#!/usr/bin/env python3
"""Chercher chez un marchand la preuve qu'il vend du SCELLÉ NBA, avec son prix.

POURQUOI UNE SONDE DÉDIÉE
-------------------------
Le funnel rendait « la première fiche de basket scellé trouvée ». Chez Ryno's, c'était une
boîte EuroLeague épuisée, et la boutique passait pour une source NBA. Ce n'est pas au hasard
de la première fiche de décider : on INTERROGE le catalogue sur ce qu'on cherche.

CE QUE LA SONDE RAPPORTE
------------------------
Chaque fiche retenue porte son titre exact, son URL directe, son prix affiché, sa
disponibilité et sa saison. Sans prix affiché, une fiche ne qualifie rien : on ne recommande
pas un magasin sur la foi d'un produit dont on ignore le tarif.
"""
from __future__ import annotations
import json, re, urllib.parse

import external_engine as xe
import nba_gate as ng

REQUETES = ["nba hobby box", "panini basketball box", "prizm basketball", "basketball blaster",
            "basketball mega box", "topps chrome basketball", "nba hoops", "basketball hobby"]


def _shopify(base: str, q: str, limit: int = 25) -> list[dict]:
    st, b, _ = xe.fetch(f"{base}/search/suggest.json?q={urllib.parse.quote(q)}"
                        f"&resources[type]=product&resources[limit]={limit}", timeout=12)
    out = []
    if st == 200 and (b or "").strip().startswith("{"):
        try:
            for p in json.loads(b)["resources"]["results"]["products"]:
                pr = p.get("price")
                out.append({"titre": p.get("title", ""),
                            "url": base + (p.get("url") or "").split("?")[0],
                            "prix": float(pr) if pr not in (None, "") else None,
                            "dispo": bool(p.get("available")), "plat": "shopify"})
        except Exception:
            pass
    return out


def _woo(base: str, q: str, limit: int = 25) -> list[dict]:
    st, b, _ = xe.fetch(f"{base}/wp-json/wc/store/v1/products?search={urllib.parse.quote(q)}"
                        f"&per_page={limit}", timeout=12)
    out = []
    if st == 200 and (b or "").strip().startswith("["):
        try:
            for p in json.loads(b):
                pr = p.get("prices") or {}
                mn = int(pr.get("currency_minor_unit", 2) or 2)
                v = pr.get("price")
                out.append({"titre": p.get("name", ""), "url": (p.get("permalink") or "").split("?")[0],
                            "prix": (float(v) / (10 ** mn)) if v not in (None, "") else None,
                            "dispo": bool(p.get("is_in_stock")), "plat": "woocommerce"})
        except Exception:
            pass
    return out


def _surfaces_publiques(dom: str) -> list[dict]:
    """Sans API, le catalogue se lit quand même : sitemap produits, JSON-LD, intitulés HTML.

    La première version n'interrogeait que Shopify et WooCommerce. Trente-trois boutiques
    pourtant VIVANTES sont ressorties « illisibles » parce qu'elles n'avaient pas d'API — une
    limite de notre sonde présentée comme une propriété du marchand. Cette reprise réutilise
    les surfaces publiques déjà exploitées par le second passage du funnel.
    """
    import shop_qualify2 as sq2
    try:
        pages = sq2.pages_publiques(f"https://{dom}")
    except Exception:
        return []
    vus, out = set(), []
    for u, b in pages:
        titres = (re.findall(r"<image:title>(?:<!\[CDATA\[)?([^<\]]{12,140})", b)
                  + re.findall(r'"name"\s*:\s*"([^"]{12,140})"', b)
                  + re.findall(r"<(?:h[1-4]|a|title|span|li|td)[^>]*>([^<]{12,140})</", b))
        liens = dict(re.findall(r'<loc>([^<]*/products?/([^<]+))</loc>', b) or [])
        for t in titres:
            t = re.sub(r"\s+", " ", t).strip()
            if t in vus:
                continue
            vus.add(t)
            out.append({"titre": t, "url": u, "prix": None, "dispo": None, "plat": "html"})
        for loc in re.findall(r"<loc>([^<]*/products?/[^<]+)</loc>", b):
            slug = loc.rstrip("/").split("/")[-1].replace("-", " ")
            if slug in vus:
                continue
            vus.add(slug)
            out.append({"titre": slug, "url": loc.split("?")[0], "prix": None,
                        "dispo": None, "plat": "html"})
    return out


def sonde_nba(dom: str, journal=None) -> dict:
    """Ce que le marchand publie de scellé NBA, avec prix. Aucune inférence."""
    base = f"https://{dom}"
    r = {"domain": dom, "api": None, "fiches_vues": 0, "nba_scelle": [],
         "autre_ligue": [], "generique": [], "requetes": 0}
    if not xe.robots_ok(base + "/"):
        r["api"] = "robots_disallow"
        return r
    vus, vide = set(), 0
    for q in REQUETES:
        res = _shopify(base, q) or _woo(base, q)
        r["requetes"] += 1
        if not res:
            vide += 1
            if vide >= 3:
                break
            continue
        r["api"] = r["api"] or res[0]["plat"]
        for x in res:
            if x["url"] in vus or not x["titre"]:
                continue
            vus.add(x["url"])
            r["fiches_vues"] += 1
            t = x["titre"]
            if not ng.SCELLE.search(t) or ng.PAS_DES_CARTES.search(t):
                continue
            if not ng.BASKET.search(t):
                continue
            fiche = {"titre": t, "url": x["url"], "prix": x["prix"], "dispo": x["dispo"],
                     "saison": ng.saison(t), "annee": ng.annee_debut(t)}
            cl = ng.classe_ligue(t)
            r["nba_scelle" if cl == ng.NBA else
              "autre_ligue" if cl == ng.AUTRE_LIGUE else "generique"].append(fiche)
    # Pas d'API : on retombe sur les surfaces publiques avant de conclure quoi que ce soit.
    if r["fiches_vues"] == 0:
        pub = _surfaces_publiques(dom)
        r["api"] = r["api"] or ("html" if pub else None)
        for x in pub:
            r["fiches_vues"] += 1
            t = x["titre"]
            if not ng.SCELLE.search(t) or ng.PAS_DES_CARTES.search(t) or not ng.BASKET.search(t):
                continue
            fiche = {"titre": t, "url": x["url"], "prix": None, "dispo": None,
                     "saison": ng.saison(t), "annee": ng.annee_debut(t)}
            cl = ng.classe_ligue(t)
            r["nba_scelle" if cl == ng.NBA else
              "autre_ligue" if cl == ng.AUTRE_LIGUE else "generique"].append(fiche)
        # Le prix ne figure pas dans un sitemap : on va le chercher sur UNE fiche.
        for f in r["nba_scelle"][:3]:
            if f["url"] and "/product" in f["url"]:
                st, b, _ = xe.fetch(f["url"], timeout=14)
                if st == 200 and b:
                    m = (re.search(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?', b)
                         or re.search(r"\$\s?([0-9]{1,4}(?:\.[0-9]{2})?)", b))
                    if m:
                        try:
                            f["prix"] = float(m.group(1))
                        except ValueError:
                            pass
                    f["dispo"] = bool(re.search(r"InStock|add to cart", b, re.I))
                break

    # Le meilleur témoin : NBA, scellé, PRIX affiché, et en stock si possible.
    avec_prix = [f for f in r["nba_scelle"] if f["prix"]]
    r["temoin"] = (next((f for f in avec_prix if f["dispo"]), None)
                   or (avec_prix[0] if avec_prix else None))
    r["nba_sans_prix"] = len(r["nba_scelle"]) - len(avec_prix)
    return r


# ------------------------------------------------------------------ old stock v2
"""Ce que la v1 mesurait mal.

La v1 lisait la PAGE D'ACCUEIL et cherchait des millésimes dans le texte. Elle ne savait pas
distinguer une fiche 2019-20 encore au panier d'une fiche archivée depuis quatre ans, ni un
millésime cité dans un billet de blog d'un produit en rayon. Or c'est exactement là qu'est le
signal : une Mega 2019-20 ENCORE ACHETABLE vaut incomparablement plus qu'une page épuisée.

La v2 se calcule sur les fiches réellement relevées chez le marchand, chacune avec sa saison
et sa disponibilité. Elle ne récompense donc plus « une vieille page existe » mais « du vieux
scellé NBA est achetable ».
"""
SAISON_COURANTE = 2025          # 2025-26 est la saison en cours

POIDS_V2 = {
    "achetable_2023_24": 12,    # la saison recrue de Wembanyama, encore au panier
    "achetable_2022_23": 8,
    "achetable_2021_22": 7,
    "achetable_2020_21": 6,
    "achetable_2019_ou_avant": 6,
    "generations_simultanees": 10,
    "vieux_format_retail": 4,   # Mega / Blaster / Hanger anciens : le circuit grande surface
    "epuise_ancien_indexe": 2,  # trace d'un stock ancien, sans preuve qu'il soit achetable
    "catalogue_profond": 3,
}
PLAFOND = {"achetable_2023_24": 24, "achetable_2022_23": 16, "achetable_2021_22": 14,
           "achetable_2020_21": 12, "achetable_2019_ou_avant": 18,
           "vieux_format_retail": 12, "epuise_ancien_indexe": 8}
RETAIL_ANCIEN = re.compile(r"mega\s*box|blaster|hanger|fat\s*pack|value\s*box|cello", re.I)


def old_stock_v2(fiches: list[dict]) -> tuple[int, list[str], dict]:
    """Le score, et surtout le DÉTAIL de ce qui l'a produit.

    `fiches` = le scellé NBA relevé chez le marchand, avec saison et disponibilité.
    Un score de 0 sur une liste vide ne dit rien du marchand : il dit que nous n'avons rien lu.
    """
    pts, motifs = 0, []
    achetables = [f for f in fiches if f.get("dispo") and f.get("annee")]
    anciens_achetables = [f for f in achetables if f["annee"] <= 2023]
    epuises_anciens = [f for f in fiches
                       if not f.get("dispo") and f.get("annee") and f["annee"] <= 2023]

    def bucket(f):
        a = f["annee"]
        return ("achetable_2023_24" if a == 2023 else "achetable_2022_23" if a == 2022 else
                "achetable_2021_22" if a == 2021 else "achetable_2020_21" if a == 2020 else
                "achetable_2019_ou_avant")

    par_seau: dict[str, list] = {}
    for f in anciens_achetables:
        par_seau.setdefault(bucket(f), []).append(f)
    for seau, lst in sorted(par_seau.items()):
        gagne = min(POIDS_V2[seau] * len(lst), PLAFOND[seau])
        pts += gagne
        motifs.append(f"+{gagne} {len(lst)} fiche(s) {seau.replace('achetable_', '').replace('_', '-')} "
                      f"ENCORE AU PANIER")

    gens = {f["saison"] for f in anciens_achetables if f.get("saison")}
    if len(gens) >= 3:
        pts += POIDS_V2["generations_simultanees"]
        motifs.append(f"+{POIDS_V2['generations_simultanees']} {len(gens)} générations de wax "
                      f"NBA achetables en même temps ({', '.join(sorted(gens)[:5])})")

    vieux_retail = [f for f in anciens_achetables if RETAIL_ANCIEN.search(f["titre"])]
    if vieux_retail:
        g = min(POIDS_V2["vieux_format_retail"] * len(vieux_retail), PLAFOND["vieux_format_retail"])
        pts += g
        motifs.append(f"+{g} {len(vieux_retail)} format(s) retail ancien(s) achetable(s) "
                      f"(Mega/Blaster/Hanger)")

    if epuises_anciens:
        g = min(POIDS_V2["epuise_ancien_indexe"] * len(epuises_anciens),
                PLAFOND["epuise_ancien_indexe"])
        pts += g
        motifs.append(f"+{g} {len(epuises_anciens)} fiche(s) ancienne(s) encore indexée(s) "
                      f"mais ÉPUISÉE(S) — trace, pas stock")

    if len(fiches) >= 25:
        pts += POIDS_V2["catalogue_profond"]
        motifs.append(f"+{POIDS_V2['catalogue_profond']} catalogue NBA scellé profond "
                      f"({len(fiches)} fiches relevées)")

    detail = {"nba_scelle_total": len(fiches), "achetables": len(achetables),
              "anciens_achetables": len(anciens_achetables),
              "epuises_anciens": len(epuises_anciens),
              "generations_achetables": sorted(gens),
              "plus_ancien_achetable": min((f["saison"] for f in anciens_achetables
                                            if f.get("saison")), default=None)}
    if not fiches:
        motifs = ["aucune fiche NBA scellée relevée — score non mesuré, "
                  "ce qui n'est pas un zéro de fait"]
    return pts, motifs, detail
