#!/usr/bin/env python3
"""HUNT PRIORITY SCORE — où chercher d'abord du sealed NBA 2023-24 oublié.

CE QUE CE SCORE MESURE, ET CE QU'IL NE MESURE PAS
-------------------------------------------------
Il ne note pas la qualité d'un magasin. Il n'ordonne pas des marchands du meilleur au pire.
Il répond à une seule question : dans quel ordre ouvrir les catalogues pour tomber sur du
sealed ancien. Un site laid, sans API, en HTML de 2009, avec un inventaire mail-order profond
est une MEILLEURE cible qu'un Shopify neuf qui ne stocke que du produit de l'année. Aucun
signal ne retire de points pour vétusté : c'est délibéré, et la liste NE_PENALISE_PAS en fait
foi.

LES DEUX ÉTAGES
---------------
A — ce que l'annuaire publie déjà : nom, rubriques, ville, site, téléphone, adresse.
    Gratuit, aucun serveur marchand n'est sollicité.
B — une inspection TRÈS LÉGÈRE : la page d'accueil, une seule requête, sous robots.txt.
    Pas de catalogue, pas d'API, pas de pagination. Le crawl profond attend le TOP 100.

L'ABSENCE DE SIGNAL N'EST PAS UN SIGNAL CONTRAIRE
-------------------------------------------------
Une page d'accueil muette sur le basket ne dit pas que le marchand n'en vend pas : elle dit
que sa vitrine n'en parle pas. Le champ `inspected` distingue « lu et rien vu » de « pas lu ».
Un score bas est une place dans une file d'attente, jamais un verdict.
"""
from __future__ import annotations
import json, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import external_engine as xe
import shop_discovery as sd

ROOT = Path(__file__).parent
SORTIE = ROOT / "discovered" / "national_priority.json"

NE_PENALISE_PAS = ("design ancien", "absence d'API", "absence de Shopify", "catalogue HTML",
                   "mail-order", "site peu sophistiqué")

# ------------------------------------------------------------------ étage A
NOM_SPORTS_CARDS = re.compile(r"sports?\s*cards?", re.I)
NOM_CARDS = re.compile(r"\bcards?\b|\bcardz\b|\bwax\b", re.I)
SIGNAL_SPORT = re.compile(r"sports?|\bnba\b|basketball|baseball|football|hockey|\bmlb\b|"
                          r"\bnfl\b|\bnhl\b|dugout|bullpen|hoops|slam|rookie|\bmvp\b", re.I)
CAT_SPORTS = re.compile(r"sports?\s*cards?|trading\s*cards?", re.I)
CAT_BOUTIQUE_EN_LIGNE = re.compile(r"online\s*store|e-?commerce|webshop", re.I)

# Les villes américaines au-dessus de ~250 000 habitants. Hors de cette liste, on est dans la
# petite ou moyenne ville — là où le stock dort au lieu d'être arbitré en 48 h.
GRANDES_VILLES = {
    "new york", "los angeles", "chicago", "houston", "phoenix", "philadelphia", "san antonio",
    "san diego", "dallas", "jacksonville", "austin", "fort worth", "san jose", "columbus",
    "charlotte", "indianapolis", "san francisco", "seattle", "denver", "oklahoma city",
    "nashville", "washington", "el paso", "las vegas", "boston", "detroit", "portland",
    "louisville", "memphis", "baltimore", "milwaukee", "albuquerque", "fresno", "tucson",
    "sacramento", "mesa", "kansas city", "atlanta", "omaha", "colorado springs", "raleigh",
    "virginia beach", "long beach", "miami", "oakland", "minneapolis", "bakersfield", "tulsa",
    "wichita", "arlington", "aurora", "tampa", "new orleans", "cleveland", "honolulu",
    "anaheim", "lexington", "stockton", "corpus christi", "henderson", "riverside",
    "newark", "saint paul", "st. paul", "santa ana", "cincinnati", "irvine", "orlando",
    "pittsburgh", "st. louis", "saint louis", "greensboro", "jersey city", "anchorage",
    "lincoln", "plano", "durham", "buffalo", "chandler", "chula vista", "toledo",
    "madison", "gilbert", "reno", "fort wayne", "north las vegas", "st. petersburg",
    "saint petersburg", "lubbock", "irving", "laredo", "winston-salem", "chesapeake",
    "glendale", "garland", "scottsdale", "norfolk", "boise", "fremont", "spokane",
    "richmond", "baton rouge", "hialeah", "tacoma", "san bernardino", "modesto",
}

# ------------------------------------------------------------------ étage B
# Panini décline ses gammes sur tous les sports : le sport doit être NOMMÉ. C'est la même
# règle qu'au funnel — « Prizm » seul a déjà fait passer un blaster de football pour du basket.
B_BASKET = re.compile(r"basketball|\bnba\b|\bhoops\b|court\s*kings", re.I)
B_SEALED = re.compile(r"sealed\s*(?:wax|box|case|product)|\bwax\s*box\b|hobby\s*box|blaster|"
                      r"mega\s*box|booster\s*box|retail\s*box|hobby\s*case|\bsealed\s*boxes\b",
                      re.I)
B_PANINI = re.compile(r"\bpanini\b", re.I)
B_PRIZM = re.compile(r"\bprizm\b", re.I)
B_SELECT = re.compile(r"panini\s*select|\bselect\b(?=[^a-z]{0,12}(?:basketball|nba|mega|hobby))",
                      re.I)
B_INVENTAIRE = re.compile(r"box\s*inventory|wax\s*inventory|sealed\s*inventory|"
                          r"box\s*list|wax\s*list", re.I)
B_MAIL = re.compile(r"mail\s*order|we\s*ship|call\s*to\s*order|phone\s*orders?|"
                    r"ships?\s*nationwide|shipping\s*available|order\s*by\s*phone", re.I)
# Un catalogue qui expose encore des millésimes anciens : exactement ce que l'on cherche.
B_ANCIEN = re.compile(r"\b(?:19[7-9]\d|200\d|201\d|2020|2021|2022)\b[^.]{0,30}"
                      r"(?:box|wax|pack|case|set)|vintage\s*(?:wax|box|sealed)|"
                      r"back\s*stock|old\s*stock|clearance", re.I)
B_2324 = re.compile(r"2023[-/\s]?24|2023-2024", re.I)
PLATEFORME = re.compile(r"cdn\.shopify|shopify|woocommerce|wp-content|bigcommerce", re.I)

POIDS_A = [
    ("nom contient « sports cards »", 8),
    ("rubrique sports cards", 6),
    ("nom « cards » + signal sport", 5),
    ("petite/moyenne ville", 4),
    ("site marchand propre", 4),
    ("téléphone physique", 3),
    ("adresse physique", 3),
    ("ancienneté vérifiable", 2),
]
POIDS_B = [
    ("basketball visible", 10), ("sealed wax / boxes visible", 10), ("Panini visible", 8),
    ("Prizm visible", 7), ("Select visible", 7), ("box/wax inventory", 6),
    ("mail order / we ship / call to order", 6), ("catalogue ancien", 5),
    ("2023-24 visible", 5), ("plateforme e-commerce connue", 3),
]

# ------------------------------------------------------------------ old stock
POIDS_OLD = [
    ("NBA 2023-24 encore présent", 10), ("NBA 2022-23", 8), ("NBA 2021-22", 6),
    ("plusieurs générations de wax", 5), ("produits OOS anciens encore indexés", 5),
    ("inventaire HTML historique", 5), ("prix manifestement anciens", 4),
    ("faible rotation apparente", 3),
]
MILLESIME = re.compile(r"\b(19[7-9]\d|20[0-2]\d)\s*[-/]\s*(\d{2})\b|\b(19[7-9]\d|20[0-2]\d)\b")
OOS = re.compile(r"out\s*of\s*stock|sold\s*out|unavailable|backorder", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def score_a(c: dict) -> tuple[int, list[str]]:
    """L'étage gratuit : rien n'est demandé au marchand."""
    nom = c.get("shop_name") or ""
    cats = " ".join(c.get("categories") or [])
    pts, motifs = 0, []

    def add(cond, libelle, poids):
        nonlocal pts
        if cond:
            pts += poids
            motifs.append(f"+{poids} {libelle}")

    add(NOM_SPORTS_CARDS.search(nom), "nom contient « sports cards »", 8)
    add(CAT_SPORTS.search(cats), "rubrique sports cards", 6)
    add(NOM_CARDS.search(nom) and SIGNAL_SPORT.search(nom + " " + cats)
        and not NOM_SPORTS_CARDS.search(nom), "nom « cards » + signal sport", 5)
    ville = (c.get("cities") or [None])[0] or ""
    add(ville and ville.strip().lower() not in GRANDES_VILLES, "petite/moyenne ville", 4)
    add(c.get("domain") and not sd.MARKETPLACES.search(c["domain"]), "site marchand propre", 4)
    add(c.get("phone"), "téléphone physique", 3)
    add(c.get("street_address"), "adresse physique", 3)
    add(c.get("since"), "ancienneté vérifiable", 2)
    return pts, motifs


def vitrine(dom: str) -> dict:
    """UNE page : l'accueil. Sous robots.txt, et rien de plus. Le catalogue attend son tour."""
    r = {"domain": dom, "inspected": False, "robots": None, "http": None,
         "platform": None, "text_len": 0, "html": ""}
    base = f"https://{dom}"
    if not xe.robots_ok(base + "/"):
        r["robots"] = "disallowed"
        return r
    r["robots"] = "allowed"
    st, b, why = xe.fetch(base, timeout=14)
    r["http"] = st if st else (why or "no_response")
    if st != 200 or not b:
        return r
    r.update(inspected=True, text_len=len(b), html=b)
    low = b.lower()
    r["platform"] = ("shopify" if "cdn.shopify" in low else
                     "woocommerce" if ("woocommerce" in low or "wp-content" in low) else
                     "bigcommerce" if "bigcommerce" in low else
                     "squarespace" if "squarespace" in low else
                     "wix" if ("wixstatic" in low or "parastorage" in low) else "custom")
    return r


def score_b(v: dict) -> tuple[int, list[str], dict]:
    """L'étage d'inspection. Sans lecture, il vaut 0 — et 0 ne veut dire NON pour rien."""
    if not v.get("inspected"):
        return 0, [], {}
    h = v["html"]
    vu = {
        "basketball visible": bool(B_BASKET.search(h)),
        "sealed wax / boxes visible": bool(B_SEALED.search(h)),
        "Panini visible": bool(B_PANINI.search(h)),
        "Prizm visible": bool(B_PRIZM.search(h)),
        "Select visible": bool(B_SELECT.search(h)),
        "box/wax inventory": bool(B_INVENTAIRE.search(h)),
        "mail order / we ship / call to order": bool(B_MAIL.search(h)),
        "catalogue ancien": bool(B_ANCIEN.search(h)),
        "2023-24 visible": bool(B_2324.search(h)),
        "plateforme e-commerce connue": bool(PLATEFORME.search(h)),
    }
    pts, motifs = 0, []
    for lib, poids in POIDS_B:
        if vu[lib]:
            pts += poids
            motifs.append(f"+{poids} {lib}")
    return pts, motifs, vu


def score_old_stock(v: dict) -> tuple[int, list[str]]:
    """Ce score ne prouve aucune disponibilité. Il dit où une chasse manuelle peut payer."""
    if not v.get("inspected"):
        return 0, []
    h = v["html"]
    annees = set()
    for a, b2, c3 in MILLESIME.findall(h):
        annees.add(int(a or c3))
    pts, motifs = 0, []

    def add(cond, libelle, poids):
        nonlocal pts
        if cond:
            pts += poids
            motifs.append(f"+{poids} {libelle}")

    add(B_2324.search(h) and B_BASKET.search(h), "NBA 2023-24 encore présent", 10)
    add(re.search(r"2022[-/\s]?23", h) and B_BASKET.search(h), "NBA 2022-23", 8)
    add(re.search(r"2021[-/\s]?22", h) and B_BASKET.search(h), "NBA 2021-22", 6)
    add(len([a for a in annees if a <= 2023]) >= 3 and B_SEALED.search(h),
        "plusieurs générations de wax", 5)
    add(OOS.search(h) and any(a <= 2023 for a in annees),
        "produits OOS anciens encore indexés", 5)
    add(v.get("platform") == "custom" and B_INVENTAIRE.search(h),
        "inventaire HTML historique", 5)
    add(bool(re.search(r"\$\s?\d{1,3}\.\d{2}", h)) and any(a <= 2022 for a in annees),
        "prix manifestement anciens", 4)
    add(len(annees) >= 4 and min(annees, default=2026) <= 2020, "faible rotation apparente", 3)
    return pts, motifs


# ------------------------------------------------------------------ legitimacy
def legitimacy(c: dict, v: dict) -> tuple[str, list[str]]:
    """Une empreinte cohérente, pas un jugement moral.

    Faible visibilité n'est PAS une arnaque : c'est une absence de preuve, et elle donne
    UNVERIFIED, jamais SUSPICIOUS. SUSPICIOUS demande une incohérence CONSTATÉE.
    """
    p = []
    if c.get("street_address"):
        p.append("adresse de rue publiée")
    if c.get("phone"):
        p.append("téléphone publié")
    if c.get("since"):
        p.append(f"présence depuis {c['since']}")
    if (c.get("listings") or 1) > 1:
        p.append(f"{c['listings']} points de vente référencés")
    if v.get("inspected"):
        p.append("site en ligne et lisible")
    if v.get("platform") in ("shopify", "woocommerce", "bigcommerce"):
        p.append(f"plateforme e-commerce établie ({v['platform']})")

    physique = bool(c.get("street_address") and c.get("phone"))
    if physique and v.get("inspected") and len(p) >= 4:
        return "TRUSTED", p
    if physique or (v.get("inspected") and (c.get("phone") or c.get("street_address"))):
        return "LIKELY_LEGIT", p
    return "UNVERIFIED", p or ["aucune preuve indépendante réunie — absence de preuve, "
                               "pas preuve d'absence"]


# ------------------------------------------------------------------ pilotage
_verrou, _compte = threading.Lock(), [0]


def evalue(c: dict, total: int, journal) -> dict:
    a, motifs_a = score_a(c)
    v = vitrine(c["domain"])
    b, motifs_b, vu = score_b(v)
    old, motifs_old = score_old_stock(v)
    leg, preuves = legitimacy(c, v)
    with _verrou:
        _compte[0] += 1
        if _compte[0] % 250 == 0:
            journal(f"  {_compte[0]}/{total} domaines inspectés")
    return {**{k: c.get(k) for k in ("domain", "shop_name", "website", "state", "cities",
                                     "phone", "street_address", "categories", "listings",
                                     "since", "cardshopmap_url")},
            "city": (c.get("cities") or [None])[0],
            "score_a": a, "score_b": b, "hunt_priority_score": a + b,
            "old_stock_score": old,
            "reason": "; ".join(motifs_a + motifs_b) or "aucun signal positif relevé",
            "old_stock_reason": "; ".join(motifs_old) or "aucun signal d'ancienneté relevé",
            "legitimacy": leg, "legitimacy_evidence": preuves,
            "inspected": v.get("inspected", False), "robots": v.get("robots"),
            "http": v.get("http"), "platform": v.get("platform"),
            "signals": vu,
            "inspection_note": (None if v.get("inspected") else
                                "vitrine non lue : le score B vaut 0 par défaut d'observation, "
                                "ce qui n'est pas une absence de basket ni de scellé")}


def classe(candidats: list[dict], workers: int = 12, journal=print) -> list[dict]:
    cands = [c for c in candidats if c.get("domain")]
    _compte[0] = 0
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(lambda c: evalue(c, len(cands), journal), cands))
    journal(f"  {len(out)} domaines en {(time.monotonic()-t0)/60:.1f} min")
    return sorted(out, key=lambda r: (-r["hunt_priority_score"], -r["old_stock_score"],
                                      r["domain"]))


def main():
    import national_index as ni
    d = ni.charge()
    cands = d.get("candidates") or []
    print(f"PHASE 2 — HUNT PRIORITY SCORE sur {len(cands)} domaines\n" + "=" * 46)
    print("inspection TRÈS LÉGÈRE : une page d'accueil par domaine, sous robots.txt.")
    print("aucun catalogue, aucune API, aucune pagination — le crawl profond attend le TOP 100.\n")
    rangs = classe(cands)
    lus = sum(1 for r in rangs if r["inspected"])
    bloques = sum(1 for r in rangs if r["robots"] == "disallowed")
    SORTIE.parent.mkdir(exist_ok=True)
    SORTIE.write_text(json.dumps({
        "generated_at": now(), "domaines": len(rangs), "inspectes": lus,
        "robots_disallow": bloques, "non_lus": len(rangs) - lus,
        "ne_penalise_pas": list(NE_PENALISE_PAS),
        "note": ("Un score bas est une place dans une file d'attente, pas un verdict. "
                 "Les domaines non inspectés ont un étage B nul par défaut d'observation : "
                 "ce n'est ni une absence de basketball ni une absence de scellé. "
                 "robots_disallow signifie que le marchand interdit le crawl — il reste "
                 "candidat, non jugé."),
        "ranked": rangs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndomaines classés     {len(rangs)}")
    print(f"vitrines lues        {lus}")
    print(f"robots interdit      {bloques}  (candidats non jugés)")
    print(f"injoignables         {len(rangs) - lus - bloques}")
    print(f"\nTOP 10 :")
    for r in rangs[:10]:
        print(f"  {r['hunt_priority_score']:3}  old {r['old_stock_score']:2}  "
              f"{r['domain'][:34]:<34} {(r['shop_name'] or '')[:28]}")


if __name__ == "__main__":
    main()
