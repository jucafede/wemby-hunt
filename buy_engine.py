#!/usr/bin/env python3
"""BUY ENGINE — « où acheter cette boîte AUJOURD'HUI ? »

POURQUOI SÉPARER DEUX MOTEURS
------------------------------
Le HUNT ENGINE cherche du stock oublié : de vieux LCS, des réassorts, des marchands
inattendus. Le BUY ENGINE répond à une tout autre question, et les confondre a rendu le
projet trop centré sur les boutiques : constater qu'un produit est EN STOCK ne dit pas qu'il
faut l'acheter là. Une Prizm Mega 2023-24 à 249,99 $ est une excellente information
d'inventaire et peut être un très mauvais achat.

CE QU'UNE PLACE DE MARCHÉ EST, ET N'EST PAS
--------------------------------------------
StockX est un RÉFÉRENTIEL DE PRIX, pas une découverte de boutique. Une cote relevée là-bas
n'ajoute aucun marchand au registre et ne qualifie personne : `evidence_role="BENCHMARK"` le
dit dans la donnée elle-même, pour qu'aucun code en aval ne puisse la confondre avec la
preuve qu'un commerçant détient du stock.

LAST SALE N'EST PAS LOWEST ASK
-------------------------------
La dernière vente est un fait passé ; le prix d'achat d'aujourd'hui est le LOWEST ASK. Les
confondre fait miroiter un tarif que personne ne propose. Les deux champs restent distincts,
et l'un ne remplit JAMAIS l'autre.

LE COÛT RENDU FRANCE NE S'INVENTE PAS
--------------------------------------
Frais acheteur, port, TVA : sans checkout ni compte, ils ne sont pas observables. Ils restent
UNKNOWN, et `landed_france` reste None. Un coût rendu partiellement deviné serait pire
qu'absent — il entrerait dans une comparaison de prix comme s'il était mesuré.
"""
from __future__ import annotations
import json, re
from datetime import datetime, timezone

import external_engine as xe

BENCHMARK = "BENCHMARK"          # référence de prix — JAMAIS une preuve de stock marchand
OFFRE = "SHOP_OFFER"             # une vraie offre chez un marchand identifié

STOCKX = "https://stockx.com"
INCONNU = "UNKNOWN"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cote_vide(produit: str, upc: str, motif: str) -> dict:
    """Une cote absente est une cote absente — pas un prix de zéro, pas un prix deviné."""
    return {"source": "stockx", "evidence_role": BENCHMARK, "product": produit, "upc": upc,
            "url": None, "lowest_ask": None, "last_sale": None, "highest_bid": None,
            "buyer_fees": INCONNU, "shipping": INCONNU, "vat": INCONNU,
            "landed_france": None, "currency": None, "observed_at": now(),
            "status": motif}


# StockX rend ses fiches produit en JSON-LD ; les chiffres se lisent là, pas dans le HTML.
_LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def lis_cote(url: str, produit: str, upc: str) -> dict:
    """La cote telle que la fiche PUBLIQUE l'affiche. robots.txt reste souverain."""
    if not xe.robots_ok(url):
        return cote_vide(produit, upc, "STOCKX_ROBOTS_DISALLOW — respecté, non contourné")
    st, b, why = xe.fetch(url, timeout=18)
    if st != 200 or not b:
        return cote_vide(produit, upc, f"STOCKX_UNREADABLE — HTTP {st or why}")
    c = cote_vide(produit, upc, "STOCKX_NO_QUOTE_ON_PAGE")
    c["url"] = url
    for bloc in _LD.findall(b):
        try:
            d = json.loads(bloc)
        except Exception:
            continue
        for o in (d if isinstance(d, list) else [d]):
            if not isinstance(o, dict):
                continue
            offre = o.get("offers") or {}
            if isinstance(offre, list):
                offre = offre[0] if offre else {}
            # « lowPrice » est l'ask le plus bas : c'est le prix d'achat du jour.
            bas = offre.get("lowPrice") or offre.get("price")
            if bas:
                try:
                    c["lowest_ask"] = float(bas)
                    c["currency"] = offre.get("priceCurrency") or "USD"
                    c["status"] = "OK"
                except (TypeError, ValueError):
                    pass
            if offre.get("highPrice"):
                try:
                    c["highest_bid"] = float(offre["highPrice"])
                except (TypeError, ValueError):
                    pass
    return c


def benchmark(cible: dict) -> dict:
    """La cote StockX d'une de nos cinq références canoniques."""
    from urllib.parse import quote
    # On ne peut pas chercher : « Disallow: */search* ». On ne devine donc pas d'URL de fiche
    # et on le DIT, au lieu de fabriquer un slug qui rendrait un 404 pris pour une absence.
    return cote_vide(cible["libelle"], cible["upc"],
                     "STOCKX_SEARCH_DISALLOWED — la recherche est interdite par robots.txt ; "
                     "sans URL de fiche connue, la cote reste non relevée")


# ------------------------------------------------------------------ deal status
BANDES = [(-100, -20, "STRONG_DEAL"), (-20, -10, "DEAL"), (-10, 10, "FAIR"),
          (10, 25, "EXPENSIVE"), (25, 10_000, "VERY_EXPENSIVE")]
REF_MIN = 2          # en deçà, « le marché » n'est qu'une anecdote


def deal_status(prix: float | None, references: list[float]) -> tuple[str, float | None, str]:
    """EN STOCK n'est pas UNE AFFAIRE. Les deux verdicts restent séparés.

    Sans assez de comparables, le statut est UNKNOWN — pas FAIR. Appeler « correct » un prix
    qu'on n'a pas pu comparer serait exactement l'erreur que ce champ doit empêcher.
    """
    refs = [r for r in references if r and r > 0]
    if prix is None or not refs:
        return INCONNU, None, "prix ou référence manquants"
    if len(refs) < REF_MIN:
        return INCONNU, None, (f"{len(refs)} référence(s) comparable(s) — il en faut "
                               f"{REF_MIN} pour parler de marché")
    med = sorted(refs)[len(refs) // 2]
    ecart = round(100 * (prix - med) / med, 1)
    for bas, haut, nom in BANDES:
        if bas <= ecart < haut:
            return nom, ecart, f"{ecart:+.1f} % par rapport à la médiane de {len(refs)} offres"
    return INCONNU, ecart, "écart hors bandes"


def offre_enrichie(o: dict, references: list[float]) -> dict:
    """Une offre marchande, avec son statut de stock ET son statut d'affaire, séparés."""
    st, ecart, motif = deal_status(o.get("price"), references)
    return {**o, "evidence_role": OFFRE,
            "stock_status": o.get("stock") or o.get("in_stock"),
            "market_reference": (sorted(references)[len(references)//2] if references else None),
            "deal_status": st, "deal_ecart_pct": ecart, "deal_motif": motif,
            # Sans frais ni port observables, le coût rendu France n'est pas calculable.
            "landed_france": None,
            "landed_france_note": "frais, port et TVA non observables sans checkout — UNKNOWN"}
