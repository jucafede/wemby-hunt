#!/usr/bin/env python3
"""ACCOUNTING — d'où partent les fiches, et où chacune s'arrête.

Une réduction non expliquée est une perte silencieuse : 193 fiches annoncées, 91 domaines
examinés, et rien entre les deux pour dire ce qu'étaient les 102 autres. Ce module rend
l'égalité vérifiable, État par État :

    FICHES BOUTIQUE = SANS SITE + DOUBLONS + LIENS NON MARCHANDS + DOMAINES UNIQUES
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

import external_engine as xe
import shop_discovery as sd

ROOT = Path(__file__).parent
ETATS = ["idaho", "iowa", "nebraska", "oklahoma"]
# Ce qui n'est pas un site marchand : cartographie, réseaux sociaux, annuaires, places de marché.
NON_MARCHAND = re.compile(
    r"cardshopmap|maps\.google|google\.com|openstreetmap|osm\.org|overturemaps|apple\.com|"
    r"bing\.com|waze|mapquest|yelp\.|facebook\.|instagram\.|twitter\.|x\.com|tiktok\.|"
    r"linktr\.ee|linkedin\.|youtube\.|schema\.org|wikipedia|ebay\.|etsy\.|amazon\.|"
    r"whatnot\.|mercari\.|tcgplayer\.com/?$", re.I)


def classe_urls(urls: list, etat: str) -> dict:
    """Le sitemap, trié par nature. Les salons ne sont pas des boutiques."""
    pref = f"https://cardshopmap.com/card-shops/{etat}"
    out = {"page_etat": [], "pages_ville": [], "fiches_boutique": [],
           "evenements": [], "autres": []}
    for u in urls:
        if f"/{etat}/" not in u and not u.rstrip("/").endswith(f"/{etat}"):
            continue
        p = u.rstrip("/").split("/")
        if u.startswith("https://cardshopmap.com/events/"):
            out["evenements"].append(u)
        elif u.startswith(pref):
            n = len(p)
            (out["page_etat"] if n == 5 else out["pages_ville"] if n == 6
             else out["fiches_boutique"] if n >= 7 else out["autres"]).append(u)
        else:
            out["autres"].append(u)
    return out


def accounting(etat: str, urls: list, lis=sd.lis_fiche) -> dict:
    c = classe_urls(urls, etat)
    fiches = c["fiches_boutique"]
    sans_site, non_marchand, doublons = [], [], []
    domaines = {}
    for u in fiches:
        f = lis(u)
        if not f:
            sans_site.append({"url": u, "raison": "fiche annuaire illisible"})
            continue
        site = f.get("site")
        if not site:
            hors = [s for s in (f.get("sortants") or []) if NON_MARCHAND.search(s)]
            sans_site.append({"url": u, "nom": f.get("nom"), "ville": f.get("ville"),
                              "raison": ("aucun lien sortant marchand"
                                         + (f" — uniquement {len(hors)} lien(s) non marchand(s)"
                                            if hors else ""))})
            continue
        if NON_MARCHAND.search(site):
            non_marchand.append({"url": u, "nom": f.get("nom"), "lien": site,
                                 "raison": "le seul lien sortant est cartographie/réseau/annuaire"})
            continue
        dom = sd.domaine(site)
        if dom in domaines:
            doublons.append({"url": u, "nom": f.get("nom"), "domaine": dom,
                             "raison": f"même domaine que « {domaines[dom]['nom']} »"})
            continue
        domaines[dom] = f
    total = len(fiches)
    somme = len(sans_site) + len(doublons) + len(non_marchand) + len(domaines)
    return {"etat": etat,
            "sitemap_total": sum(len(v) for v in c.values()),
            "page_etat": len(c["page_etat"]), "pages_ville": len(c["pages_ville"]),
            "evenements": len(c["evenements"]), "autres": len(c["autres"]),
            "fiches_boutique": total,
            "sans_site": sans_site, "doublons": doublons, "non_marchand": non_marchand,
            "domaines_uniques": sorted(domaines),
            "equation_verifiee": somme == total,
            "somme": somme}
