#!/usr/bin/env python3
"""PRIZM_WEMBY_CORE — surveillance dédiée du produit central de la chasse.

POURQUOI CETTE FAMILLE A SON PROPRE MOTEUR
------------------------------------------
2023-24 Panini Prizm Basketball NBA porte la rookie card #136 de Victor Wembanyama. C'est le
produit autour duquel tout le reste gravite, et il ne doit pas dépendre d'une découverte
généraliste qui ratisse trois cents références et peut manquer la seule qui compte.

Le 06/09, elle l'a manquée : une boîte International Hobby à 334,95 \$, achetable, chez un
marchand actif depuis 2016. Deux défauts cumulés — la boutique n'était pas enregistrée, et le
sondage de plateforme testait Shopify, recevait un 404, et concluait « illisible » alors que
l'API WooCommerce répondait. Ce module existe pour que cela ne se reproduise pas.

CE QU'IL FAIT DE PLUS QUE LE HUNT GÉNÉRAL
-----------------------------------------
· il conserve les ruptures : un OOS est une information, pas un vide
· il cherche par UPC autant que par nom — un vendeur mal référencé titre mal, mais saisit juste
· il distingue « nous avons cherché et rien trouvé » de « nous ne connaissons pas la boutique »

CE QU'IL NE FAIT PLUS : CRAWLER
-------------------------------
Il lisait lui-même les 52 boutiques que `hunt.py` venait de lire, doublant la durée du run et
la charge imposée aux marchands pour obtenir exactement les mêmes fiches. Il consomme désormais
`products_raw`, la table où `hunt.py` dépose TOUT ce qu'il a lu — rattaché à un SKU ou non.
Ce module ne fait plus une seule requête réseau ; `tests_autonomy` le vérifie en coupant
les sockets avant de l'appeler.

La lecture des deux plateformes, elle, n'a pas disparu : elle a été remontée dans `hunt.py`,
où elle profite à tout le catalogue au lieu du seul Prizm.

LA RÈGLE QUI GOUVERNE TOUT
--------------------------
Le prix n'est JAMAIS un filtre de découverte. Une International Hobby à 989 \$ doit apparaître
au même titre qu'une à 334,95 \$. Découvrir et juger sont deux étapes, et les confondre revient
à décider qu'on ne veut pas savoir.
"""
from __future__ import annotations
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

import hunt

ROOT = Path(__file__).parent
OUT = ROOT / "discovered"
# Formats confirmés par Beckett et Cardboard Connection. Un format n'entre ici QUE si une
# source de référence en atteste la configuration — le reste est marqué non confirmé et
# surveillé quand même, parce qu'un format non documenté peut exister quand même.
FORMATS = {
    "Hobby":         {"packs": 12, "cards": 12, "autos": 2, "confirmed": "Beckett + Cardboard Connection",
                      "exclusives": "Snakeskin, White, Prizmania · 22 Prizms + 10 inserts/boîte"},
    "Fast Break":    {"packs": 10, "cards": 9, "autos": 1, "confirmed": "Beckett + Cardboard Connection",
                      "exclusives": "Blue /150, Red /100, Purple /75, Pink /50, Bronze /20, Neon Green /5 · Rookie Variations"},
    "Choice":        {"packs": 1, "cards": 8, "autos": 1, "confirmed": "Beckett + Cardboard Connection",
                      "exclusives": "Tiger Stripe, Red /88, Blue /49, Cherry Blossom /20, Green /8, Nebula 1/1"},
    "Mega":          {"packs": None, "cards": None, "autos": 0, "confirmed": "existence confirmée, configuration non publiée",
                      "exclusives": "Red Ice (variantes retail)"},
    "International": {"packs": 12, "cards": 5, "autos": None, "confirmed": "fiches marchandes concordantes",
                      "exclusives": "Blue Wave, White Wave /38, Multi Wave /88, Gold Wave /10 · Rookie Sigs Blue/Gold Wave"},
    "Blaster":       {"packs": None, "cards": None, "autos": 0, "confirmed": "non documenté — surveillé quand même",
                      "exclusives": "Ice, Green Wave (à confirmer)"},
    "Retail Box":    {"packs": 24, "cards": None, "autos": 0, "confirmed": "non documenté — surveillé quand même",
                      "exclusives": None},
    "Hanger":        {"packs": None, "cards": None, "autos": 0, "confirmed": "non documenté — surveillé quand même",
                      "exclusives": None},
    "Pack":          {"packs": 1, "cards": None, "autos": 0, "confirmed": "retail, décliné en value/fat/multi",
                      "exclusives": None},
    "FOTL":          {"packs": None, "cards": None, "autos": None, "confirmed": "NON CONFIRMÉ pour cette saison",
                      "exclusives": None},
}

# UPC connus — un vendeur mal référencé titre mal mais saisit juste son code produit.
UPC = {"International": "746134150784", "Hobby": "746134150678", "Fast Break": "746134150753"}

CORE_SKUS = re.compile(r"^PANINI_2023-24_PRIZM_(?!EUROLEAGUE|DRAFT|MONOPOLY)")
TITLE_RE = re.compile(r"prizm", re.I)
SEASON_RE = re.compile(r"2023[-/]24|23[-/]24")
NOT_CORE = re.compile(r"euro\s*league|turkish|draft\s*picks|collegiate|monopoly|\bdeca\b|"
                      r"\bwnba\b|football|soccer|baseball|hockey", re.I)

ALERTS = ("PRIZM_NEW_STOCK", "PRIZM_RESTOCK", "PRIZM_NEW_LOW", "PRIZM_NEW_SELLER",
          "PRIZM_STOCK_AMBIGUOUS", "PRIZM_SOURCE_LOST")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stock_confidence(item: dict, shop: dict) -> str:
    """CONFIRMED_IN_STOCK ne se donne pas à la légère.

    Une boutique qui déclare 100 % de son catalogue disponible ne gère pas ses stocks : son
    « in stock » est une valeur par défaut, pas une information. Kutogo est dans ce cas —
    737 produits sur 737, dont des boîtes 2018-19, avec un champ de disponibilité vide.
    """
    if not item["available"]:
        return "OOS"
    if shop.get("stock_reliability") == "low":
        return "PROBABLY_IN_STOCK"
    if item.get("stock_text") == "":
        return "PROBABLY_IN_STOCK" if shop.get("platform") == "woocommerce" else "CONFIRMED_IN_STOCK"
    return "CONFIRMED_IN_STOCK"


def is_core(title: str, sku: str | None) -> bool:
    """Le noyau, c'est le Prizm NBA SCELLÉ. Trois exclusions, chacune apprise à ses dépens :

    · les familles voisines — EuroLeague, Draft Picks, Monopoly, Deca — ont leur propre marché,
      et les mélanger fausse toute comparaison de prix ;
    · les cartes à l'unité, qui portent le même nom de gamme et la même saison : « 2023-24
      Panini Prizm NBA Amen Thompson » n'est pas une boîte, c'est un single à 230 € ;
    · un UPC connu suffit en revanche à qualifier, même si le titre est mal rédigé — c'est
      précisément le cas des vendeurs mal référencés qu'on cherche.
    """
    if sku and sku in UPC.values():
        return True
    if not (TITLE_RE.search(title) and SEASON_RE.search(title)
            and re.search(r"basketball|\bnba\b", title, re.I)):
        return False
    if NOT_CORE.search(title):
        return False
    return bool(hunt.sealed_product(hunt.norm(title)))


def run(conn, sources, skus, log=print):
    """Le noyau Prizm, extrait de ce que `hunt.py` vient de lire. Aucune requête réseau.

    On prend, boutique par boutique, le DERNIER passage présent dans `products_raw`. Un
    passage plus ancien qu'un autre n'est pas une erreur : une boutique interrompue en cours
    de run garde ses fiches de la veille, et il vaut mieux une fiche datée qu'un trou.
    """
    shops = {sh["key"]: sh for sh in sources}
    rows, seen, lost = [], [], []
    attendus = [sh for sh in sources
                if sh.get("status") != "reject" and sh["type"] in ("shopify_json", "html")
                and not hunt.blocklisted(sh.get("base_url", ""))]
    for sh in attendus:
        k = sh["key"]
        last = conn.execute("SELECT MAX(seen_at) FROM products_raw WHERE shop=?", (k,)).fetchone()[0]
        if not last:
            lost.append(k)
            continue
        fiches = conn.execute(
            "SELECT title, price, available, url, vendor_sku, stock_text, platform, sku_id, seen_at "
            "FROM products_raw WHERE shop=? AND seen_at=?", (k, last)).fetchall()
        if not fiches:
            lost.append(k)
            continue
        seen.append(k)
        n = 0
        for title, price, avail, url, vsku, stext, plat, sku_id, sa in fiches:
            if not is_core(title or "", vsku):
                continue
            # le sku_id stocké vient du matcher du crawl ; on le recalcule si la fiche n'en
            # portait pas (une fiche qualifiée par son seul UPC n'en a jamais eu)
            sid = sku_id or hunt.match_title(title, skus).sku_id
            # un « 12 Box Case » à 13 549 $ n'est pas une boîte : sans la quantité, il se
            # compare aux 874 $ d'une Hobby seule et fait passer le marché pour fou
            qte = max(1, hunt.parse_quantity(hunt.norm(title)) or 1)
            px = float(price or 0)
            item = {"title": title, "price": px, "available": bool(avail),
                    "sku": vsku, "stock_text": stext, "url": url,
                    "quantity": qte, "unit_price": round(px / qte, 2) if px else None}
            rows.append({**item, "shop": k, "country": sh.get("country", "US"),
                         "currency": sh.get("currency", "USD"),
                         "sku_id": sid, "platform": plat,
                         "stock_confidence": stock_confidence(item, {**sh, "platform": plat}),
                         "seen_at": sa, "source_layer": "REGISTERED_SOURCES",
                         "read_from": "hunt.db/products_raw"})
            n += 1
        log(f"  {k:<22} {len(fiches):>5} fiches ({last[:16]}) · {n:>2} Prizm core · {plat or '?'}")
    return rows, seen, lost


def main():
    cat = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    hunt.load_blocklist(src)
    OUT.mkdir(exist_ok=True)
    print("PRIZM_WEMBY_CORE — 2023-24 Panini Prizm Basketball NBA")
    print("lecture de hunt.db/products_raw — aucune boutique n'est recontactée\n")
    # hunt.db() et non sqlite3.connect : la migration douce doit tourner, la base
    # peut dater d'avant les colonnes plateforme.
    conn = hunt.db()
    rows, seen, lost = run(conn, src["shops"], cat["skus"])
    prev_path = OUT / "prizm_core.json"
    prev = {}
    if prev_path.exists():
        for r in json.loads(prev_path.read_text(encoding="utf-8")).get("listings", []):
            prev[(r["shop"], r["url"])] = r
    alerts = []
    for r in rows:
        k = (r["shop"], r["url"])
        old = prev.get(k)
        if old is None:
            alerts.append({"type": "PRIZM_NEW_STOCK" if r["available"] else "PRIZM_NEW_SELLER",
                           "url": r["url"], "why": "listing jamais vu"})
        else:
            if r["available"] and not old.get("available"):
                alerts.append({"type": "PRIZM_RESTOCK", "url": r["url"],
                               "why": "était en rupture au passage précédent"})
            if r["price"] and old.get("price") and r["price"] < old["price"]:
                alerts.append({"type": "PRIZM_NEW_LOW", "url": r["url"],
                               "why": f"{r['price']:.2f} contre {old['price']:.2f}"})
        if r["stock_confidence"] == "PROBABLY_IN_STOCK":
            alerts.append({"type": "PRIZM_STOCK_AMBIGUOUS", "url": r["url"],
                           "why": "la boutique ne gère pas ses quantités — à vérifier à la main"})
    for k in lost:
        alerts.append({"type": "PRIZM_SOURCE_LOST", "url": k,
                       "why": "aucune fiche dans products_raw : le crawl n'a rien rapporté de cette boutique"})
    payload = {"generated_at": now(), "collection": "hunt.db/products_raw (aucun crawl propre)",
               "sources_read": seen, "sources_lost": lost,
               "formats": FORMATS, "upc": UPC, "listings": rows, "alerts": alerts}
    prev_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(rows)} listing(s) Prizm core · {len(seen)} source(s) lues · {len(lost)} perdue(s)")
    print(f"{len(alerts)} alerte(s) → {prev_path}")


if __name__ == "__main__":
    main()
