#!/usr/bin/env python3
"""
wemby-hunt v1 — moteur de détection de prix sur les LCS US (Shopify).
Pipeline : shops -> products_raw -> normalisation -> sku_id (score) -> observations -> décision.

Usage:
  python hunt.py                 # crawl tous les shops + rapport
  python hunt.py --shop ehcards  # un seul shop
  python hunt.py --report        # rapport seul depuis la base (pas de crawl)
  python hunt.py --dry-run       # normalise des titres de test (sans réseau)
"""
from __future__ import annotations
import argparse, csv, json, re, sqlite3, sys, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).parent
DB = ROOT / "hunt.db"
OUT = ROOT / "out"
MATCHER_VERSION = "1.4"
UA = "wemby-hunt/1.4 (personal price research; contact via order email)"
RATE_S = 1.0  # 1 requête / seconde par shop

# ---------------------------------------------------------------- normalisation
FORMATS = [
    # Pack en tête : une variante Shopify ", Pack" ou un "4-Card Pack" ne doit JAMAIS être lu comme une boîte.
    # Le (?<![\w-]) protège "6-Pack Blaster" / "24-Pack Retail Box", où "pack" décrit le contenu de la boîte,
    # pas le produit. Les packs nommés (fat/value/multi) gardent leurs entrées dédiées, testées plus bas.
    ("Fat Pack", r"fat[- ]?pack"),
    ("Cello", r"\bcello\b|multi[- ]?pack"),
    ("Value Box", r"value\s*box"),
    ("Retail Box", r"\bretail\s*box\b|24[- ]?pack"),
    ("Pack", r"(?<![\w-])packs?\b"),
    ("Case", r"\bcase\b|\d+\s*-?\s*box\s*case"),
    ("FOTL", r"first\s*off\s*the\s*line|\bfotl\b"),
    ("Fast Break", r"fast\s*break"),
    ("Choice", r"\bchoice\b"),
    ("H2", r"\bh2\b|hybrid"),
    ("Tin", r"\btin\b"),
    ("Chinese New Year", r"chinese\s*new\s*year|\bcny\b|lunar"),
    ("International", r"\binternational\b|\bintl\b|\basia\b|\btmall\b"),
    ("Hobby Mega", r"hobby\s*mega|mega\s*hobby"),
    ("Hobby Blaster", r"hobby\s*blaster"),
    ("Hobby", r"\bhobby\b"),
    ("Mega", r"\bmega\b"),
    ("Blaster", r"\bblaster\b"),
    ("Hanger", r"\bhanger\b"),
]
# Exclusivités retailer : un titre qui en porte une ne peut matcher QU'UN SKU déclarant cette configuration.
# Décision 17/08 : Walmart Reactive Blue/Pink = le Mega standard ; Target Reactive Yellow/Green = SKU distinct.
EXCLUSIVES = [
    ("Target", r"\btarget\b|reactive\s*(yellow|green)|yellow\s*/\s*green"),
    ("Fanatics", r"\bfanatics\b"),
]

def parse_exclusive(t: str) -> str | None:
    for name, rx in EXCLUSIVES:
        if re.search(rx, t): return name
    return None
SEASON_RE = re.compile(r"(20\d{2})\s*[-/–]\s*(\d{2,4})|(?<!\d)(\d{2})\s*[-/–]\s*(\d{2})(?!\d)")
SPORT_HINTS = {"basketball": ["basketball", "nba", "bball", "hoops"], "not_basketball": ["football", "nfl", "baseball", "mlb", "hockey", "nhl", "soccer", "wnba", "pokemon", "ufc", "wrestling", "f1", "euroleague", "golf", "nascar", "racing", "wwe", "tennis", "mma", "boxing", "college", "draft picks", "world cup", "premier league"]}
SEALED_RE = re.compile(r"\b(box|boxes|blaster|mega|hobby|case|pack|packs|tin|display|bundle|lot)\b")
SINGLE_RE = re.compile(r"(#\s*\d+\b|\b\d{1,3}\s*/\s*\d{1,4}\b|\bpsa\b|\bbgs\b|\bsgc\b|\bauto\b|\bautograph\b|\brc\b\s*$|\bpatch\b|\brelic\b|\bslab)")
CONFIG_HINTS = ["target", "walmart", "fanatics", "exclusive", "green shock", "cracked ice", "red ice", "blue ice", "green ice", "hyper pink", "hyper orange", "glitter", "flash", "ice prizm", "seismic", "npp", "reactive", "fluorescent", "shimmer", "pulsar", "disco", "holo", "purple", "pink", "orange", "yellow", "green", "blue", "red"]

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("&amp;", "&")).strip()

def parse_season(t: str) -> str | None:
    m = SEASON_RE.search(t)
    if not m: return None
    if m.group(1):
        y1 = int(m.group(1)); y2 = m.group(2)
        y2 = int(y2[-2:])
    else:
        y1 = 2000 + int(m.group(3)); y2 = int(m.group(4))
    if (y1 % 100 + 1) % 100 != y2: return None  # doit être consécutif (23-24)
    return f"{y1}-{y2:02d}"

def parse_format(t: str) -> str | None:
    for name, rx in FORMATS:
        if re.search(rx, t): return name
    return None

def parse_sport(t: str) -> str:
    if any(k in t for k in SPORT_HINTS["not_basketball"]): return "other"
    if any(k in t for k in SPORT_HINTS["basketball"]): return "basketball"
    return "unknown"

def parse_config(t: str) -> str | None:
    hits = [h for h in CONFIG_HINTS if h in t]
    return ", ".join(hits) if hits else None

@dataclass
class Match:
    sku_id: str | None
    score: float
    candidates: list  # [(sku_id, score)]
    season: str | None
    fmt: str | None
    sport: str
    config: str | None

def match_title(title: str, skus: list[dict]) -> Match:
    t = norm(title)
    season, fmt, sport, cfg = parse_season(t), parse_format(t), parse_sport(t), parse_config(t)
    excl = parse_exclusive(t)
    cands = []
    # likely_single : signaux forts de carte individuelle SANS signal sealed → ignoré (pas même en REVIEW).
    # Un titre sans "Box" mais sans signal single (ex. "2023-24 Panini Phoenix Basketball") reste candidat → REVIEW.
    if SINGLE_RE.search(t) and not re.search(r"\b(box|boxes|blaster|mega|hobby|case|tin|display)\b", t):
        return Match(None, 0.0, [], season, fmt, sport, cfg)
    for s in skus:
        sc = 0.0
        names = [s["set"].lower()] + [a.lower() for a in s.get("aliases", [])]
        set_hit = any(re.search(rf"\b{re.escape(n)}\b", t) for n in names)
        if not set_hit: continue
        # garde-fous : "Donruss Optic" vs "Donruss" seul, "Prizm" vs "Prizm Monopoly", "Hoops Premium Stock" vs "Hoops"
        if s["set"].lower() == "prizm":
            if any(k in t for k in ("monopoly", "draft", "deca", "emergent", "flashback", "collegiate")): continue
            if not re.search(r"(panini\s+prizm|prizm\s+(basketball|nba|bball))", t): continue  # évite "Ice Prizms", "Hyper Pink Prizms"
        if s["set"].lower() == "donruss optic" and ("optic" not in t or "contenders" in t or "recon" in t): continue
        if s["set"].lower() == "contenders" and "optic" in t: continue   # "Contenders Optic" est une autre gamme
        if s["set"].lower() == "select" and ("select racing" in t or "nascar" in t): continue
        # FOTL / International (asia, tmall) sont désormais des FORMATS détectés : le garde-fou "mauvais format
        # = éliminé" suffit, comme pour Hanger. Ne restent ici que les sous-gammes sans format dédié.
        if any(k in t for k in ("cello", "multi-pack", "value pack")): continue
        # exclusivité retailer : Target/Fanatics ne peut matcher qu'un SKU portant cette configuration,
        # et un SKU d'exclusivité ne peut pas absorber un titre standard. Sinon → pas de candidat → REVIEW.
        sku_cfg = (s.get("configuration") or "")
        if excl:
            if excl.lower() not in sku_cfg.lower(): continue
        elif parse_exclusive(sku_cfg.lower()): continue
        # un Case est toujours "case DE quelque chose" : sans le format interne dans le titre, on ne peut pas
        # décider entre le case Mega et le case Fast Break de la même gamme → aucun candidat → REVIEW.
        if s["format"] == "Case":
            inner = (s.get("case_of") or "").lower()
            if not inner or not re.search(rf"\b{re.escape(inner)}\b", t): continue
        sc += 0.40                                            # gamme
        if season == s["season"]: sc += 0.30                  # saison
        elif season is None: sc += 0.05
        else: continue                                        # mauvaise saison = jamais
        if fmt == s["format"]: sc += 0.25                     # format
        elif fmt is None: sc += 0.0                           # format inconnu → jamais >= 0.80 → REVIEW
        else: continue                                        # mauvais format = jamais
        if sport == "basketball": sc += 0.05
        elif sport == "other": continue
        if s["manufacturer"].lower() in t: sc = min(1.0, sc + 0.02)
        cands.append((s["id"], round(sc, 2)))
    cands.sort(key=lambda x: -x[1])
    best = cands[0] if cands else (None, 0.0)
    return Match(best[0] if best[1] >= 0.80 else None, best[1], cands[:3], season, fmt, sport, cfg)

# ---------------------------------------------------------------- stockage
def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products_raw(
      shop TEXT, handle TEXT, title TEXT, variant_title TEXT, vendor TEXT, product_type TEXT,
      price REAL, compare_at REAL, available INTEGER, url TEXT,
      season TEXT, fmt TEXT, sport TEXT, config TEXT,
      sku_id TEXT, match_score REAL, candidates TEXT, seen_at TEXT,
      PRIMARY KEY(shop, handle, variant_title, seen_at));
    CREATE TABLE IF NOT EXISTS observations(
      sku_id TEXT, shop TEXT, title TEXT, variant_title TEXT, price REAL, available INTEGER,
      url TEXT, match_score REAL, seen_at TEXT,
      PRIMARY KEY(sku_id, shop, url, variant_title, seen_at));
    """)
    # migration douce : colonne matcher_version si absente
    cols = [r[1] for r in c.execute("PRAGMA table_info(observations)")]
    if "matcher_version" not in cols:
        c.execute("ALTER TABLE observations ADD COLUMN matcher_version TEXT")
    c.executescript("""
    CREATE INDEX IF NOT EXISTS ix_obs ON observations(sku_id, seen_at);
    """)
    return c

# ---------------------------------------------------------------- collecte Shopify
def shopify_by_collections(base: str, session: requests.Session) -> list[dict]:
    """Contourne le plafond de ~100 pages de /products.json : on liste les collections puis on pagine
    chacune. Dédoublonné par product id — un produit présent dans 3 collections ne compte qu'une fois."""
    seen, out = set(), []
    cols, page = [], 1
    while True:
        r = session.get(f"{base}/collections.json", params={"limit": 250, "page": page}, timeout=30)
        time.sleep(RATE_S)
        if r.status_code != 200: break
        items = r.json().get("collections", [])
        if not items: break
        cols.extend(items)
        if len(items) < 250: break
        page += 1
    for col in cols:
        handle = col.get("handle")
        if not handle: continue
        page = 1
        while True:
            r = session.get(f"{base}/collections/{handle}/products.json", params={"limit": 250, "page": page}, timeout=30)
            time.sleep(RATE_S)
            if r.status_code != 200: break
            items = r.json().get("products", [])
            if not items: break
            for p in items:
                if p.get("id") not in seen:
                    seen.add(p.get("id")); out.append(p)
            if len(items) < 250: break
            page += 1
    return out

def shopify_products(base: str, session: requests.Session) -> list[dict]:
    """Pagine /products.json?limit=250&page=N (fallback page_info non nécessaire en lecture publique
    sur la plupart des stores ; si vide dès la page 1, on tente /collections/all/products.json)."""
    out, page = [], 1
    for path in ("/products.json", "/collections/all/products.json"):
        page = 1
        while True:
            r = session.get(f"{base}{path}", params={"limit": 250, "page": page}, timeout=30)
            time.sleep(RATE_S)
            if r.status_code != 200: break
            items = r.json().get("products", [])
            if not items: break
            out.extend(items)
            if len(items) < 250: break
            page += 1
        if out: break
    return out

def collect_shop(shop: dict, skus: list[dict], conn: sqlite3.Connection, seen_at: str) -> tuple[int, int]:
    s = requests.Session(); s.headers["User-Agent"] = UA
    if shop.get("status") == "reject":
        print(f"  [{shop['key']}] status=reject (qualifié sur données réelles → 0 sealed 2023-24) → skip"); return (0, 0)
    if shop["type"] == "breaks":
        print(f"  [{shop['key']}] type=breaks (breaker, hors périmètre sealed) → skip"); return (0, 0)
    if shop["type"] != "shopify_json":
        print(f"  [{shop['key']}] type={shop['type']} non géré en v1 → skip"); return (0, 0)
    try:
        prods = (shopify_by_collections if shop.get("paginate") == "collections" else shopify_products)(shop["base_url"], s)
    except Exception as e:
        print(f"  [{shop['key']}] erreur collecte: {e}"); return (0, 0)
    n_raw = n_obs = 0
    for p in prods:
        title = p.get("title", ""); handle = p.get("handle", "")
        variants = p.get("variants") or []
        if not variants: continue
        url = f"{shop['base_url']}/products/{handle}"
        # Une ligne PAR VARIANTE : on matche titre + variant_title (garde-fou Blaster/Mega dans les variantes)
        for v in variants:
            vt = v.get("title") or ""
            vt_clean = "" if vt.lower() in ("default title", "default") else vt
            full = f"{title} {vt_clean}".strip()
            price = float(v.get("price") or 0); cmp_at = float(v.get("compare_at_price") or 0) or None
            available = 1 if v.get("available") else 0
            m = match_title(full, skus)
            conn.execute("INSERT OR REPLACE INTO products_raw VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (shop["key"], handle, full, vt_clean, p.get("vendor"), p.get("product_type"), price, cmp_at, available, url,
                 m.season, m.fmt, m.sport, m.config, m.sku_id, m.score, json.dumps(m.candidates), seen_at))
            n_raw += 1
            if m.sku_id:
                conn.execute("INSERT OR REPLACE INTO observations (sku_id,shop,title,variant_title,price,available,url,match_score,seen_at,matcher_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m.sku_id, shop["key"], full, vt_clean, price, available, url, m.score, seen_at, MATCHER_VERSION))
                n_obs += 1
    conn.commit()
    return (n_raw, n_obs)

# ---------------------------------------------------------------- décision / rapport
def money(v, cur="$"):
    """Un champ catalogue mal saisi (texte au lieu d'un nombre) doit dégrader la ligne, pas tuer le run."""
    try: return f"{cur}{float(v):.2f}"
    except (TypeError, ValueError): return "n/a"

def landed_eur(price_usd: float, cat: dict) -> float:
    lc = cat["landed_cost"]; fx = cat["fx_usd_eur"]
    usd = price_usd + lc["domestic_shipping_usd"] + lc["forwarder_fee_usd_per_box"] + lc["intl_shipping_usd_per_box"]
    eur = usd * fx
    eur += eur * lc["vat_rate"]
    eur += lc["customs_flat_eur_per_category"] * lc["customs_categories"] / float(lc.get("bundle_boxes", 8))
    return round(eur, 2)  # = coût rendu ESTIMÉ par boîte dans un panier de bundle_boxes boîtes

def prev_state(conn, sku_id, shop, url, vt, seen_at):
    """dispo au passage précédent (pour détecter un RESTOCK)."""
    r = conn.execute("""SELECT available FROM observations WHERE sku_id=? AND shop=? AND url=? AND variant_title=? AND seen_at<?
                        ORDER BY seen_at DESC LIMIT 1""", (sku_id, shop, url, vt, seen_at)).fetchone()
    return None if r is None else r[0]

def purge_stale(conn: sqlite3.Connection, skus: list[dict]):
    """Supprime des observations les lignes que le matching ACTUEL ne rattacherait plus (ex. Contenders Optic
    matché par une ancienne version). L'historique products_raw n'est pas touché."""
    rows = conn.execute("SELECT rowid, sku_id, title FROM observations").fetchall()
    bad = [r[0] for r in rows if match_title(r[2], skus).sku_id != r[1]]
    if bad:
        conn.executemany("DELETE FROM observations WHERE rowid=?", [(b,) for b in bad])
    conn.execute("UPDATE observations SET matcher_version=? WHERE matcher_version IS NULL", (MATCHER_VERSION,))  # re-validées par le matcher actuel
    conn.commit()
    return len(bad)

TRUST_FLAG = {"watch": "  👀 VERIFY", "high_risk": "  ⚠️ VERIFY SELLER"}

def trust_of(shop_key: str, trust: dict) -> str:
    """trusted par défaut : un shop sans clé `trust` dans sources.yaml reste classé normalement."""
    return trust.get(shop_key, "trusted")

def report(cat: dict, conn: sqlite3.Connection, seen_at: str | None, trust: dict | None = None):
    trust = trust or {}
    skus = {s["id"]: s for s in cat["skus"]}
    nb = cat["landed_cost"].get("bundle_boxes", 8)
    n_purged = purge_stale(conn, cat["skus"])
    if n_purged: print(f"(purge : {n_purged} observation(s) obsolètes retirées — matchées par une ancienne version du code)")
    # dernier passage RÉUSSI par shop (dernier seen_at où le shop a renvoyé au moins 1 produit brut)
    last_by_shop = dict(conn.execute("SELECT shop, MAX(seen_at) FROM products_raw GROUP BY shop").fetchall())
    # dernière observation par (sku, shop, url, variante)
    rows = conn.execute("""
      SELECT o.sku_id, o.shop, o.title, o.price, o.available, o.url, o.match_score, o.seen_at, o.variant_title
      FROM observations o
      JOIN (SELECT sku_id, shop, url, variant_title, MAX(seen_at) AS m FROM observations GROUP BY sku_id, shop, url, variant_title) l
        ON l.sku_id=o.sku_id AND l.shop=o.shop AND l.url=o.url AND l.variant_title=o.variant_title AND l.m=o.seen_at
      ORDER BY o.sku_id, o.available DESC, o.price ASC""").fetchall()
    by = {}; restocks = []; stale = []
    for r in rows:
        # une observation est LIVE seulement si elle date du dernier passage réussi de ce shop ;
        # sinon le produit a disparu du catalogue du shop → on la garde en mémoire (stale) mais pas dans le classement
        if r[7] != last_by_shop.get(r[1]):
            stale.append(r); continue
        by.setdefault(r[0], []).append(r)
        if r[4] == 1 and prev_state(conn, r[0], r[1], r[5], r[8], r[7]) == 0:
            deal = r[3] <= skus.get(r[0], {}).get("buy_below_usd", 0)
            restocks.append((r, deal))
    html = []  # lignes pour la page web
    OUT.mkdir(exist_ok=True)
    stamp = (seen_at or datetime.now(timezone.utc).isoformat())[:19].replace(":", "-")
    csv_path = OUT / f"deals_{stamp}.csv"
    if stale:
        print(f"({len(stale)} observation(s) 'stale' ignorées : produit plus présent au dernier passage du shop — historique conservé)")
    if restocks:
        print("\n" + "="*72 + "\n  🔔 RESTOCKS depuis le passage précédent\n" + "="*72)
        for r, deal in restocks:
            print(f"  {'🚨 RESTOCK DEAL' if deal else '🔔 RESTOCK'}  {r[0]}  {r[1]}  ${r[3]:.2f}  {r[5]}")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku_id","sku_status","licensed","tier","shop","trust","title","variant","price_usd","boxes_per_case","unit_price_per_box","in_stock",f"landed_eur_est_{nb}box_bundle","market_ask_us","market_sold_us","market_sold_source","market_sold_checked_at","buy_below","watch_below","eu_ref_eur","status","restock","url","seen_at","match_score"])
        for tier in ("retail", "hobby"):
            print("\n" + "="*72 + f"\n  {tier.upper()}\n" + "="*72)
            for sid, s in skus.items():
                if s.get("tier","retail") != tier: continue
                obs = by.get(sid, [])
                in_stock = [o for o in obs if o[4]]
                # high_risk : observé et affiché, mais jamais retenu comme BEST → ne peut pas déclencher un GO
                best = next((o for o in in_stock if trust_of(o[1], trust) != "high_risk"), None)
                # status du SKU : le matching tourne sur TOUS les statuts, la classification GO/NO_GO
                # ne concerne que les ACTIVE. WATCH/CANDIDATE sont observés, jamais recommandés à l'achat.
                sk_st = s.get("status", "ACTIVE")
                if sk_st != "ACTIVE":
                    status, icon = ("SUIVI" if sk_st == "WATCH" else "CANDIDAT"), "·"
                elif best and s.get("buy_below_usd") and best[3] <= s["buy_below_usd"]: status, icon = "GO", "🔥"
                elif best and s.get("watch_below_usd") and best[3] <= s["watch_below_usd"]: status, icon = "WATCH", "👀"
                elif best: status, icon = "NO_GO", "⛔"
                else: status, icon = ("NO_STOCK" if obs else "NO_DATA"), "—"
                lic = "" if s.get("licensed", True) else "  ⚑ unlicensed"
                bpc = s.get("boxes_per_case")
                cfgl = f" ({s['configuration']})" if s.get("configuration") else ""
                print(f"\n{icon} {status}   {s['season']} {s['manufacturer']} {s['set']} {s['format']}{cfgl}   [{sid}]{lic}")
                rs = {id(r[0]) for r in restocks}
                for i, o in enumerate(obs[:6], 1):
                    stock = "IN STOCK" if o[4] else "SOLD OUT"
                    flag = "  🔔" if any(o is r for r,_ in restocks) else ""
                    unit = f"  = ${o[3]/bpc:>7.2f}/boîte" if bpc else ""
                    print(f"   {i}. {o[1]:<16} ${o[3]:>8.2f}{unit}  {stock:<9} landed≈€{landed_eur(o[3]/bpc if bpc else o[3],cat):>7.2f} ({nb}-box bundle)  (score {o[6]:.2f}){flag}{TRUST_FLAG.get(trust_of(o[1], trust), '')}")
                ask = s.get("market_ask_us"); sold = s.get("market_sold_us"); eu = s.get("eu_reference_eur")
                ssrc = s.get("market_sold_source"); schk = s.get("market_sold_checked_at")
                prov = f" [{ssrc}{' ' + str(schk) if schk else ''}]" if sold and ssrc else ""
                print(f"   ask {money(ask):<8} sold {money(sold):<8}{prov} | buy ≤ {money(s.get('buy_below_usd')):<8} | watch ≤ {money(s.get('watch_below_usd')):<8} | EU {money(eu, '€')}")
                if best: print(f"   BEST → {best[1]}  {best[5]}")
                html.append((tier, status, icon, s, obs, best))
                for o in obs:
                    w.writerow([sid, sk_st, s.get("licensed", True), tier, o[1], trust_of(o[1], trust), o[2], o[8], o[3], bpc or "", round(o[3]/bpc, 2) if bpc else "", o[4], landed_eur(o[3]/bpc if bpc else o[3],cat), ask, sold, ssrc, schk, s.get("buy_below_usd"), s.get("watch_below_usd"), eu, status if o is best else "", 1 if any(o is r for r,_ in restocks) else 0, o[5], o[7], o[6]])
    # REVIEW : bruts basket 2023-24 non matchés (score entre 0.4 et 0.8) — dernier crawl seulement
    print("\n" + "="*72 + "\n  ⚠️  REVIEW (basketball 2023-24, non rattachés)\n" + "="*72)
    q = conn.execute("""SELECT shop,title,price,available,candidates,match_score,url FROM products_raw
        WHERE sku_id IS NULL AND sport!='other' AND (season='2023-24' OR season IS NULL) AND match_score>=0.60
        AND seen_at=(SELECT MAX(seen_at) FROM products_raw) ORDER BY match_score DESC LIMIT 40""").fetchall()
    for shop,title,price,av,cands,sc,url in q:
        print(f"  [{shop}] {title}  ${price:.2f} {'IN' if av else 'OOS'}  → {cands}")
    write_html(cat, html, restocks, q, seen_at, trust)
    print(f"\nCSV → {csv_path}\nHTML → {OUT/'index.html'}")

def write_html(cat, blocks, restocks, review, seen_at, trust=None):
    trust = trust or {}
    nb = cat["landed_cost"].get("bundle_boxes", 8)
    col = {"GO":"#1b7f3b","WATCH":"#b8860b","NO_GO":"#b22222","NO_STOCK":"#666","NO_DATA":"#999","SUIVI":"#4a5568","CANDIDAT":"#8a8a8a"}
    h = [f"<!doctype html><meta charset='utf-8'><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>Wemby Hunt</title><style>body{{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;padding:0 12px;color:#222}}"
         f".sku{{border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0}}.st{{font-weight:bold;color:#fff;padding:2px 8px;border-radius:4px}}"
         f"table{{width:100%;border-collapse:collapse}}td,th{{padding:4px 6px;border-bottom:1px solid #eee;text-align:left;font-size:14px}}"
         f".oos{{color:#999}}.small{{color:#666;font-size:12px}}h2{{margin-top:28px}}</style>"
         f"<h1>Wemby Hunt — 2023-24 sealed</h1><p class=small>Dernier passage : {seen_at or ''} UTC. landed = coût rendu France ESTIMÉ par boîte dans un panier de {nb} boîtes (hypothèses catalog.yaml).</p>"]
    if restocks:
        h.append("<h2>🔔 Restocks</h2><ul>")
        for r, deal in restocks:
            h.append(f"<li>{'🚨 DEAL ' if deal else ''}<b>{r[0]}</b> — {r[1]} — ${r[3]:.2f} — <a href='{r[5]}'>lien</a></li>")
        h.append("</ul>")
    for tier in ("retail","hobby"):
        h.append(f"<h2>{tier.upper()}</h2>")
        for t, status, icon, s, obs, best in blocks:
            if t != tier: continue
            ask=s.get("market_ask_us"); sold=s.get("market_sold_us"); eu=s.get("eu_reference_eur")
            h.append(f"<div class=sku><span class=st style='background:{col[status]}'>{icon} {status}</span> <b>{s['season']} {s['manufacturer']} {s['set']} {s['format']}</b>"
                     f"<div class=small>ask {ask or 'n/a'} $ · sold {sold or 'n/a'} $ · buy ≤ {s.get('buy_below_usd') or 'n/a'} $ · watch ≤ {s.get('watch_below_usd') or 'n/a'} $ · EU {eu or 'n/a'} €{'' if s.get('licensed', True) else ' · ⚑ unlicensed'}</div>")
            if obs:
                h.append("<table><tr><th>Shop</th><th>Produit (titre live)</th><th>Configuration</th><th>Prix</th><th>Stock</th><th>Landed €</th></tr>")
                seen=set()
                for o in obs:
                    key=(o[1],o[5],o[8],round(o[3],2),o[4])   # shop, url, variante, prix, stock — deux configs restent deux lignes
                    if key in seen: continue
                    seen.add(key)
                    if len(seen)>12: break
                    cls = "" if o[4] else " class=oos"
                    cfg = parse_config(norm(o[2])) or "—"
                    tv = trust_of(o[1], trust)
                    badge = {"watch": " <span class=small>👀 VERIFY</span>",
                             "high_risk": " <span class=small>⚠️ VERIFY SELLER</span>"}.get(tv, "")
                    h.append(f"<tr{cls}><td>{o[1]}{badge}</td><td><a href='{o[5]}'>{o[2]}</a></td><td class=small>{cfg}</td><td>${o[3]:.2f}</td><td>{'IN STOCK' if o[4] else 'sold out'}</td><td>€{landed_eur(o[3],cat):.2f}</td></tr>")
                h.append("</table>")
            h.append("</div>")
    if review:
        h.append("<h2>⚠️ À revoir (non rattachés)</h2><table><tr><th>Shop</th><th>Titre</th><th>Prix</th><th>Stock</th><th>Candidats</th></tr>")
        for shop,title,price,av,cands,sc,url in review:
            h.append(f"<tr><td>{shop}</td><td><a href='{url}'>{title}</a></td><td>${price:.2f}</td><td>{'IN' if av else 'OOS'}</td><td class=small>{cands}</td></tr>")
        h.append("</table>")
    (OUT/"index.html").write_text("\n".join(h), encoding="utf-8")

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop"); ap.add_argument("--report", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--diag", metavar="SHOP", help="affiche des titres bruts basket/2023-24 d'un shop pour comprendre un 0 rattaché")
    a = ap.parse_args()
    cat = yaml.safe_load((ROOT/"catalog.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT/"sources.yaml").read_text(encoding="utf-8"))
    skus = cat["skus"]
    if a.dry_run:
        tests = ["2023/24 Panini Phoenix Basketball 6-pack Blaster Box","2023-24 Panini Phoenix NBA NPP Blaster Box",
          "23-24 Phoenix Bball Blaster","Phoenix Basketball Box","2023-24 Panini Donruss Optic Basketball Mega Box (Hyper Pink Prizms)",
          "2023/24 Panini Donruss Optic Basketball 6-Pack Blaster Box (Glitter Parallels)","2023/24 Panini Premium Stock Basketball Blaster Box",
          "2023/24 Panini NBA Hoops Premium Stock Basketball Mega Box","2024-25 Panini Phoenix Basketball Blaster Box",
          "2023 Panini Phoenix Football Blaster Box","2023-24 Panini Select Basketball Mega Box (Green Shock Prizm)",
          "23-24 Select Basketball Box","2023-24 Panini Prizm Basketball Blaster Box (Ice Prizms!)","2023-24 Panini Prizm Monopoly Basketball Blaster",
          "2023-24 Panini Revolution Basketball Hobby Box","2023-24 Panini Donruss Optic Basketball 6-Pack Hobby Blaster Box (Shimmer Parallels)"]
        for t in tests:
            m = match_title(t, skus)
            print(f"{m.score:>4.2f} {str(m.sku_id):<40} <- {t}   [season={m.season} fmt={m.fmt} sport={m.sport} cfg={m.config}]")
        return
    conn = db()
    if a.diag:
        rows = conn.execute("""SELECT title, price, available, season, fmt, sport, match_score FROM products_raw
            WHERE shop=? AND seen_at=(SELECT MAX(seen_at) FROM products_raw WHERE shop=?)
            AND (title LIKE '%2023%' OR title LIKE '%23-24%' OR title LIKE '%23/24%' OR title LIKE '%Wemb%')
            ORDER BY match_score DESC, price DESC LIMIT 60""", (a.diag, a.diag)).fetchall()
        tot = conn.execute("SELECT COUNT(*), SUM(CASE WHEN sport='basketball' THEN 1 ELSE 0 END), SUM(CASE WHEN fmt IS NOT NULL THEN 1 ELSE 0 END) FROM products_raw WHERE shop=? AND seen_at=(SELECT MAX(seen_at) FROM products_raw WHERE shop=?)", (a.diag, a.diag)).fetchone()
        print(f"[{a.diag}] {tot[0]} bruts | {tot[1]} détectés basket | {tot[2]} avec un format sealed détecté")
        for t in rows: print(f"  {t[6]:.2f} {str(t[3]):<8} {str(t[4]):<12} {t[5]:<10} ${t[1]:>8.2f} {'IN ' if t[2] else 'OOS'}  {t[0][:90]}")
        return
    trust = {sh["key"]: sh.get("trust", "trusted") for sh in src["shops"]}
    if not a.report:
        seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        shops = [s for s in src["shops"] if not a.shop or s["key"] == a.shop]
        for sh in shops:
            print(f"→ {sh['name']} ({sh['base_url']})  [trust={sh.get('trust','trusted')}]")
            n_raw, n_obs = collect_shop(sh, skus, conn, seen_at)
            print(f"  {n_raw} produits bruts, {n_obs} rattachés à un SKU")
        report(cat, conn, seen_at, trust)
    else:
        report(cat, conn, None, trust)

if __name__ == "__main__":
    main()
