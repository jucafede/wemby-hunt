#!/usr/bin/env python3
"""OBSERVATIONS MANUELLES — donnée de première classe, au même rang que le crawl.

POURQUOI CE MODULE EXISTE
-------------------------
Le 15/09, la chasse européenne a conclu « EUROPEAN GEMS : aucune » alors que cinq boutiques
européennes avaient du stock vérifié à la main. La conclusion était fausse, et sa cause tenait
en une confusion : le moteur ne savait représenter que ce qu'il avait lu lui-même. Tout ce
qu'un humain avait vu n'existait pas.

Or un site qui nous refuse l'accès ne disparaît pas du marché. Hokej-Karty nous interdit
nommément par robots.txt ; SuperCollectors répond 403 à toute requête. Leurs prix restent des
prix, et leur stock reste du stock.

Une observation humaine entre donc ici avec le MÊME statut qu'une lecture automatique. Elle
porte simplement sa provenance — `MANUAL_VERIFIED` au lieu de `CRAWLER_VERIFIED` — et cette
provenance se lit partout où la ligne apparaît. Elle ne vaut pas moins : elle vaut autrement,
et souvent mieux, puisqu'un humain a vu la page.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne contourne rien. Quand un site nous autorise, on l'enrichit en lisant sa page ; quand il
nous refuse, on se contente de ce que l'utilisateur a relevé. Le refus est respecté dans les
deux cas — il cesse simplement d'effacer l'information.
"""
from __future__ import annotations
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

import yaml

import hunt

ROOT = Path(__file__).parent
OBS = ROOT / "discovered" / "manual_observations.json"

CRAWLER_VERIFIED = "CRAWLER_VERIFIED"
MANUAL_VERIFIED = "MANUAL_VERIFIED"

# États de stock quantitatif. Une quantité qui ne bouge pas est une information à part entière :
# du stock que personne ne touche, souvent le plus négociable.
STOCK_MOVING = "STOCK_MOVING"
LOW_STOCK = "LOW_STOCK"
LAST_UNIT = "LAST_UNIT"
RESTOCK = "RESTOCK"
SOLD_OUT = "SOLD_OUT"
DORMANT_STOCK = "DORMANT_STOCK"
DORMANT_JOURS = 21


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def charge() -> dict:
    if OBS.exists():
        return json.loads(OBS.read_text(encoding="utf-8"))
    return {"generated_at": None, "observations": [],
            "price_history": [], "stock_history": []}


def sauve(d: dict):
    d["generated_at"] = now()
    OBS.parent.mkdir(exist_ok=True)
    OBS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def hote(url: str) -> str:
    h = (url or "").split("//")[-1].split("/")[0].lower()
    return h[4:] if h.startswith("www.") else h


def identifie_vendeur(url: str, sources: list) -> tuple:
    """(clé, métadonnées) du vendeur, depuis sources.yaml — ou un vendeur inconnu nommé."""
    h = hote(url)
    for s in sources:
        if hote(s.get("base_url", "")) == h:
            return s["key"], s
    return h, {"key": h, "country": None, "currency": None, "trust": None,
               "status": "non enregistré"}


def identifie_produit(titre: str, skus: list) -> dict:
    """Identité produit par le matcher du moteur. Aucune seconde logique d'identité."""
    m = hunt.match_title(titre or "", skus)
    s = next((x for x in skus if x["id"] == m.sku_id), None)
    tn = hunt.norm(titre or "")
    return {"sku_id": m.sku_id, "score": m.score,
            "format": (s or {}).get("format"), "season": (s or {}).get("season"),
            "league": (s or {}).get("league"), "wemby_rc": (s or {}).get("wemby_rc"),
            "quantity": max(1, hunt.parse_quantity(tn) or 1),
            "exact_comp_key": hunt.exact_comp_key(m.sku_id or "UNKNOWN", tn, s or {}, "")
                              if m.sku_id else None}


def etat_quantite(avant: int | None, apres: int | None, depuis_jours: float | None) -> list:
    """Les transitions que la quantité révèle, et elles seules."""
    out = []
    if apres is None:
        return out
    if apres == 0:
        if avant:
            out.append(SOLD_OUT)
        return out
    if avant == 0:
        out.append(RESTOCK)
    if avant is not None and apres < avant:
        out.append(STOCK_MOVING)
    if apres == 1:
        out.append(LAST_UNIT)
    elif apres <= 2:
        out.append(LOW_STOCK)
    if (avant is not None and avant == apres and depuis_jours is not None
            and depuis_jours >= DORMANT_JOURS):
        out.append(DORMANT_STOCK)
    return out


# ---------------------------------------------------------------- comparaison inter-boutiques
def toutes_les_offres_live(skus: list, sources: list) -> list:
    """TOUTES les offres vivantes connues, crawl ET relevés manuels, dans un format commun.

    C'est la table qu'il faut consulter avant d'écrire « affaire » quelque part. Le 15/09,
    Bandurka a failli être annoncée à 36,60 € comme un bon prix alors que SuperCollectors
    affichait 25 € — sauf qu'après vérification ce n'était même pas le même produit. Les deux
    erreurs viennent de la même cause : un prix jugé seul.
    """
    live = []
    # 1 · ce que le crawler a lu
    p = ROOT / "discovered" / "prizm_core.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8")).get("listings", []):
            if not r.get("available"):
                continue
            live.append({"sku_id": r.get("sku_id"), "exact_comp_key": None,
                         "titre": r.get("title"), "prix": r.get("unit_price") or r.get("price"),
                         "devise": r.get("currency", "USD"), "seller": r.get("shop"),
                         "pays": r.get("country"), "url": r.get("url"),
                         "evidence_type": CRAWLER_VERIFIED, "quantite": None,
                         "vu_le": (r.get("seen_at") or "")[:10]})
    # 2 · ce qu'un humain a vérifié — même rang, provenance différente
    for o in charge().get("observations", []):
        if o.get("stock") in ("sold_out", "oos"):
            continue
        live.append({"sku_id": o.get("sku_id"), "exact_comp_key": o.get("exact_comp_key"),
                     "titre": o.get("titre"), "prix": o.get("prix"),
                     "devise": o.get("devise"), "seller": o.get("seller"),
                     "pays": o.get("pays"), "url": o.get("url"),
                     "evidence_type": MANUAL_VERIFIED, "quantite": o.get("quantite"),
                     "vu_le": (o.get("observed_at") or "")[:10]})
    # Les boutiques dont on n'a pas confirmé si le prix affiché est HT ou TTC ne peuvent PAS
    # porter un « plus bas ». shopuscards enregistre 116,66 € quand sa page annonce 139,99 € —
    # exactement ×1,20. Annoncer 116,66 € comme meilleur prix européen ferait perdre un achat
    # au profit d'un prix qui n'existe pas. On les garde visibles, on leur retire le droit de
    # fixer un plancher.
    ht = {s["key"] for s in sources if s.get("price_display_warning") or s.get("ht_unconfirmed")}
    for r in live:
        if r.get("seller") in ht:
            r["prix_ht_non_confirme"] = True
        if r["sku_id"] and not r["exact_comp_key"]:
            s = next((x for x in skus if x["id"] == r["sku_id"]), {})
            r["exact_comp_key"] = hunt.exact_comp_key(r["sku_id"], hunt.norm(r["titre"] or ""), s, "")
    return live


def en_eur(prix, devise, fx_usd_eur: float) -> float | None:
    """Une comparaison de prix n'a de sens qu'en une seule monnaie."""
    if prix is None:
        return None
    taux = {"EUR": 1.0, "USD": fx_usd_eur, "GBP": 1.17, "SEK": 0.087, "CZK": 0.0405,
            "PLN": 0.233, "CHF": 1.06}
    t = taux.get((devise or "USD").upper())
    return round(prix * t, 2) if t else None


def compare(offre: dict, live: list, fx: float) -> dict:
    """Situe une offre parmi TOUTES celles qui partagent son exact_comp_key.

    Sans cloison identique, aucune comparaison : deux formats différents ne se comparent pas,
    même quand leurs noms se ressemblent. « Value Box » et « Blaster Box » sont deux produits.
    """
    cle = offre.get("exact_comp_key")
    if not cle:
        return {"comparable": False, "raison": "produit non identifié — aucune comparaison possible"}
    pairs = [r for r in live if r.get("exact_comp_key") == cle and r.get("prix")
             and not r.get("prix_ht_non_confirme")]
    exclus_ht = [r for r in live if r.get("exact_comp_key") == cle and r.get("prix_ht_non_confirme")]
    if not pairs:
        return {"comparable": False, "raison": "aucune autre offre vivante sur ce produit"}
    # Une offre dont on ignore si le prix est HT ou TTC ne revendique aucun plancher — pas
    # même le sien. Sinon shopuscards s'annonce « plus bas mondial » à 116,66 € alors que sa
    # page réclame 139,99 € au passage en caisse.
    if offre.get("prix_ht_non_confirme") or offre.get("seller") in {
            r.get("seller") for r in live if r.get("prix_ht_non_confirme")}:
        return {"comparable": False,
                "raison": ("prix affiché probablement HT et non confirmé TTC — cette offre ne "
                           "peut ni porter un plus-bas ni servir de référence")}
    px = en_eur(offre.get("prix"), offre.get("devise"), fx)
    valeurs = [(en_eur(r["prix"], r["devise"], fx), r) for r in pairs]
    valeurs = [(v, r) for v, r in valeurs if v is not None]
    if px is None or not valeurs:
        return {"comparable": False, "raison": "prix non convertible"}
    mini_eur, mini_r = min(valeurs, key=lambda x: x[0])
    eu = [(v, r) for v, r in valeurs if (r.get("pays") or "").upper() in
          ("FR","ES","DE","IT","NL","GR","PL","CZ","SE","BE","AT","PT","SK","RS")]
    mini_eu = min(eu, key=lambda x: x[0])[0] if eu else None
    # « PLUS BAS MONDIAL » est une affirmation sur le monde. Nous ne connaissons qu'une base.
    # Tant que la découverte est incomplète — et elle l'est, faute de clé de moteur — la seule
    # phrase vraie est « la plus basse offre vivante QUE NOUS CONNAISSONS ». La nuance n'est pas
    # cosmétique : elle dit à l'acheteur s'il peut arrêter de chercher.
    return {"comparable": True, "n_offres": len(valeurs),
            "exclus_ht": [r.get("seller") for r in exclus_ht],
            "libelle_plus_bas": "LOWEST KNOWN LIVE OFFER",
            "prix_eur": px, "lowest_known_eur": mini_eur,
            "lowest_known_seller": mini_r.get("seller"),
            "lowest_known_europe_eur": mini_eu,
            "is_lowest_known": px <= mini_eur + 0.01,
            "is_lowest_known_europe": mini_eu is not None and px <= mini_eu + 0.01,
            "ecart_vs_lowest_known_pct": round((px - mini_eur) / mini_eur * 100, 1) if mini_eur else None}


def verdict_sold(sku_id: str, prix_eur: float, skus: list, fx: float) -> dict:
    """Comparaison au marché des VENTES RÉALISÉES, ou rien.

    La règle du projet ne change pas parce qu'une offre vient d'Europe : sans transaction
    connue, il n'y a pas de verdict d'achat, et un prix demandé ne remplace pas une vente.
    """
    s = next((x for x in skus if x["id"] == sku_id), None)
    if not s:
        return {"base": None, "verdict": "INSUFFICIENT SOLD DATA"}
    sold = s.get("market_sold_us")
    if not sold:
        return {"base": None, "verdict": "INSUFFICIENT SOLD DATA",
                "why": "aucune vente réalisée en base pour ce SKU"}
    ref = round(float(sold) * fx, 2)
    ecart = round((prix_eur - ref) / ref * 100, 1)
    v = ("STRONG BUY" if ecart <= -25 else "BUY" if ecart <= -10
         else "MARKET" if ecart <= 10 else "EXPENSIVE")
    return {"base": ref, "ecart_pct": ecart, "verdict": v,
            "source": s.get("market_sold_source"), "checked_at": s.get("market_sold_checked_at")}


def ajoute(url: str, prix=None, devise=None, stock=None, quantite=None,
           titre=None, note=None) -> dict:
    """Ingère une observation humaine et rend un verdict immédiat.

    On enrichit depuis la page UNIQUEMENT si le site nous y autorise. S'il nous refuse, on
    travaille avec ce que l'utilisateur a relevé — sans jamais forcer la porte.
    """
    import external_engine as xe
    cat = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))
    skus, fx = cat["skus"], float(cat["fx_usd_eur"])
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]

    autorise = xe.robots_ok(url)
    lu = {}
    if autorise and not titre:
        st, body, _ = xe.fetch(url, timeout=14)
        if st == 200 and body:
            t, px, cur, av = xe.read_offer(body)
            lu = {"titre": t, "prix": px, "devise": cur, "dispo": av}
    titre = titre or lu.get("titre") or url.rstrip("/").split("/")[-1].replace("-", " ")
    prix = prix if prix is not None else lu.get("prix")
    devise = devise or lu.get("devise")

    cle_v, meta_v = identifie_vendeur(url, src)
    devise = devise or meta_v.get("currency") or "EUR"
    ident = identifie_produit(titre, skus)

    d = charge()
    anciennes = [o for o in d["observations"] if o.get("url") == url]
    avant = anciennes[-1] if anciennes else None
    depuis = None
    if avant and avant.get("quantite") is not None:
        try:
            depuis = (datetime.fromisoformat(now()) -
                      datetime.fromisoformat(avant["observed_at"])).days
        except Exception:
            depuis = None
    transitions = etat_quantite(avant.get("quantite") if avant else None, quantite, depuis)
    if avant and avant.get("prix") and prix and prix < avant["prix"] * 0.95:
        transitions.append("PRICE_DROP")

    obs = {"url": url, "titre": titre, "prix": prix, "devise": devise,
           "prix_eur": en_eur(prix, devise, fx),
           "stock": stock or ("in_stock" if (quantite or 0) > 0 else None),
           "quantite": quantite, "seller": cle_v, "pays": meta_v.get("country"),
           "seller_trust": meta_v.get("trust"), "seller_status": meta_v.get("status"),
           "evidence_type": MANUAL_VERIFIED,
           "page_lue": bool(lu), "robots_autorise": autorise,
           "observed_at": now(), "note": note, **ident, "transitions": transitions}
    d["observations"] = [o for o in d["observations"] if o.get("url") != url] + [obs]
    d.setdefault("price_history", []).append(
        {"t": obs["observed_at"], "url": url, "seller": cle_v,
         "exact_comp_key": ident["exact_comp_key"], "prix": prix, "devise": devise,
         "prix_eur": obs["prix_eur"], "evidence_type": MANUAL_VERIFIED})
    if quantite is not None:
        d.setdefault("stock_history", []).append(
            {"t": obs["observed_at"], "seller": cle_v, "product": titre,
             "exact_comp_key": ident["exact_comp_key"], "quantity": quantite,
             "transitions": transitions})
    sauve(d)

    live = toutes_les_offres_live(skus, src)
    cmp_ = compare(obs, live, fx)
    sold = verdict_sold(ident["sku_id"], obs["prix_eur"], skus, fx) if obs["prix_eur"] else {}
    return {"observation": obs, "comparaison": cmp_, "sold": sold}
