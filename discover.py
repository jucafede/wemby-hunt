#!/usr/bin/env python3
"""
discover.py — prospection de nouvelles sources. INDÉPENDANT de hunt.py.

Pour chaque SKU ACTIVE du catalogue : interroge un moteur de recherche, collecte les domaines,
écarte ceux déjà connus et les géants, puis teste chaque nouveau domaine en Shopify et le qualifie
sur ses propres données (produits totaux / basket / sealed 2023-24).

Sortie : discovered/candidates.yaml + un fragment HTML repris par la page.
NE MODIFIE JAMAIS sources.yaml — la décision d'ajouter une source reste humaine.

Usage:
  python discover.py                  # tous les SKU ACTIVE
  python discover.py --limit 5        # 5 SKU (mise au point)
  python discover.py --engine ddg     # force le moteur
  python discover.py --no-probe       # collecte les domaines sans les sonder

Moteur : SerpAPI si SERPAPI_KEY est défini, sinon DuckDuckGo HTML (gratuit, sans clé).
"""
from __future__ import annotations
import argparse, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse, quote_plus

import requests
import yaml

ROOT = Path(__file__).parent
OUT = ROOT / "discovered"   # versionné : hunt.py y lit la section pour la page
UA = "wemby-hunt-discover/1.0 (personal price research; contact via order email)"
RATE_S = 1.0          # 1 requête/seconde, moteur comme boutiques
PROBE_TIMEOUT = 20

# Géants, places de marché, agrégateurs et médias : jamais des LCS à démarcher.
GIANTS = {
    "target.com", "walmart.com", "ebay.com", "amazon.com", "dacardworld.com",
    "steelcitycollectibles.com", "blowoutcards.com", "fanatics.com", "stockx.com",
    "panini-america.com", "paniniamerica.net", "topps.com", "whatnot.com", "comc.com",
    "pwccmarketplace.com", "goldin.co", "alt.xyz", "cardladder.com", "sportscardspro.com",
    "pricecharting.com", "beckett.com", "psacard.com", "sgccard.com", "tcgplayer.com",
    "mercari.com", "etsy.com", "facebook.com", "instagram.com", "youtube.com", "tiktok.com",
    "reddit.com", "x.com", "twitter.com", "pinterest.com", "wikipedia.org", "google.com",
    "bing.com", "duckduckgo.com", "costco.com", "samsclub.com", "bestbuy.com", "meijer.com",
    "kroger.com", "cvs.com", "walgreens.com", "gamestop.com", "barnesandnoble.com",
    "waxstat.com", "cardboardconnection.com", "sportscollectorsdaily.com", "espn.com",
}
GIANT_SUFFIXES = (".gov", ".edu", ".mil")


def registrable(host: str) -> str:
    """Rabat www.x.co.uk / shop.x.com sur le domaine à démarcher. Suffisant ici : on ne fait
    que dédoublonner et exclure, pas du parsing DNS."""
    h = (host or "").lower().strip().rstrip(".")
    if h.startswith("www."): h = h[4:]
    return h


def is_excluded(host: str, known: set[str]) -> str | None:
    if not host: return "vide"
    if host.endswith(GIANT_SUFFIXES): return "institutionnel"
    if host in known: return "déjà dans sources.yaml"
    if host in GIANTS: return "géant/marketplace"
    if any(host.endswith("." + g) for g in GIANTS): return "sous-domaine de géant"
    return None


# ---------------------------------------------------------------- moteurs de recherche
def search_serpapi(query: str, key: str, n: int = 20) -> list[str]:
    r = requests.get("https://serpapi.com/search.json",
                     params={"q": query, "engine": "google", "num": n, "api_key": key},
                     headers={"User-Agent": UA}, timeout=PROBE_TIMEOUT)
    r.raise_for_status()
    return [x.get("link", "") for x in r.json().get("organic_results", [])]


DDG_HREF = re.compile(r'<a[^>]*\bclass="[^"]*result__a[^"]*"[^>]*href="([^"]+)"'
                      r'|<a[^>]*href="([^"]+)"[^>]*\bclass="[^"]*result__a[^"]*"')
DDG_ANY = re.compile(r'href="(https?://[^"]+)"')

def search_ddg(query: str, n: int = 20) -> list[str]:
    """DuckDuckGo HTML : pas de clé, pas de quota annoncé. En contrepartie le HTML peut changer —
    d'où le second motif de repli."""
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                      headers={"User-Agent": UA}, timeout=PROBE_TIMEOUT)
    r.raise_for_status()
    links = [a or b for a, b in DDG_HREF.findall(r.text)] or DDG_ANY.findall(r.text)
    out = []
    for l in links:
        m = re.search(r"uddg=([^&]+)", l)      # DDG encapsule parfois la cible
        if m:
            from urllib.parse import unquote
            l = unquote(m.group(1))
        if l.startswith("http"): out.append(l)
    return out[:n]


def search(query: str, engine: str, key: str | None) -> list[str]:
    try:
        if engine == "serpapi" and key: return search_serpapi(query, key)
        return search_ddg(query)
    except Exception as e:
        print(f"    ! recherche en échec ({e.__class__.__name__}: {e})")
        return []
    finally:
        time.sleep(RATE_S)


# ---------------------------------------------------------------- sondage d'un domaine
def probe(host: str, skus: list[dict]) -> dict:
    """Teste /products.json. Un seul appel de 250 produits : on qualifie, on ne crawle pas."""
    import hunt   # réutilise le normaliseur SANS le modifier
    res = {"domain": host, "shopify": False, "products_sampled": 0,
           "basketball": 0, "sealed_2023_24": 0, "matched": 0, "error": None}
    s = requests.Session(); s.headers["User-Agent"] = UA
    for scheme in ("https://", "http://"):
        base = scheme + host
        try:
            r = s.get(f"{base}/products.json", params={"limit": 250}, timeout=PROBE_TIMEOUT)
            time.sleep(RATE_S)
            if r.status_code != 200: continue
            prods = r.json().get("products", [])
        except Exception as e:
            res["error"] = f"{e.__class__.__name__}"; continue
        res["shopify"] = True
        res["base_url"] = base
        res["products_sampled"] = len(prods)
        for p in prods:
            for v in (p.get("variants") or []):
                vt = v.get("title") or ""
                vt = "" if vt.lower() in ("default title", "default") else vt
                full = f"{p.get('title','')} {vt}".strip()
                t = hunt.norm(full)
                if hunt.parse_sport(t) != "basketball": continue
                res["basketball"] += 1
                if hunt.parse_format(t) and hunt.parse_season(t) == "2023-24":
                    res["sealed_2023_24"] += 1
                if hunt.match_title(full, skus).sku_id: res["matched"] += 1
        return res
    return res


# ---------------------------------------------------------------- rendu
def write_outputs(cands: list[dict], queried: int, engine: str, stamp: str):
    OUT.mkdir(exist_ok=True)
    doc = {"generated_at": stamp, "engine": engine, "skus_queried": queried,
           "note": "Prospection automatique. sources.yaml n'est JAMAIS modifié par ce module.",
           "candidates": cands}
    (OUT / "candidates.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    h = ["<h2>🔎 Nouveaux candidats</h2>",
         f"<p class=small>discover.py — {stamp} · moteur {engine} · {queried} SKU ACTIVE interrogés · "
         f"{len(cands)} domaine(s) retenus. Aucun ajout automatique à sources.yaml.</p>"]
    if not cands:
        h.append("<p class=small>Aucun nouveau domaine Shopify détecté ce passage.</p>")
    else:
        h.append("<table><tr><th>Domaine</th><th>Shopify</th><th>Échantillon</th>"
                 "<th>Basket</th><th>Sealed 23-24</th><th>Matchés</th><th>Vu pour</th></tr>")
        for c in cands:
            h.append(f"<tr><td><a href='{c.get('base_url', 'https://'+c['domain'])}'>{c['domain']}</a></td>"
                     f"<td>{'oui' if c['shopify'] else 'non'}</td><td>{c['products_sampled']}</td>"
                     f"<td>{c['basketball']}</td><td>{c['sealed_2023_24']}</td><td>{c['matched']}</td>"
                     f"<td class=small>{', '.join(c['seen_for'][:3])}</td></tr>")
        h.append("</table>")
    (OUT / "candidates.html").write_text("\n".join(h), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="nombre de SKU ACTIVE à interroger")
    ap.add_argument("--engine", choices=["serpapi", "ddg"], help="force le moteur")
    ap.add_argument("--no-probe", action="store_true", help="collecte les domaines sans les sonder")
    a = ap.parse_args()

    cat = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    skus = cat["skus"]
    known = {registrable(urlparse(s["base_url"]).netloc) for s in src["shops"]}

    key = os.environ.get("SERPAPI_KEY") or None
    engine = a.engine or ("serpapi" if key else "ddg")
    if engine == "serpapi" and not key:
        print("SERPAPI_KEY absent → bascule sur DuckDuckGo"); engine = "ddg"
    print(f"moteur : {engine} | {len(known)} domaines déjà connus | {len(GIANTS)} géants exclus")

    active = [s for s in skus if s.get("status", "ACTIVE") == "ACTIVE"]
    if a.limit: active = active[:a.limit]
    print(f"{len(active)} SKU ACTIVE à interroger\n")

    found: dict[str, set] = {}
    for s in active:
        label = f'{s["season"]} {s["manufacturer"]} {s["set"]} {s["format"]}'
        queries = [f'"{label}" basketball box in stock',
                   f'{label} basketball "add to cart" card shop',
                   f'{label} basketball box "sold out" collectibles store']
        print(f"→ {s['id']}")
        for q in queries:
            for url in search(q, engine, key):
                host = registrable(urlparse(url).netloc)
                if is_excluded(host, known): continue
                found.setdefault(host, set()).add(s["id"])
    print(f"\n{len(found)} domaine(s) nouveaux après exclusions")

    cands = []
    for host, seen_for in sorted(found.items()):
        if a.no_probe:
            cands.append({"domain": host, "shopify": None, "products_sampled": 0, "basketball": 0,
                          "sealed_2023_24": 0, "matched": 0, "seen_for": sorted(seen_for)})
            continue
        print(f"  sonde {host} …", end=" ", flush=True)
        r = probe(host, skus)
        r["seen_for"] = sorted(seen_for)
        print(f"shopify={r['shopify']} basket={r['basketball']} sealed23-24={r['sealed_2023_24']} match={r['matched']}")
        if r["shopify"]: cands.append(r)

    cands.sort(key=lambda c: (-c["sealed_2023_24"], -c["basketball"]))
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_outputs(cands, len(active), engine, stamp)
    print(f"\ncandidats Shopify retenus : {len(cands)}")
    print(f"→ {OUT/'candidates.yaml'}\n→ {OUT/'candidates.html'}")
    print("sources.yaml NON modifié (par conception).")


if __name__ == "__main__":
    main()
