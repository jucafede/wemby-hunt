#!/usr/bin/env python3
"""Chasse ciblée sur les 5 Mega Box — disponibilité et classement, quel que soit le prix."""
from __future__ import annotations
import json, re, sys, urllib.parse
from pathlib import Path

import yaml

import external_engine as xe
import liveness as lv
import nba_gate as ng
import nba_probe as npb
import offers
from mega_targets import TARGETS, PAR_UPC, PAR_SKU, UPC_VOISINS

ROOT = Path(__file__).parent
SAISON = re.compile(r"2023[-/ ]?24|23[-/]24|2023[-/]2024", re.I)
MEGA = re.compile(r"\bmega\b", re.I)
# Panini décline « Select Mega Box » sur presque tous ses sports et toutes ses ligues. Sans
# cette liste, une Mega Premier League ou Road to FIFA remonte comme candidate basket.
HORS = re.compile(r"euro\s*league|turkish|draft\s*picks?|collegiate|monopoly|\bdeca\b|wnba|"
                  r"football|soccer|\bnfl\b|baseball|hockey|\bwwe\b|"
                  r"premier\s*league|\bepl\b|la\s*liga|serie\s*a\b|bundesliga|ligue\s*1|"
                  r"\bfifa\b|world\s*cup|\buefa\b|\bnbl\b|overtime\s*elite|\bote\b", re.I)
LOT = re.compile(r"\blot\b|\bcase\b|\bbundle\b|\bx\s?[2-9]\b|\bbreak\b|\bspot\b", re.I)
CONF = re.compile(r"(\d{1,2})\s*(?:packs?|pks?)[^\d]{0,12}(\d{1,2})\s*cards?"
                  r"|(\d{1,2})\s*cards?[^\d]{0,12}(\d{1,2})\s*packs?", re.I)


def identifie(titre: str, texte: str = "", sku_vendeur: str = "") -> dict:
    """L'échelle de confiance, du plus sûr au plus faible. Rien en dessous d'un alias."""
    blob = f"{titre} {texte} {sku_vendeur}"
    chiffres = re.sub(r"[^0-9]", "", blob)

    # 1 · UPC exact — la seule preuve qui ne dépend pas de la prose du vendeur
    for upc, t in PAR_UPC.items():
        if upc in chiffres or upc in blob:
            return {"target": t, "confiance": "UPC_EXACT", "preuve": f"UPC {upc}"}
    for mauvais, quoi in UPC_VOISINS.items():
        if mauvais in chiffres:
            return {"target": None, "confiance": "UPC_VOISIN", "preuve": quoi}

    # 2 · SKU fabricant
    for sku, t in PAR_SKU.items():
        if sku.lower().replace(" ", "") in blob.lower().replace(" ", ""):
            return {"target": t, "confiance": "SKU_FABRICANT", "preuve": f"SKU {sku}"}

    # 3 · année + set + format + VARIANTE nommée. La variante est obligatoire : sans elle on
    #     mélangerait les trois Select, dont deux n'ont même pas le même nombre de cartes.
    # Le filtre des ligues s'applique au TITRE seul. Sur le texte entier d'une page, le menu
    # d'une boutique multi-sports contient « football » et écarterait une Mega basket légitime.
    if HORS.search(titre) or LOT.search(titre):
        return {"target": None, "confiance": "HORS_PERIMETRE", "preuve": None}
    if not (SAISON.search(blob) and MEGA.search(blob)):
        return {"target": None, "confiance": "HORS_PERIMETRE", "preuve": None}
    for t in TARGETS:
        jeu = "prizm" if "Prizm" in t["set"] else "select"
        if not re.search(rf"\b{jeu}\b", blob, re.I):
            continue
        if re.search(t["variant_rx"], blob, re.I):
            return {"target": t, "confiance": "SET_FORMAT_VARIANTE",
                    "preuve": f"{jeu} + variante « {t['variant']} » nommée"}

    # 4 · alias textuel exact
    for t in TARGETS:
        for a in t["aliases"]:
            if a.lower() in blob.lower() and re.search(t["variant_rx"], a, re.I):
                return {"target": t, "confiance": "ALIAS", "preuve": f"alias « {a} »"}

    # un Mega 2023-24 sans variante nommée : on sait que c'est proche, pas lequel
    jeu = "Prizm" if re.search(r"\bprizm\b", blob, re.I) else (
          "Select" if re.search(r"\bselect\b", blob, re.I) else None)
    if jeu:
        return {"target": None, "confiance": "AMBIGU",
                "preuve": f"Mega {jeu} 2023-24 sans variante nommée — non attribuable"}
    return {"target": None, "confiance": "HORS_PERIMETRE", "preuve": None}


def valide_config(t: dict, blob: str) -> str | None:
    """Le nombre de packs/cartes confirme ou contredit l'identification.

    Blue/Pink fait 32 cartes, Red/Purple et Green Shock en font 40 : quand le vendeur affiche
    sa configuration, elle tranche sans l'UPC.
    """
    m = CONF.search(blob)
    if not m:
        return None
    g = [x for x in m.groups() if x]
    if len(g) < 2:
        return None
    a, b = int(g[0]), int(g[1])
    packs, cartes = (a, b) if a <= 12 and b >= 4 else (b, a)
    if packs == t["packs_per_box"] and cartes == t["cards_per_pack"]:
        return f"config confirmée {packs}×{cartes}"
    return f"⚠️ config lue {packs}×{cartes}, attendu {t['packs_per_box']}×{t['cards_per_pack']}"


# Shopify plafonne sa recherche à dix résultats : ce qui remonte dépend donc du classement,
# pas seulement du catalogue. La Mega Prizm 2023-24 « Pink Ice » de World Champion est
# apparue à un passage et pas au suivant, sans que rien change chez le marchand — elle
# n'était nommée par aucune requête. « Pink Ice » et « Hyper Pink » sont des variantes Mega
# de l'ère Wemby que nos cinq clés ne couvrent pas : c'est précisément ce que l'AMBIGU doit
# attraper, et il ne l'attrape que si on le demande.
REQUETES = ["prizm mega", "select mega", "mega box", "red ice", "green ice",
            "cracked ice", "green shock", "wembanyama mega", "pink ice", "hyper pink"]


def _prix(v):
    """Shopify rend « 110.00 », WooCommerce rend des centimes : ici, un nombre ou rien.

    Un prix laissé en texte a fait tomber la persistance au premier comparatif de baisse —
    `'110.00' < 108.0` n'a pas de sens en Python, et tout le passage s'est arrêté après le
    crawl, juste avant d'écrire. Un champ mal typé ne doit pas coûter une passe entière.
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def cherche(base, q, limit=20):
    out = []
    st, b, _ = xe.fetch(f"{base}/search/suggest.json?q={urllib.parse.quote(q)}"
                        f"&resources[type]=product&resources[limit]={limit}", timeout=12)
    if st == 200 and (b or "").strip().startswith("{"):
        try:
            for p in json.loads(b)["resources"]["results"]["products"]:
                out.append({"titre": p.get("title", ""), "url": base + (p.get("url") or ""),
                            "prix": _prix(p.get("price")), "dispo": bool(p.get("available")),
                            "plat": "shopify"})
        except Exception:
            pass
    if out:
        return out
    st, b, _ = xe.fetch(f"{base}/wp-json/wc/store/v1/products?search={urllib.parse.quote(q)}"
                        f"&per_page={limit}", timeout=12)
    if st == 200 and (b or "").strip().startswith("["):
        try:
            for p in json.loads(b):
                pr = p.get("prices") or {}
                mn = int(pr.get("currency_minor_unit", 2) or 2)
                out.append({"titre": p.get("name", ""), "url": p.get("permalink", ""),
                            "prix": _prix((float(pr.get("price") or 0) / (10 ** mn)) or None),
                            "dispo": bool(p.get("is_in_stock")), "plat": "woocommerce",
                            "devise": pr.get("currency_code"), "sku": p.get("sku") or ""})
        except Exception:
            pass
    return out


def main():
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]
    reg = json.loads((ROOT / "discovered" / "candidate_domains.json").read_text(encoding="utf-8"))
    boutiques = {}
    for s in src:
        if s.get("type") in ("marketplace", "eu_reference") or s.get("status") == "reject":
            continue
        if s.get("robots_disallow") or s.get("crawl_blocked"):
            continue
        boutiques[s["base_url"].rstrip("/")] = {"key": s["key"], "pays": s.get("country"),
                                                "devise": s.get("currency"), "trust": s.get("trust"),
                                                "risk": s.get("seller_risk")}
    for d in reg.get("domains", []):
        if d.get("reachable") is not False:
            boutiques.setdefault(f"https://{d['domain']}",
                                 {"key": d["domain"], "pays": None, "devise": None,
                                  "trust": None, "risk": None})
    # SONDE DE VIVACITÉ AVANT TOUTE INTERROGATION
    # -------------------------------------------
    # Le DNS d'abord : un domaine mort ne coûte alors AUCUNE requête au marchand. Un domaine
    # BLOQUÉ n'est pas un domaine mort — il est simplement écarté de cette passe, et reste
    # une boutique du registre. Aucun état de vivacité ne dit quoi que ce soit du catalogue.
    doms = {base: urllib.parse.urlsplit(base).netloc for base in boutiques}
    etats = {e["domain"]: e for e in lv.sonde_tous(list(doms.values()), journal=print)}
    ecartes = {b: etats[d]["state"] for b, d in doms.items()
               if etats.get(d, {}).get("state") not in lv.EXPLOITABLE}
    boutiques = {b: m for b, m in boutiques.items() if b not in ecartes}
    print(f"CHASSE MEGA — {len(boutiques)} boutiques vivantes interrogées "
          f"({len(ecartes)} écartées : non lues, PAS jugées)\n")

    trouves, ambigus, vus = [], [], set()
    nba_par_boutique: dict[str, list] = {}
    for base, m in boutiques.items():
        # TOUTES les requêtes, sur CHAQUE boutique. S'arrêter à la première qui rend quelque
        # chose revenait à ne chercher que « prizm mega » partout : « green shock » et
        # « cracked ice » n'étaient jamais posées, et trois des cinq cibles restaient
        # invisibles. Sur une chasse ciblée, le rappel prime sur le nombre de requêtes.
        vide = 0
        for q in REQUETES:
            res = cherche(base, q)
            if not res:
                vide += 1
                if vide >= 3:      # la boutique ne répond à rien : inutile d'insister
                    break
                continue
            for r in res:
                # Tout scellé NBA lu ici alimente le score d'ancienneté, cible ou non :
                # c'est la profondeur du rayon qui le mesure, pas nos cinq références.
                if ng.est_scelle_nba(r["titre"]):
                    nba_par_boutique.setdefault(m["key"], []).append(
                        {"titre": r["titre"], "url": r["url"], "prix": r.get("prix"),
                         "dispo": bool(r.get("dispo")), "saison": ng.saison(r["titre"]),
                         "annee": ng.annee_debut(r["titre"])})
                if r["url"] in vus:
                    continue
                blob = f"{r['titre']} {r.get('sku','')}"
                ident = identifie(r["titre"], sku_vendeur=r.get("sku", ""))
                if ident["confiance"] == "HORS_PERIMETRE":
                    continue
                vus.add(r["url"])
                rec = {**r, **m, "confiance": ident["confiance"], "preuve": ident["preuve"],
                       "cible": (ident["target"] or {}).get("id"),
                       "libelle": (ident["target"] or {}).get("libelle")}
                if ident["target"]:
                    rec["config"] = valide_config(ident["target"], blob)
                    trouves.append(rec)
                    print(f"  {'IN ' if r['dispo'] else 'OOS'} {ident['confiance']:<20} "
                          f"{m['key']:<20} {str(r['prix']):>9} {r['titre'][:52]}")
                else:
                    ambigus.append(rec)
                    print(f"  {'IN ' if r['dispo'] else 'OOS'} {'AMBIGU':<20} "
                          f"{m['key']:<20} {str(r['prix']):>9} {r['titre'][:52]}")
    # PERSISTANCE DANS LA COUCHE OFFER
    # --------------------------------
    # Les résultats partaient dans un fichier temporaire de session, hors du dépôt : la
    # trouvaille du jour disparaissait avec la session. Elles vont désormais dans
    # discovered/offers.json, la seule mémoire des observations produit × boutique.
    #
    # Les AMBIGU y entrent AUSSI, avec product_id = None. Les écarter parce qu'aucune cible
    # ne leur est attribuée perdrait exactement ce qu'on cherche : une Mega Prizm 2023-24 en
    # rayon dont la variante ne porte pas l'un de nos cinq suffixes.
    d = offers.charge()
    scores = {k: npb.old_stock_v2(v) for k, v in nba_par_boutique.items()}
    evenements = []
    for rec in trouves + ambigus:
        sc = scores.get(rec.get("key") or "", (0, [], {}))
        evt = offers.upsert(d, {
            "product_id": rec.get("cible"),          # None pour un AMBIGU : c'est voulu
            "shop_id": rec.get("key"), "url": rec.get("url"),
            "price": rec.get("prix"), "currency": rec.get("devise") or "USD",
            "stock_status": offers.IN_STOCK if rec.get("dispo") else offers.OUT_OF_STOCK,
            "stock_qty": None, "shipping_france": None, "shipping_cost": None,
            "landed_price_france": None,
            "match_method": rec.get("confiance"), "confidence": rec.get("preuve"),
            "titre_observe": rec.get("titre"),
            "old_stock_score": sc[0], "old_stock_motifs": sc[1]})
        evenements.append(evt)
    offers.sauve(d)
    live = [t for t in trouves if t["dispo"]]
    from collections import Counter
    print(f"\n{len(trouves)} fiche(s) identifiée(s) · {len(live)} EN STOCK · "
          f"{len(ambigus)} ambiguë(s) non attribuée(s)")
    print(f"offers.json : {len(d['offers'])} offres · événements {dict(Counter(evenements))}")
    if not trouves and not ambigus:
        print(offers.formule_absence(len(boutiques),
                                     sorted({v for v in ecartes.values()}) or None))


if __name__ == "__main__":
    main()
