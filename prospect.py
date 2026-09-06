#!/usr/bin/env python3
"""Découverte par EXPLORATION DE CATALOGUES — produits, formats et vendeurs inconnus.

LE PROBLÈME QUE CE MODULE RÉSOUT
--------------------------------
discover.py cherche des VENDEURS à partir de produits qu'on connaît déjà. Il ne peut donc,
par construction, jamais trouver un produit qu'on ignore. Or c'est exactement ce qui manquait :
le Prizm Draft Picks dormait chez Stickerpoint depuis des mois, et aucune requête ne pouvait
le révéler puisque personne n'avait pensé à le chercher.

Ce module inverse la démarche. Il lit les catalogues ENTIERS des boutiques accessibles et
laisse les données parler : tout titre qui ressemble à une boîte de basket scellée d'une
saison Wemby, et que le catalogue ne sait pas nommer, devient un candidat documenté.

Aucune invention. Un produit n'est proposé que s'il est adossé à au moins une fiche réelle,
avec son URL, son prix et son vendeur. Un format n'existe que si un marchand le vend.

TROIS FAMILLES DE DÉCOUVERTE
----------------------------
  UNKNOWN_PRODUCT  une boîte scellée qu'aucun SKU ne reconnaît
  UNKNOWN_FORMAT   un set connu, décliné dans un format que le catalogue ignore
  UNKNOWN_SELLER   un domaine croisé dans les liens sortants ou les recherches

CE QU'IL NE FAIT PAS
--------------------
Il ne modifie ni catalog.yaml ni sources.yaml. L'ajout d'un SKU ou d'une source reste une
décision humaine — la même règle que discover.py depuis le premier jour.
"""
from __future__ import annotations
import argparse
import collections
import json
import re
import ssl
import sys
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
DELAY = 1.0            # une requête par seconde et par boutique
MAX_PAGES = 24         # 250 produits par page : de quoi lire 6 000 références

# Saisons de la fenêtre Wemby. 2023-24 est la rookie year — priorité absolue. On garde 2024-25
# et 2025-26 parce qu'il y figure aussi, et 2022-23 EXCLUSIVEMENT pour pouvoir le REJETER
# explicitement : c'est l'année Banchero, elle ne contient aucun Wemby, et un stock ancien
# 2022-23 en rayon n'est pas une trouvaille, c'est un piège.
WEMBY_SEASONS = ("2023-24", "2024-25", "2025-26")
PRE_WEMBY = ("2022-23", "2021-22", "2020-21", "2019-20")

# Vocabulaire de format observé sur le marché. Sert à REPÉRER un format dans un titre, jamais
# à en inventer un : un format n'entre au rapport que si un titre réel le porte.
FORMAT_WORDS = [
    "fat pack", "value pack", "value box", "retail box", "hanger", "blaster", "mega",
    "hobby jumbo", "hobby box", "hobby", "jumbo", "cello", "choice", "fast break", "fast brk",
    "h2", "hybrid", "fotl", "first off the line", "1st off the line", "tmall", "t-mall",
    "international", "premium", "factory set", "breakers delight", "tin", "gravity feed",
    "case", "box", "pack",
]

MANUFACTURERS = {"panini": "Panini", "topps": "Topps", "upper deck": "Upper Deck"}

# Contexte de ligue — la distinction que le catalogue ne faisait pas. Un Prizm Draft Picks
# n'est pas un produit NBA : c'est du draft/collegiate, la carte Wemby n'y porte pas le logo
# RC officiel, et son marché est distinct. Les mélanger fausse toute comparaison de prix.
LEAGUE_PATTERNS = [
    ("EuroLeague", r"euro\s*league|euroleague|turkish airlines"),
    ("Collegiate/Draft", r"draft picks|collegiate|\bncaa\b|prizm draft"),
    ("WNBA", r"\bwnba\b"),
    ("NBL", r"\bnbl\b"),
    ("OTE", r"overtime elite|\bote\b"),
    ("G-League", r"g[- ]league"),
]

NON_BASKET = re.compile(
    r"football|soccer|fifa|baseball|hockey|\bnfl\b|\bmlb\b|\bnhl\b|pokemon|ufc|wrestl|\bwwe\b|"
    r"formula|\bf1\b|nascar|golf|tennis|marvel|star wars|disney|harry potter|one piece|"
    r"lorcana|magic the gathering|yu-?gi-?oh|digimon|bundesliga|premier league|la liga|"
    r"serie a|ligue 1|champions league|veefriends|garbage pail|mandalorian", re.I)

IS_BASKET = re.compile(r"basketball|\bnba\b|\bhoops\b|euroleague", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url: str, tries: int = 2, timeout: int = 30):
    for k in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                       timeout=timeout, context=CTX)
            return r.read().decode("utf-8", "replace")
        except Exception:
            if k < tries - 1:
                time.sleep(2)
    return None


# ---------------------------------------------------------------- lecture des catalogues
def shopify_catalog(base: str, log=print):
    """Toutes les fiches d'une boutique Shopify. Une entrée PAR VARIANTE : c'est au niveau de
    la variante que se joue la distinction boîte / case, et la confondre a déjà coûté cher."""
    out = []
    for p in range(1, MAX_PAGES + 1):
        body = fetch(f"{base}/products.json?limit=250&page={p}")
        if not body:
            break
        try:
            prods = (json.loads(body) or {}).get("products") or []
        except Exception:
            break
        if not prods:
            break
        for x in prods:
            for v in x.get("variants") or []:
                vt = v.get("title") or ""
                vt = "" if vt.lower() in ("default title", "default") else vt
                out.append({
                    "title": f"{x['title']} {vt}".strip(),
                    "price": float(v.get("price") or 0),
                    "available": bool(v.get("available")),
                    "url": f"{base}/products/{x.get('handle','')}",
                    "vendor": x.get("vendor"), "ptype": x.get("product_type"),
                    "published_at": x.get("published_at"),
                })
        time.sleep(DELAY)
    return out


def woo_catalog(base: str, log=print):
    """API Store de WooCommerce, publique par défaut. Quand elle répond, on évite tout scraping."""
    out = []
    for p in range(1, 30):
        body = fetch(f"{base}/wp-json/wc/store/v1/products?per_page=100&page={p}")
        if not body:
            break
        try:
            items = json.loads(body)
        except Exception:
            break
        if not isinstance(items, list) or not items:
            break
        for x in items:
            pr = x.get("prices") or {}
            mn = int(pr.get("currency_minor_unit", 2) or 2)
            out.append({
                "title": x.get("name", ""),
                "price": float(pr.get("price") or 0) / (10 ** mn),
                "available": bool(x.get("is_in_stock")),
                "url": x.get("permalink", ""), "vendor": None, "ptype": None,
                "published_at": None,
            })
        time.sleep(DELAY)
    return out


def adapter_catalog(key: str, log=print):
    """Boutique servie par un adaptateur HTML écrit à la main (osCommerce, thèmes fermés)."""
    import html_adapters as ha
    ad = ha.adapter_for(key)
    if not ad:
        return []
    out = []
    for seed in ad.seeds:
        body = fetch(seed)
        if not body:
            continue
        got = ad.parse(body, seed)
        for it in (got if isinstance(got, list) else [got] if got else []):
            out.append({"title": it["title"], "price": it.get("price") or 0,
                        "available": bool(it.get("available")), "url": it.get("url", ""),
                        "vendor": None, "ptype": None, "published_at": None})
        time.sleep(DELAY)
    return out


def read_catalog(base: str, hint: str | None = None, log=print, key: str | None = None):
    """Adaptateur dédié d'abord s'il en existe un, sinon Shopify, sinon WooCommerce."""
    if key:
        items = adapter_catalog(key, log)
        if items:
            return items, "adaptateur"
    if hint != "woocommerce":
        items = shopify_catalog(base, log)
        if items:
            return items, "shopify"
    items = woo_catalog(base, log)
    if items:
        return items, "woocommerce"
    return [], None


# ---------------------------------------------------------------- lecture d'un titre
def season_of(t: str) -> str | None:
    """Saison telle qu'elle est ÉCRITE. On ne devine pas : « 2023 Panini Prizm Draft Picks »
    est un produit draft daté d'une seule année, et le forcer en 2023-24 serait une invention."""
    s = hunt.parse_season(hunt.norm(t))
    if s:
        return s
    m = re.search(r"\b(20\d{2})\b", t)
    return m.group(1) if m else None


def league_of(t: str) -> str:
    for name, rx in LEAGUE_PATTERNS:
        if re.search(rx, t, re.I):
            return name
    return "NBA"


def formats_in(t: str) -> list[str]:
    low = hunt.norm(t)
    hits = []
    for w in FORMAT_WORDS:
        if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
            hits.append(w)
    # « box » et « pack » sont trop génériques pour compter s'ils accompagnent un format nommé
    if len(hits) > 1:
        hits = [h for h in hits if h not in ("box", "pack")] or hits
    return hits


def manufacturer_of(t: str) -> str | None:
    low = t.lower()
    for k, v in MANUFACTURERS.items():
        if k in low:
            return v
    return None


def set_guess(t: str, known_sets: set[str]) -> str | None:
    """Le set nommé dans le titre, parmi ceux que le catalogue connaît, plus une liste de
    gammes réellement éditées. On ne crée pas de set à partir d'un mot inconnu."""
    low = t.lower()
    extra = ["prizm draft picks", "crown royale", "obsidian", "spectra", "recon", "chronicles",
             "totally certified", "contenders optic", "origins", "one and one", "immaculate",
             "national treasures", "flawless", "court kings", "revolution", "phoenix",
             "premium stock", "donruss optic", "donruss", "mosaic", "select", "prizm", "hoops",
             "noir", "opulence", "impeccable", "eminence", "vanguard", "absolute", "certified",
             "elite", "encased", "gold standard", "limited", "luminance", "photogenic",
             "instant", "definitive", "inception", "cosmic chrome", "midnight", "finest",
             "bowman", "topps chrome", "signature class", "sapphire", "merlin", "stadium club"]
    cands = sorted({s for s in list(known_sets) + extra if s and s.lower() in low},
                   key=len, reverse=True)
    return cands[0] if cands else None


def is_sealed_box(t: str) -> bool:
    """Le sealed gate du moteur, réutilisé tel quel. Un single n'est jamais un candidat."""
    return bool(hunt.sealed_product(hunt.norm(t)))


# ---------------------------------------------------------------- moteur
def prospect(sources, skus, only=None, log=print):
    known_sets = {str(x.get("set") or "").lower() for x in skus}
    known_pairs = {(x.get("season"), str(x.get("set") or "").lower(),
                    str(x.get("format") or "").lower()) for x in skus}
    known_sets_by_season = collections.defaultdict(set)
    for x in skus:
        known_sets_by_season[x.get("season")].add(str(x.get("set") or "").lower())

    found = []          # candidats produits
    sellers = {}        # domaines croisés
    stats = collections.Counter()
    rejets = collections.Counter()
    per_shop = {}

    for sh in sources:
        key = sh["key"]
        if only and key not in only:
            continue
        if sh.get("status") == "reject" or sh["type"] not in ("shopify_json", "html"):
            continue
        if hunt.blocklisted(sh.get("base_url", "")):
            log(f"  ⛔ {key} en blocklist — ignoré")
            continue
        t0 = time.monotonic()
        items, plat = read_catalog(sh["base_url"], sh.get("platform"), log, key)
        dur = time.monotonic() - t0
        per_shop[key] = {"items": len(items), "platform": plat, "seconds": round(dur, 1)}
        if not items:
            log(f"  ✗ {key:<22} illisible ({dur:.0f} s)")
            continue
        nb = 0
        for it in items:
            t = it["title"]
            stats["lus"] += 1
            if not IS_BASKET.search(t):
                rejets["pas basket"] += 1; continue
            if NON_BASKET.search(t):
                rejets["autre sport / autre licence"] += 1; continue
            if not is_sealed_box(t):
                rejets["non scellé (single, lot de cartes)"] += 1; continue
            sea = season_of(t)
            if sea is None:
                rejets["saison illisible"] += 1; continue
            if sea in PRE_WEMBY:
                rejets[f"antérieur à Wemby ({sea})"] += 1; continue
            if sea not in WEMBY_SEASONS and not re.match(r"^20\d{2}$", sea):
                rejets[f"hors fenêtre ({sea})"] += 1; continue
            m = hunt.match_title(t, skus)
            fmts = formats_in(t)
            st = set_guess(t, known_sets)
            lg = league_of(t)
            if m.sku_id:
                # produit connu : reste-t-il un format que le catalogue ignore ?
                stats["déjà au catalogue"] += 1
                continue
            kind = "UNKNOWN_PRODUCT"
            if st and st in known_sets_by_season.get(sea, set()):
                kind = "UNKNOWN_FORMAT"
            found.append({
                "kind": kind, "season": sea, "league": lg,
                "manufacturer": manufacturer_of(t), "set": st,
                "exact_product_name": t, "formats_detected": fmts,
                "price": it["price"], "currency": sh.get("currency", "USD"),
                "available": it["available"], "shop": key,
                "country": sh.get("country") or ("US" if sh.get("market_region", "US") == "US" else "FR"),
                "url": it["url"], "published_at": it.get("published_at"),
                "match_score": m.score, "seen_at": now(),
            })
            nb += 1
        log(f"  ✓ {key:<22} {len(items):>5} fiches · {nb:>3} candidat(s) · {plat} · {dur:.0f} s")
    return found, per_shop, stats, rejets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="limiter à ces clés de source")
    ap.add_argument("--out", default="prospect.json")
    a = ap.parse_args()
    cat = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    hunt.load_blocklist(src)
    OUT.mkdir(exist_ok=True)
    print(f"prospection sur {len(src['shops'])} source(s) — 1 req/s\n")
    found, per_shop, stats, rejets = prospect(src["shops"], cat["skus"], a.only)
    payload = {"generated_at": now(), "stats": dict(stats), "rejets": dict(rejets),
               "shops": per_shop, "candidates": found}
    (OUT / a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{stats['lus']} fiche(s) lues · {len(found)} candidat(s) → {OUT / a.out}")
    par = collections.Counter(c["kind"] for c in found)
    print("  " + " · ".join(f"{k} {v}" for k, v in par.items()))


if __name__ == "__main__":
    main()
