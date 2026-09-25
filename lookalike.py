#!/usr/bin/env python3
"""LOOKALIKE DISCOVERY — chercher les sosies de nos meilleures boutiques.

LE RENVERSEMENT
---------------
La découverte nationale demandait « laquelle de ces 3 281 boutiques a l'air intéressante ? »
et, faute de savoir, ouvrait 2 298 pages d'accueil. Celle-ci demande « laquelle ressemble le
plus à celles qui nous ont DÉJÀ servi ? » — et la réponse se lit dans l'annuaire, sans
solliciter un seul serveur marchand.

CE QUI SERT D'EMPREINTE
-----------------------
Pas des déclarations : nos propres relevés. 214 900 fiches déjà collectées disent, boutique
par boutique, quelle part du catalogue est du basket scellé, quelle marque domine, si le
2023-24 y traîne encore. Une boutique qui vend 908 boîtes scellées dont 663 Panini et 159 en
2023-24 est un modèle ; une qui affiche 30 713 produits tous en 2025-26 est un breaker, et
n'en est pas un.

CE QUE LA SIMILARITÉ PEUT VOIR, ET CE QU'ELLE NE PEUT PAS
----------------------------------------------------------
Elle compare ce que l'ANNUAIRE publie — nom, ville, État, rubriques — à ce que nous savons de
nos graines. Elle ne voit aucun catalogue. Elle ne prouve donc rien : elle ordonne une file.
Le score est une somme pondérée assumée, pas un modèle appris — l'appeler autrement serait se
mentir sur trois variables catégorielles.

ET SURTOUT
----------
Une candidate n'est PAS une recommandation. Rien ne sort en « boutique intéressante » sans
trois preuves réunies : basket SCELLÉ visible, PRIX affiché, ACHAT À DISTANCE possible.
"""
from __future__ import annotations
import json, re, sqlite3, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
SORTIE = ROOT / "discovered" / "lookalikes.json"

# ------------------------------------------------------------------ graines
# Ce qui disqualifie une boutique comme MODÈLE — pas comme marchand. Un breaker est un vrai
# commerce ; il n'est simplement pas le profil que nous cherchons à retrouver.
EXCLU_GRAINE = {
    "breaks": "breaker — vend de l'ouverture en direct, pas du scellé à emporter",
    "marketplace": "place de marché, pas une boutique identifiée",
    "eu_reference": "référence de prix européenne, hors univers de candidats américain",
}
# « Singles-heavy » ne veut pas dire « plus de singles que de scellé » : c'est le cas partout,
# une boîte scellée pèse cent cartes à l'unité. Hidden Gems affiche 4,3 % de scellé ET 236
# boîtes de basket — c'est un excellent modèle, et le premier seuil l'écartait. Ce qui
# disqualifie, c'est l'absence de PROFONDEUR scellée en valeur absolue.
SCELLE_MIN = 25          # en deçà, le profil scellé n'est pas établi
SINGLES_SEUIL = 60       # peu de scellé ET une part négligeable = boutique de singles
SINGLES_PART = 0.05
GRANDE_ENSEIGNE = 20000  # un catalogue de cette taille n'est plus un LCS indépendant


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def domaine(u: str) -> str:
    h = urllib.parse.urlsplit(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


BK = re.compile(r"basketball|\bnba\b|\bhoops\b|court\s*kings", re.I)
SE = re.compile(r"hobby\s*box|blaster|mega\s*box|booster\s*box|retail\s*box|hobby\s*case|"
                r"hanger|fat\s*pack|jumbo\s*box|sealed|wax\s*box|value\s*box", re.I)
MARQUES = ("panini", "prizm", "select", "optic", "phoenix", "mosaic", "hoops", "donruss")


def profils_catalogue(db: Path) -> dict:
    """Ce que NOS relevés disent de chaque boutique. Aucune requête réseau."""
    c = sqlite3.connect(db)
    out: dict[str, dict] = defaultdict(lambda: {"n": 0, "bk": 0, "sealed": 0, "s2324": 0,
                                                "vieux": 0, "dispo": 0,
                                                **{m: 0 for m in MARQUES}})
    for shop, titre, fmt, sport, dispo in c.execute(
            "select shop, title, fmt, sport, available from products_raw"):
        d = out[shop]
        t = titre or ""
        d["n"] += 1
        d["dispo"] += 1 if dispo else 0
        bk = bool(BK.search(t)) or (sport or "").lower().startswith("basket")
        if not bk:
            continue
        d["bk"] += 1
        if not (SE.search(t) or (fmt or "") not in ("", None, "Single", "Pack")):
            continue
        d["sealed"] += 1
        if re.search(r"2023[-/ ]?24|23[-/]24", t):
            d["s2324"] += 1
        if re.search(r"20(1\d|2[0-2])[-/ ]?\d{2}", t):
            d["vieux"] += 1
        for m in MARQUES:
            if re.search(m, t, re.I):
                d[m] += 1
    c.close()
    return dict(out)


# Les notes du registre portent une géographie que le YAML n'a pas structurée.
ETATS = {"alabama": "AL", "arizona": "AZ", "arkansas": "AR", "california": "CA",
         "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL",
         "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
         "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
         "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
         "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
         "nevada": "NV", "new-hampshire": "NH", "new-jersey": "NJ", "new-mexico": "NM",
         "new-york": "NY", "north-carolina": "NC", "north-dakota": "ND", "ohio": "OH",
         "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode-island": "RI",
         "south-carolina": "SC", "south-dakota": "SD", "tennessee": "TN", "texas": "TX",
         "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
         "west-virginia": "WV", "wisconsin": "WI", "wyoming": "WY"}
VILLE_ETAT = {"las vegas": "NV", "nyc": "NY", "new york": "NY", "pittsburgh": "PA",
              "shelby township": "MI", "phoenix": "AZ", "los angeles": "CA",
              "bay area": "CA", "broken arrow": "OK", "amersfoort": None,
              "floride": "FL", "missouri": "MO", "columbia": None}
# Régions : deux États d'une même région forment un « marché comparable » au sens de la
# consigne, sans prétendre à une distance kilométrique que nous n'avons pas.
REGIONS = {
    "NE": {"ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA"},
    "SE": {"DE", "MD", "VA", "WV", "NC", "SC", "GA", "FL", "KY", "TN", "AL", "MS", "AR", "LA"},
    "MW": {"OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS"},
    "SW": {"TX", "OK", "NM", "AZ"},
    "W": {"CO", "WY", "MT", "ID", "UT", "NV", "CA", "OR", "WA", "AK", "HI"},
}


def region(etat: str | None) -> str | None:
    return next((r for r, e in REGIONS.items() if etat in e), None) if etat else None


def geo_depuis_notes(s: dict) -> tuple[str | None, str | None]:
    """La géographie que nous avons déjà écrite, sans rien inventer."""
    if s.get("state"):
        return s["state"], s.get("city")
    blob = f"{s.get('notes') or ''}"
    for ville, et in VILLE_ETAT.items():
        if re.search(rf"\b{re.escape(ville)}\b", blob, re.I) and et:
            return et, ville.title()
    m = re.search(r"\b([A-Z]{2})\b(?=[\s.,]|$)", blob)
    if m and m.group(1) in ETATS.values():
        return m.group(1), None
    return None, None


# ------------------------------------------------------------------ sélection
def graines(db: Path = ROOT / "hunt.db", journal=print) -> list[dict]:
    """Les boutiques qui MÉRITENT d'être imitées, choisies sur preuve, pas sur réputation."""
    prof = profils_catalogue(db)
    reg = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]
    idx = json.loads((ROOT / "discovered" / "national_index.json").read_text(encoding="utf-8"))
    par_dom = {c["domain"]: c for c in idx["candidates"]}
    out, rejets = [], []
    for s in reg:
        k, dom = s["key"], domaine(s.get("base_url") or "")
        p = prof.get(k)
        motif = None
        if s.get("type") in EXCLU_GRAINE:
            motif = EXCLU_GRAINE[s["type"]]
        elif s.get("status") == "reject":
            motif = "boutique déjà rejetée dans le registre"
        elif (s.get("seller_risk") or "").upper() == "HIGH" or s.get("crawl_blocked"):
            motif = "vendeur à risque élevé — pas un modèle"
        elif s.get("country") not in (None, "US"):
            motif = f"hors univers de candidats (pays {s.get('country')})"
        elif "national shop discovery" in (s.get("discovery_method") or ""):
            # Découverte par la passe nationale d'hier : la prendre pour modèle reviendrait à
            # mesurer une méthode avec ses propres résultats. Et une boutique qualifiée n'a
            # pas encore d'HISTOIRE — ni prix utile, ni déstockage, ni restock observés.
            motif = "issue de la passe nationale — modèle circulaire, aucun historique de chasse"
        elif not p or p["sealed"] < SCELLE_MIN:
            motif = (f"scellé basket non établi dans nos relevés "
                     f"({(p or {}).get('sealed', 0)} fiche(s))")
        elif p["n"] > GRANDE_ENSEIGNE:
            motif = (f"grande enseigne — {p['n']} fiches, ce n'est plus un LCS indépendant")
        elif (p["sealed"] < SINGLES_SEUIL and p["sealed"] / p["n"] < SINGLES_PART
              and p["s2324"] < 10):
            # Une densité 2023-24 réelle prime sur le ratio : E5 Sports n'a que 26 boîtes,
            # mais 14 sont de la saison recherchée. C'est le profil, pas le volume, qui compte.
            motif = (f"catalogue de singles — {p['sealed']} scellés sur {p['n']} fiches "
                     f"({100*p['sealed']/p['n']:.1f} %)")
        if motif:
            rejets.append({"key": k, "domain": dom, "motif": motif})
            continue
        etat, ville = geo_depuis_notes(s)
        fiche = par_dom.get(dom)
        if fiche:
            etat = etat or ETATS.get(fiche["state"])
            ville = ville or (fiche.get("cities") or [None])[0]
        nom = s.get("name") or k
        vide = {"n": 0, "bk": 0, "sealed": 0, "s2324": 0, "vieux": 0, "dispo": 0,
                **{m: 0 for m in MARQUES}}
        p = p or vide
        sans_releve = p["n"] == 0
        out.append({
            "catalogue_releve": not sans_releve,
            "key": k, "name": nom, "domain": dom,
            # GÉOGRAPHIE — UNKNOWN reste UNKNOWN
            "state": etat, "city": ville, "region": region(etat),
            "dans_annuaire": bool(fiche),
            "categories_annuaire": (fiche or {}).get("categories") or [],
            # COMMERCE
            "platform": s.get("platform"), "purchase_mode": s.get("purchase_mode"),
            # CATALOGUE — nos propres relevés
            "fiches": p["n"], "basket": p["bk"], "scelle": p["sealed"],
            "part_scelle": round(p["sealed"] / max(p["n"], 1), 3),
            "s2324": p["s2324"], "vieux_wax": p["vieux"],
            "marques": {m: p[m] for m in MARQUES if p[m]},
            "part_panini": round(p["panini"] / max(p["sealed"], 1), 2),
            # PROFIL
            "specialiste": bool(re.search(r"sports?\s*cards?", nom, re.I)),
            "trust": s.get("trust"), "notes": (s.get("notes") or "")[:160],
            "preuve_registre": (s.get("qualification_evidence") or None) if sans_releve else None,
        })
    journal(f"{len(out)} graines retenues, {len(rejets)} écartées")
    return sorted(out, key=lambda g: -g["scelle"]), rejets


def raison_graine(g: dict) -> str:
    r = [f"{g['scelle']} fiches de basket scellé relevées chez nous"]
    if g["s2324"]:
        r.append(f"{g['s2324']} en 2023-24 — la saison recherchée")
    if g["vieux_wax"]:
        r.append(f"{g['vieux_wax']} millésimes antérieurs encore listés")
    if g["part_panini"] >= 0.4:
        r.append(f"Panini domine ({int(100*g['part_panini'])} % du scellé)")
    for m in ("prizm", "select", "optic", "phoenix", "mosaic"):
        if g["marques"].get(m):
            r.append(f"{m.title()} présent ({g['marques'][m]})")
    if g["part_scelle"] >= 0.5:
        r.append(f"boutique orientée scellé ({int(100*g['part_scelle'])} % du catalogue)")
    if g["specialiste"]:
        r.append("enseigne explicitement « sports cards »")
    return " · ".join(r)


# ------------------------------------------------------------------ similarité
MOT_VIDE = {"the", "and", "of", "llc", "inc", "co", "shop", "store", "card", "cards",
            "cardz", "collectibles", "collectables", "sports", "sport"}
SPECIALISTE = re.compile(r"sports?\s*cards?", re.I)
# Ce qui éloigne du profil cherché. Ce sont des MALUS de tri, jamais des rejets : une boutique
# de jeux peut très bien avoir un rayon de scellé NBA oublié, et rien ici ne le prouve.
TCG = re.compile(r"\btcg\b|pokemon|magic|yu-?gi|lorcana|anime|comics?|gaming|\bgames?\b|"
                 r"hobby\s*shop|toys?|dice|tabletop|figures?", re.I)
BREAKER = re.compile(r"\bbreaks?\b|\bbreakers?\b|case\s*break|rip\s*n", re.I)
GENERALISTE = re.compile(r"antiques?|pawn|thrift|flea|memorabilia\s*&|coins?\b|jewelry", re.I)
# Rubriques de l'annuaire : les seules que la fiche publie, et ce qu'elles valent pour nous.
RUBRIQUE_POIDS = {"online store": 6,          # un achat à distance est au moins plausible
                  "buys cards": 4,            # rachète du stock — donc en accumule de l'ancien
                  "sells cards": 2,
                  "events / tournaments": -1,  # profil animation plutôt que stock
                  "grading submissions": 1}


def jetons(nom: str) -> set:
    return {m for m in re.findall(r"[a-z0-9]+", (nom or "").lower())
            if len(m) > 2 and m not in MOT_VIDE}


def similarite(g: dict, c: dict) -> tuple[float, list[str], str]:
    """Combien cette fiche d'annuaire ressemble-t-elle à cette graine ?

    Somme pondérée transparente sur les seuls champs que l'annuaire publie. Elle ne voit
    aucun catalogue et ne prouve rien : elle ordonne une file d'attente.
    """
    pts, why = 0.0, []
    nom = c.get("shop_name") or ""
    ville = (c.get("cities") or [None])[0]
    etat = ETATS.get(c.get("state") or "")
    cats = {x.lower() for x in (c.get("categories") or [])}

    # --- géographie : le jumeau LOCAL
    local = False
    if g["state"] and etat:
        if etat == g["state"]:
            pts += 14
            why.append(f"même État que {g['key']} ({etat})")
            local = True
            if ville and g["city"] and ville.lower() == g["city"].lower():
                pts += 6
                why.append(f"même ville ({ville})")
        elif region(etat) and region(etat) == g["region"]:
            pts += 5
            why.append(f"même région ({region(etat)})")

    # --- nom : le métier annoncé
    if SPECIALISTE.search(nom):
        pts += 12
        why.append("enseigne « sports cards »")
        if g["specialiste"]:
            pts += 4
            why.append(f"comme {g['key']}")
    comm = jetons(nom) & jetons(g["name"])
    if comm:
        pts += 3 * len(comm)
        why.append(f"jetons communs : {', '.join(sorted(comm))}")

    # --- rubriques publiées
    for r, poids in RUBRIQUE_POIDS.items():
        if r in cats:
            pts += poids
            if poids > 0:
                why.append(f"rubrique « {r} »")

    # --- indépendance et taille de marché
    if (c.get("listings") or 1) == 1:
        pts += 3
        why.append("point de vente unique — LCS indépendant")
    elif (c.get("listings") or 1) > 2:
        pts -= 6
        why.append(f"enseigne à {c['listings']} adresses — profil de chaîne")
    if ville and ville.strip().lower() not in GRANDES_VILLES_LK:
        pts += 3
        why.append("petite ou moyenne ville")

    # --- ce qui éloigne du profil (malus de tri, jamais un rejet)
    if TCG.search(nom) and not SPECIALISTE.search(nom):
        pts -= 8
        why.append("nom orienté TCG / comics / jeux")
    if BREAKER.search(nom):
        pts -= 10
        why.append("nom de breaker")
    if GENERALISTE.search(nom):
        pts -= 5
        why.append("profil généraliste / brocante")

    return pts, why, ("LOCAL" if local else "PROFILE")


from hunt_priority import GRANDES_VILLES as GRANDES_VILLES_LK


# ------------------------------------------------------------------ découverte
# La consigne dit « environ 3 jumeaux locaux et 3 de profil ». À 3+3 sur 16 graines, le
# recouvrement est tel qu'il ne reste que 31 domaines uniques — trop peu pour un TOP 50, et
# trop peu pour que l'expérience dise quoi que ce soit. On élargit à 8+8 : même méthode, une
# file assez longue pour être tranchée.
TOP_LOCAL, TOP_PROFILE = 8, 8
# Ressembler à plusieurs graines est un signal, pas un multiplicateur : à +10 par graine, un
# candidat retrouvé par quatorze graines écrasait tout le classement avec +130, alors que la
# quatorzième n'apprend presque rien de plus que la quatrième.
BONUS_MULTI, BONUS_MAX = 8, 5


def connus() -> set:
    """Tout ce qu'on ne redécouvre pas : registre, candidats déjà jugés, rejets."""
    d = {domaine(s.get("base_url") or "")
         for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]}
    cand = ROOT / "discovered" / "shop_candidates.json"
    if cand.exists():
        for c in json.loads(cand.read_text(encoding="utf-8")).get("candidates", []):
            if c.get("status", "").startswith("REJECTED"):
                d.add(c["domain"])          # un rejet PROUVÉ ne se réexamine pas
    top = ROOT / "discovered" / "national_top100.json"
    if top.exists():
        for s in json.loads(top.read_text(encoding="utf-8")).get("shops", []):
            if str(s.get("status", "")).startswith("REJECTED"):
                d.add(s["domain"])
    return {x for x in d if x}


def decouvre(journal=print) -> dict:
    """Pour chaque graine, ses sosies. Aucune requête vers un site marchand."""
    g, rejets = graines(journal=journal)
    idx = json.loads((ROOT / "discovered" / "national_index.json").read_text(encoding="utf-8"))
    deja = connus()
    univers = [c for c in idx["candidates"] if c["domain"] not in deja]
    journal(f"univers de candidats : {len(univers)} domaines "
            f"({len(idx['candidates'])} indexés - {len(idx['candidates']) - len(univers)} déjà connus ou rejetés)")

    brut = 0
    par_dom: dict[str, dict] = {}
    for seed in g:
        notes = []
        for c in univers:
            sc, why, kind = similarite(seed, c)
            if sc > 0:
                notes.append((sc, why, kind, c))
        locaux = sorted([n for n in notes if n[2] == "LOCAL"], key=lambda x: -x[0])[:TOP_LOCAL]
        profils = sorted([n for n in notes if n[2] == "PROFILE"], key=lambda x: -x[0])[:TOP_PROFILE]
        for sc, why, kind, c in locaux + profils:
            brut += 1
            e = par_dom.setdefault(c["domain"], {
                "candidate_domain": c["domain"],
                "candidate_name": c.get("shop_name"),
                "city": (c.get("cities") or [None])[0],
                "state": ETATS.get(c.get("state") or "") or c.get("state"),
                "cardshopmap_url": c.get("cardshopmap_url"),
                "phone": c.get("phone"), "street_address": c.get("street_address"),
                "categories": c.get("categories") or [], "listings": c.get("listings", 1),
                "already_known": False, "matches": []})
            e["matches"].append({"source_seed": seed["key"], "twin_type": kind,
                                 "similarity_score": round(sc, 1),
                                 "similarity_reasons": why})
    journal(f"jumeaux bruts : {brut} · après dédoublonnage : {len(par_dom)}")

    for e in par_dom.values():
        m = e["matches"]
        meilleur = max(x["similarity_score"] for x in m)
        # Ressembler à PLUSIEURS graines indépendantes vaut mieux que ressembler fort à une
        # seule : c'est le signal que le profil, et non un hasard de nom, est retrouvé.
        n_seeds = len({x["source_seed"] for x in m})
        e["best_similarity"] = round(meilleur, 1)
        e["seed_count"] = n_seeds
        e["twin_types"] = sorted({x["twin_type"] for x in m})
        e["lookalike_score"] = round(meilleur + BONUS_MULTI * min(n_seeds - 1, BONUS_MAX), 1)
        e["source_seeds"] = sorted({x["source_seed"] for x in m})
    classe = sorted(par_dom.values(),
                    key=lambda e: (-e["lookalike_score"], -e["seed_count"], e["candidate_domain"]))
    return {"generated_at": now(), "seeds": g, "seeds_rejected": rejets,
            "univers": len(univers), "jumeaux_bruts": brut,
            "candidats": classe,
            "note": ("Un score de similarité ordonne une file d'attente. Il ne voit aucun "
                     "catalogue, ne prouve ni basket ni scellé, et une candidate n'est PAS "
                     "une recommandation : il faut basket SCELLÉ visible + PRIX + ACHAT À "
                     "DISTANCE. Les malus (TCG, breaker, chaîne) sont des critères de tri, "
                     "pas des jugements — UNKNOWN n'est jamais NO.")}


# ------------------------------------------------------------------ porte dure
import external_engine as xe
import shop_discovery as sd
import shop_qualify2 as sq2

_FETCHS = [0]
_vrai_fetch = xe.fetch


def compte_fetch(url, timeout=12):
    _FETCHS[0] += 1
    return _vrai_fetch(url, timeout=timeout)


def instrumente():
    """Compter les requêtes réellement émises : sans ça, « moins cher » n'est qu'une opinion."""
    xe.fetch = compte_fetch
    sd.xe.fetch = compte_fetch
    sq2.xe.fetch = compte_fetch
    _FETCHS[0] = 0


PRIX_RX = [re.compile(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?'),
           re.compile(r'itemprop="price"[^>]*content="([0-9]+(?:\.[0-9]{1,2})?)"'),
           re.compile(r'property="(?:og:)?price:amount"[^>]*content="([0-9]+(?:\.[0-9]{1,2})?)"'),
           re.compile(r'data-product-price="?\$?([0-9]+(?:\.[0-9]{1,2})?)')]
PRIX_TXT = re.compile(r"\$\s?([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")


def prix_sur_page(url: str) -> tuple[float | None, str | None]:
    """Le prix tel que la page l'affiche. Pas d'estimation, pas de reconstruction."""
    if not url or not url.startswith("http") or not xe.robots_ok(url):
        return None, "page non lisible ou interdite"
    st, b, why = xe.fetch(url, timeout=14)
    if st != 200 or not b:
        return None, f"page produit illisible ({why or st})"
    for rx in PRIX_RX:
        m = rx.search(b)
        if m:
            try:
                v = float(m.group(1))
                if 1 <= v <= 20000:
                    return v, None
            except ValueError:
                pass
    m = PRIX_TXT.search(b)
    if m:
        try:
            return float(m.group(1).replace(",", "")), None
        except ValueError:
            pass
    return None, "aucun prix affiché sur la page produit"


ACHAT_DISTANCE = {"ONLINE_CART", "MAIL_ORDER", "PHONE_ORDER"}


def valide(dom: str) -> dict:
    """La PORTE DURE. Trois preuves, ou la boutique reste une candidate.

    Basket SCELLÉ visible + PRIX affiché + ACHAT À DISTANCE. « Boutique de cartes de sport »,
    « basket confirmé », « revendeur Panini », « magasin physique » ne suffisent pas : la
    découverte précédente a produit des recommandations inutilisables faute de cette règle.
    """
    r = {"domain": dom, "checked_at": now(), "verdict": None, "raison": None,
         "sealed_product": None, "product_url": None, "price": None, "currency": "USD",
         "purchase_mode": None, "crawlability": None, "legitimacy": None,
         "in_stock": None, "preuves": []}
    try:
        p1 = sd.qualifie(dom)
    except Exception as e:
        p1 = {"status": "ERROR", "reason": e.__class__.__name__}
    try:
        p2 = sq2.qualifie2(dom)
    except Exception as e:
        p2 = {"status": "ERROR", "reason": e.__class__.__name__}
    v = sq2.fusionne(p1, p2)
    r.update(purchase_mode=v.get("purchase_mode"), crawlability=v.get("crawlability"),
             legitimacy=v.get("legitimacy"), titres_examines=v.get("titres_examines"),
             api_lue=v.get("api_lue"), statut_funnel=v["status"])
    r["preuves"] = (p2.get("signaux") or [])

    if v["status"] == sq2.UNVERIFIED_NOT_CRAWLABLE:
        r.update(verdict="BLOCKED", raison="robots.txt nous interdit — respecté, non contourné")
        return r
    if v["status"] == sq2.UNKNOWN_NOT_READ:
        r.update(verdict="UNREADABLE", raison=v["reason"])
        return r
    if not v.get("sealed_basketball"):
        r.update(verdict="CANDIDATE_ONLY",
                 raison=("scellé basket NON PROUVÉ — " + (v.get("reason") or "")))
        if v["status"] in ("REJECTED_NO_BASKETBALL", "REJECTED_NO_SEALED"):
            r["verdict"] = "REJECTED"      # établi sur catalogue énuméré, pas sur ignorance
        if v["status"] == sq2.UNKNOWN_NO_CATALOGUE:
            r["verdict"] = "CANDIDATE_ONLY"
        return r

    ev = v.get("evidence") or {}
    r["sealed_product"] = ev.get("product_name")
    r["product_url"] = ev.get("product_url")
    r["in_stock"] = ev.get("availability")
    prix = ev.get("price")
    if prix in (None, 0, "0", "0.00"):
        prix, pourquoi = prix_sur_page(r["product_url"])
        if prix is None:
            r.update(verdict="CANDIDATE_ONLY",
                     raison=f"scellé prouvé, mais PRIX non constaté — {pourquoi}")
            return r
    r["price"] = float(prix)

    if r["purchase_mode"] not in ACHAT_DISTANCE:
        r.update(verdict="CANDIDATE_ONLY",
                 raison=f"scellé et prix constatés, mais aucun achat à distance identifié "
                        f"({r['purchase_mode']})")
        return r

    r.update(verdict="QUALIFIED",
             raison=f"scellé basket + prix affiché + achat {r['purchase_mode']}")
    return r


# ------------------------------------------------------------------ old stock
def old_stock(dom: str, url_produit: str | None) -> tuple[int, list[str]]:
    """Mesuré sur une page déjà lue du marchand. Ne prouve AUCUNE disponibilité."""
    import hunt_priority as hp
    v = hp.vitrine(dom)
    if not v.get("inspected"):
        return 0, ["vitrine non relue — score d'ancienneté non mesuré, ce n'est pas un zéro de fait"]
    return hp.score_old_stock(v)


# ------------------------------------------------------------------ 5 cibles
def cibles(dom: str, journal=print) -> list[dict]:
    """Le matcher canonique, INCHANGÉ. UPC > SKU fabricant > année+set+format+variante > alias."""
    import mega_hunt as mh
    base, out, vus = f"https://{dom}", [], set()
    vide = 0
    for q in mh.REQUETES:
        try:
            res = mh.cherche(base, q)
        except Exception:
            res = []
        if not res:
            vide += 1
            if vide >= 3:
                break
            continue
        for x in res:
            # Shopify renvoie la même fiche avec des paramètres de suivi différents selon la
            # requête : sans normalisation, un seul produit ressort huit fois.
            cle = urllib.parse.urlsplit(x["url"])._replace(query="", fragment="").geturl()
            if cle in vus:
                continue
            ident = mh.identifie(x["titre"], sku_vendeur=x.get("sku", ""))
            if ident["confiance"] == "HORS_PERIMETRE":
                continue
            vus.add(cle)
            t = ident["target"]
            if not t:
                # AMBIGU : un Mega 2023-24 dont la variante n'est pas l'une de nos cinq. Le
                # jeter reviendrait à perdre exactement ce qu'on cherche — une Mega Prizm
                # 2023-24 en rayon — parce qu'elle ne porte pas le bon suffixe. Il ne devient
                # jamais une offre canonique, mais il doit REMONTER.
                out.append({"product": None, "upc": None, "target_id": None, "domain": dom,
                            "price": x.get("prix"),
                            "stock": "IN_STOCK" if x.get("dispo") else "OUT_OF_STOCK",
                            "url": cle, "title": x["titre"],
                            "match_level": ident["preuve"], "confidence": ident["confiance"],
                            "config": None})
                journal(f"    AMBIGU — {x['titre'][:60]}")
                continue
            out.append({"product": t["libelle"], "upc": t["upc"], "target_id": t["id"],
                        "domain": dom, "price": x.get("prix"),
                        "stock": "IN_STOCK" if x.get("dispo") else "OUT_OF_STOCK",
                        "url": cle, "title": x["titre"],
                        "match_level": ident["preuve"], "confidence": ident["confiance"],
                        "config": mh.valide_config(t, f"{x['titre']} {x.get('sku','')}")})
            journal(f"    CIBLE {ident['confiance']} — {x['titre'][:56]}")
    return out
