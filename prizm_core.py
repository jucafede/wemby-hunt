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
· il interroge TOUTES les plateformes sur chaque boutique, jamais la première qui répond
· il conserve les ruptures : un OOS est une information, pas un vide
· il cherche par UPC autant que par nom — un vendeur mal référencé titre mal, mais saisit juste
· il distingue « nous avons cherché et rien trouvé » de « nous ne connaissons pas la boutique »

LA RÈGLE QUI GOUVERNE TOUT
--------------------------
Le prix n'est JAMAIS un filtre de découverte. Une International Hobby à 989 \$ doit apparaître
au même titre qu'une à 334,95 \$. Découvrir et juger sont deux étapes, et les confondre revient
à décider qu'on ne veut pas savoir.
"""
from __future__ import annotations
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

import hunt

ROOT = Path(__file__).parent
OUT = ROOT / "discovered"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

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


def get(url, timeout=25):
    try:
        return json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX))
    except Exception:
        return None


def read_all_platforms(base: str):
    """Shopify ET WooCommerce, systématiquement. C'est la correction du 06/09 : s'arrêter à la
    première plateforme qui répond 404 fait manquer des boutiques entières."""
    items, plat = [], None
    for p in range(1, 16):
        j = get(f"{base}/products.json?limit=250&page={p}")
        pr = (j or {}).get("products") or []
        if not pr:
            break
        plat = "shopify"
        for x in pr:
            for v in x.get("variants") or []:
                vt = v.get("title") or ""
                vt = "" if vt.lower() in ("default title", "default") else vt
                items.append({"title": f"{x['title']} {vt}".strip(),
                              "price": float(v.get("price") or 0),
                              "available": bool(v.get("available")),
                              "sku": v.get("sku"),
                              "url": f"{base}/products/{x.get('handle','')}"})
        time.sleep(0.4)
    if items:
        return items, plat
    import html as _h
    for p in range(1, 16):
        j = get(f"{base}/wp-json/wc/store/v1/products?per_page=100&page={p}")
        if not isinstance(j, list) or not j:
            break
        plat = "woocommerce"
        for x in j:
            pr = x.get("prices") or {}
            mn = int(pr.get("currency_minor_unit", 2) or 2)
            items.append({"title": _h.unescape(x.get("name", "")),
                          "price": float(pr.get("price") or 0) / (10 ** mn),
                          "available": bool(x.get("is_in_stock")),
                          "sku": x.get("sku"),
                          # ce champ dit si la boutique GÈRE ses stocks : vide = non géré
                          "stock_text": ((x.get("stock_availability") or {}).get("text") or ""),
                          "url": x.get("permalink", "")})
        time.sleep(0.4)
    return items, plat


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


def run(sources, skus, log=print):
    seen, lost, rows = [], [], []
    for sh in sources:
        if sh.get("status") == "reject" or sh["type"] not in ("shopify_json", "html"):
            continue
        if hunt.blocklisted(sh.get("base_url", "")):
            continue
        items, plat = read_all_platforms(sh["base_url"])
        if not items:
            lost.append(sh["key"])
            continue
        seen.append(sh["key"])
        n = 0
        for it in items:
            if not is_core(it["title"], it.get("sku")):
                continue
            m = hunt.match_title(it["title"], skus)
            rows.append({**it, "shop": sh["key"], "country": sh.get("country", "US"),
                         "currency": sh.get("currency", "USD"),
                         "sku_id": m.sku_id, "platform": plat,
                         "stock_confidence": stock_confidence(it, {**sh, "platform": plat}),
                         "seen_at": now()})
            n += 1
        log(f"  {sh['key']:<22} {len(items):>5} fiches · {n:>2} Prizm core · {plat}")
    return rows, seen, lost


def main():
    cat = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    hunt.load_blocklist(src)
    OUT.mkdir(exist_ok=True)
    print("PRIZM_WEMBY_CORE — 2023-24 Panini Prizm Basketball NBA\n")
    rows, seen, lost = run(src["shops"], cat["skus"])
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
                       "why": "aucune fiche lue : boutique injoignable ou plateforme changée"})
    payload = {"generated_at": now(), "sources_read": seen, "sources_lost": lost,
               "formats": FORMATS, "upc": UPC, "listings": rows, "alerts": alerts}
    prev_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(rows)} listing(s) Prizm core · {len(seen)} source(s) lues · {len(lost)} perdue(s)")
    print(f"{len(alerts)} alerte(s) → {prev_path}")


if __name__ == "__main__":
    main()
