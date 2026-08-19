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
SHOP_COUNTS = []  # (key, trust, bruts, matchés) — rempli par main(), rendu en bas de page

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
    ("FOTL", r"(first|1st)\s*off\s*the\s*line|\bfotl\b"),
    ("Fast Break", r"fast\s*break|fast\s*brk"),
    ("Choice", r"\bchoice\b"),
    ("H2", r"\bh2\b|hybrid"),
    ("Tin", r"\btin\b"),
    ("Chinese New Year", r"chinese\s*new\s*year|\bcny\b|lunar"),
    ("International", r"\binternational\b|\bintl\b|\basia\b|\btmall\b"),
    ("Breakers Delight", r"breaker'?s?\s*delight"),
    ("Hobby Jumbo", r"\bjumbo\b"),
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

# Une ligue non-NBA est une identité produit à part entière : le Prizm EuroLeague n'est pas un
# Prizm NBA moins cher, c'est un autre produit. Un SKU sans `league` refuse les titres de ligue,
# et un SKU avec `league` n'accepte QUE cette ligue.
LEAGUES = [("EuroLeague", r"euro\s*league|turkish\s*airlines")]
LEAGUE_STRIP = re.compile(r"euro\s*league|turkish\s*airlines")

def parse_league(t: str) -> str | None:
    for name, rx in LEAGUES:
        if re.search(rx, t): return name
    return None

def parse_exclusive(t: str) -> str | None:
    for name, rx in EXCLUSIVES:
        if re.search(rx, t): return name
    return None
SEASON_RE = re.compile(r"(20\d{2})\s*[-/–]\s*(\d{2,4})|(?<!\d)(\d{2})\s*[-/–]\s*(\d{2})(?!\d)")
SPORT_HINTS = {"basketball": ["basketball", "nba", "bball", "hoops"], "not_basketball": ["football", "nfl", "baseball", "mlb", "hockey", "nhl", "soccer", "wnba", "pokemon", "ufc", "wrestling", "f1", "euroleague", "golf", "nascar", "racing", "wwe", "tennis", "mma", "boxing", "pfl", "fighters", "college", "draft picks", "world cup", "premier league"]}
SEALED_RE = re.compile(r"\b(box|boxes|blaster|mega|hobby|case|pack|packs|tin|display|bundle|lot)\b")
SINGLE_RE = re.compile(r"(#\s*\d+\b|\b\d{1,3}\s*/\s*\d{1,4}\b|\bpsa\b|\bbgs\b|\bsgc\b|\bauto\b|\bautograph\b|\brc\b\s*$|\bpatch\b|\brelic\b|\bslab)")
# Parallèles nommés : une "Green Shock" ou une "Hyper Pink" n'est pas la boîte standard.
# Un SKU sans configuration qui capte un titre porteur d'un parallèle nommé donne une
# comparaison RELATED — observée, jamais convertie en GO.
PARALLEL_HINTS = ["green shock", "cracked ice", "red ice", "blue ice", "green ice", "hyper pink",
                  "hyper orange", "hyper green", "ice prizm", "velocity", "shimmer", "pulsar",
                  "disco", "seismic", "glitter", "flash", "reactive", "fluorescent", "purple shock"]

# ---------------------------------------------------------------- G : sealed gate (P0)
# Aucune blacklist de joueurs : on s'appuie sur des caractéristiques STRUCTURELLES.
# Un produit scellé nomme son contenant (box, case, tin, display, blaster, mega, hanger, pack).
# Une carte à l'unité porte un identifiant de carte : code d'insert (HS-3, #AN-KAT), numérotation
# (12/99), ou une note de grading. "Hobby Stars" contient "hobby" mais n'est pas une boîte.
CONTAINER_RE = re.compile(r"\b(box|boxes|case|tin|display|bundle|lot|blaster|mega|hanger|packs?)\b")
# un "#" suivi d'un code d'insert est le marqueur le plus fiable d'une carte à l'unité :
# #339, #HS-3, #AN-KAT, #PM-TJD, #RGBR — lettres et/ou chiffres, avec ou sans tiret.
CARD_ID_RE = re.compile(r"#\s*[a-z0-9]{1,8}(?:-[a-z0-9]{1,8})?\b"
                        r"|\b[a-z]{2,3}-\d{1,3}\b|\b\d{1,3}\s*/\s*\d{1,4}\b")
GRADE_RE = re.compile(r"\b(psa|bgs|sgc|cgc)\s*\d(\.\d)?\b|\bgem\s*mt\b")

def sealed_product(t: str) -> bool | None:
    """True = scellé · False = carte à l'unité · None = indécidable (-> REVIEW, jamais décisionnel)."""
    single = bool(CARD_ID_RE.search(t) or GRADE_RE.search(t))
    container = bool(CONTAINER_RE.search(t))
    if single and container: return None      # "lot de 3 cartes #12" : ambigu
    if single: return False
    return container or None

# ---------------------------------------------------------------- H/I : EXACT_COMP et quantité
# Jetons de configuration : un titre qui en porte un ne peut matcher QU'UN SKU qui le déclare,
# et réciproquement. Vaut pour toutes les familles, pas seulement Topps.
EDITION_TOKENS = ("sapphire", "monster", "first day", "cactus jack", "china", "gravity feed")

QTY_RE = re.compile(r"(\d{1,3})\s*-?\s*box\b")
LOT_RE = re.compile(r"\blot\b|\bbundle\b|\bcase\b|gravity\s*feed|\bdisplay\b")

def parse_quantity(t: str, sku: dict | None = None) -> int:
    """Nombre de boîtes derrière un prix. '6-box lot' -> 6. 'case' sans nombre -> boxes_per_case
    du SKU si connu. Défaut 1. Le prix affiché reste le TOTAL : l'unitaire en est dérivé, jamais
    l'inverse — on ne doit ni annoncer une boîte à 300 $ ni un lot entier à 50 $."""
    m = QTY_RE.search(t)
    if m:
        n = int(m.group(1))
        if 1 < n <= 200: return n
    if LOT_RE.search(t) and sku and sku.get("boxes_per_case"):
        return int(sku["boxes_per_case"])
    return 1

def exact_comp_key(sku_id: str, t: str, sku: dict | None = None) -> str:
    """Cloison de comparabilité commerciale. SOLD, LIVE MARKET, cheapest, historique et signaux
    ne doivent JAMAIS traverser cette clé. Deux offres de clés différentes ne se comparent pas."""
    qty = parse_quantity(t, sku)
    ed = "+".join(tok.replace(" ", "") for tok in EDITION_TOKENS if tok in t) or "std"
    return f"{sku_id}|{ed}|x{qty}"

def comp_type_of(title_norm: str, sku: dict) -> str:
    """EXACT = même configuration que le SKU. RELATED = même SKU, autre configuration reconnue."""
    if sku.get("configuration"): return "EXACT"
    return "RELATED" if any(h in title_norm for h in PARALLEL_HINTS) else "EXACT"

CONFIG_HINTS = ["target", "walmart", "fanatics", "exclusive", "green shock", "cracked ice", "red ice", "blue ice", "green ice", "hyper pink", "hyper orange", "glitter", "flash", "ice prizm", "seismic", "npp", "reactive", "fluorescent", "shimmer", "pulsar", "disco", "holo", "purple", "pink", "orange", "yellow", "green", "blue", "red"]

def norm(s: str) -> str:
    # dé-collage AVANT le passage en minuscules : "BasketballMega" -> "Basketball Mega".
    # Des titres de shops collent deux mots et le format devenait indétectable.
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
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
    # Le dé-collage de norm() coupe les mots collés : "EuroLeague" -> "euro league". Un mot-clé
    # d'exclusion écrit en CamelCase par le shop cessait donc d'être reconnu — un blaster
    # EuroLeague à 14,75 $ est ressorti en 🔥 GO sur le SKU Prizm NBA le 18/08.
    # On teste aussi la forme sans espaces. Le garde len>4 évite qu'un token court (f1, mma,
    # pfl, nfl) ne matche accidentellement à l'intérieur d'un autre mot.
    tight = t.replace(" ", "")
    def has(k): return k in t or (len(k) > 4 and k.replace(" ", "") in tight)
    if any(has(k) for k in SPORT_HINTS["not_basketball"]): return "other"
    if any(has(k) for k in SPORT_HINTS["basketball"]): return "basketball"
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
    league = parse_league(t)
    # pour un SKU de ligue, le sport se juge sur le titre débarrassé des tokens de ligue :
    # sinon "euroleague" (exclusion sport) rejetterait son propre SKU.
    sport_noleague = parse_sport(LEAGUE_STRIP.sub(" ", t)) if league else sport
    cands = []
    # likely_single : signaux forts de carte individuelle SANS signal sealed → ignoré (pas même en REVIEW).
    # Un titre sans "Box" mais sans signal single (ex. "2023-24 Panini Phoenix Basketball") reste candidat → REVIEW.
    # G : sealed gate. Un non-scellé ne peut alimenter aucune décision marché.
    sealed = sealed_product(t)
    if sealed is False:
        return Match(None, 0.0, [], season, fmt, sport, cfg)
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
            # le garde-fou anti-"Ice Prizms" exige "Panini Prizm" ou "Prizm Basketball". Un SKU de
            # ligue est déjà identifié par son token de ligue : "Prizm Turkish Airlines EuroLeague"
            # suffit, inutile d'exiger en plus "Panini" ou "Basketball".
            if not (re.search(r"(panini\s+prizm|prizm\s+(basketball|nba|bball))", t)
                    or (s.get("league") and league == s.get("league"))): continue
        if s["set"].lower() == "donruss optic" and ("optic" not in t or "contenders" in t or "recon" in t): continue
        if s["set"].lower() == "contenders" and "optic" in t: continue   # "Contenders Optic" est une autre gamme
        if s["set"].lower() == "select" and ("select racing" in t or "nascar" in t): continue
        # Éditions spéciales : Sapphire, Monster, First Day Issue, Cactus Jack sont des identités
        # à part dans TOUTES les familles Topps/Bowman. Titre et SKU doivent concorder, sinon un
        # "Bowman Sapphire Hobby Box" à 2 500 $ finit sur le Hobby standard (constaté le 20/08).
        ident_ed = (s["id"] + " " + (s.get("configuration") or "") + " "
                    + (s.get("configuration_note") or "")).lower()
        if any((tok in t) != (tok in ident_ed) for tok in EDITION_TOKENS): continue
        if s["set"].lower() == "bowman":
            # la famille Bowman Basketball ne couvre PAS les sous-gammes universitaires ni les
            # déclinaisons Chrome/Best/1st Edition, qui sont d'autres produits.
            if any(k in t for k in ("bowman u ", "bowman university", "1st edition", "first edition",
                                    "bowman best", "bowman chrome", "u chrome")): continue
            # Sapphire / Monster sont des éditions distinctes ici aussi : un "Bowman Sapphire
            # Hobby Box" à 2 500 $ était absorbé par le Hobby standard (constaté le 20/08).
        if s["set"].lower() in ("topps chrome", "cosmic chrome", "topps chrome update"):
            # Update est une gamme distincte de Chrome, dans les deux sens.
            if ("update" in t) != ("update" in s["set"].lower()): continue
            # collaborations et éditions spéciales : identités séparées, pas du Chrome standard
            # gammes voisines qui ne sont PAS du Topps Chrome NBA
            if any(k in t for k in ("nbl", "australia", "overtime elite", "\bote\b", "bowman",
                                    "g-league", "g league", "breaker", "uefa")): continue
            # Cosmic est une gamme distincte de Chrome, dans les deux sens
            if ("cosmic" in t) != (s["set"].lower() == "cosmic chrome"): continue
            # Sapphire et Monster sont des configurations distinctes : le titre et le SKU doivent
            # être d'accord, sinon une Sapphire à 400 $ nourrirait le Chrome Hobby standard.
        # FOTL / International (asia, tmall) sont désormais des FORMATS détectés : le garde-fou "mauvais format
        # = éliminé" suffit, comme pour Hanger. Ne restent ici que les sous-gammes sans format dédié.
        if any(k in t for k in ("cello", "multi-pack", "value pack")): continue
        # exclusivité retailer : Target/Fanatics ne peut matcher qu'un SKU portant cette configuration,
        # et un SKU d'exclusivité ne peut pas absorber un titre standard. Sinon → pas de candidat → REVIEW.
        sku_league = s.get("league")
        if bool(sku_league) != bool(league) or (sku_league and sku_league != league): continue
        eff_sport = sport_noleague if sku_league else sport
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
        if eff_sport == "basketball": sc += 0.05
        elif eff_sport == "other": continue
        if s["manufacturer"].lower() in t: sc = min(1.0, sc + 0.02)
        cands.append((s["id"], round(sc, 2)))
    # sealed indécidable : plafonné sous le seuil de rattachement -> REVIEW, jamais décisionnel
    if sealed is None:
        cands = [(i, min(sc, 0.75)) for i, sc in cands]
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
    c.executescript("""
    CREATE TABLE IF NOT EXISTS signals(
      sku TEXT, shop TEXT, url TEXT, variant_title TEXT, price REAL,
      badges TEXT, reference REAL, reference_kind TEXT, gap_pct REAL, seen_at TEXT,
      PRIMARY KEY(sku, shop, url, variant_title, seen_at));
    CREATE TABLE IF NOT EXISTS crawl_runs(
      shop TEXT, seen_at TEXT, partial INTEGER, n_raw INTEGER,
      PRIMARY KEY(shop, seen_at));
    """)
    # migration douce : colonne matcher_version si absente
    cr = [r[1] for r in c.execute("PRAGMA table_info(crawl_runs)")]
    for col in ("duration_s REAL", "reason TEXT"):
        if col.split()[0] not in cr:
            c.execute(f"ALTER TABLE crawl_runs ADD COLUMN {col}")
    cols = [r[1] for r in c.execute("PRAGMA table_info(observations)")]
    for col in ("matcher_version TEXT", "image_url TEXT", "comp_type TEXT",
                "quantity INTEGER", "unit_price REAL", "exact_comp_key TEXT", "sealed INTEGER"):
        if col.split()[0] not in cols:
            c.execute(f"ALTER TABLE observations ADD COLUMN {col}")
    c.executescript("""
    CREATE INDEX IF NOT EXISTS ix_obs ON observations(sku_id, seen_at);
    """)
    return c

# ---------------------------------------------------------------- collecte Shopify
SLOW_CRAWL_S = 300      # 5 min : avertissement, le crawl continue
HARD_TIMEOUT_S = 480    # 8 min : ce shop est interrompu proprement, le run global continue

class ShopTimeout(Exception):
    """Levée par fetch_json quand le budget temps du shop est épuisé. Interrompt CE shop,
    jamais le run : les données déjà collectées deviennent un passage PARTIAL/TIMEOUT."""

RETRIES = 3
BACKOFF = (2, 5)   # secondes entre tentatives

def fetch_json(session, url, params, label, deadline=None):
    """Retourne (data, ok). ok=False après RETRIES tentatives non-200 ou en erreur réseau.
    L'appelant décide alors si la pagination est PARTIELLE (des produits déjà collectés) ou
    simplement terminée. Sans ça, une erreur passagère tronque un shop en silence — vécu le
    18/08 : awesome tombé de 7 266 à 2 000 produits et de 40 matchs à 1, run vert."""
    last = None
    for i in range(RETRIES):
        if deadline and time.monotonic() > deadline:
            raise ShopTimeout(label)
        try:
            r = session.get(url, params=params, timeout=30)
            time.sleep(RATE_S)
            if r.status_code == 200:
                return r.json(), True
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = e.__class__.__name__
        if i < RETRIES - 1:
            time.sleep(BACKOFF[i])
    print(f"    ⚠️  {label} : {RETRIES} tentatives en échec ({last})")
    return None, False

def shopify_by_collections(base: str, session: requests.Session, only: str | None = None, deadline=None) -> tuple[list[dict], bool]:
    """Contourne le plafond de ~100 pages de /products.json : on liste les collections puis on pagine
    chacune. Dédoublonné par product id — un produit présent dans 3 collections ne compte qu'une fois.
    `only` = regex sur handle+titre pour ne garder que les collections utiles (ex. basket) et tenir le budget temps."""
    seen, out, partial = set(), [], False
    cols, page = [], 1
    while True:
        data, ok = fetch_json(session, f"{base}/collections.json", {"limit": 250, "page": page},
                              f"collections.json page {page}", deadline)
        if not ok:
            partial = bool(cols); break
        items = data.get("collections", [])
        if not items: break
        cols.extend(items)
        if len(items) < 250: break
        page += 1
    if only:
        rx = re.compile(only, re.I)
        kept = [c for c in cols if rx.search(f"{c.get('handle','')} {c.get('title','')}")]
        if kept:
            print(f"    collections : {len(kept)}/{len(cols)} retenues (filtre {only!r})")
            cols = kept
        else:
            # aucune collection basket : le shop n'expose pas /collections.json, ou nomme ses collections
            # autrement. On ne rate PAS le shop — retour à la pagination complète, et c'est écrit noir sur blanc.
            print(f"    ⚠️  FALLBACK pagination complète : 0/{len(cols)} collection ne matche {only!r}")
            prods, p2 = shopify_products(base, session, deadline)
            return prods, (partial or p2)
    for col in cols:
        handle = col.get("handle")
        if not handle: continue
        page = 1
        while True:
            data, ok = fetch_json(session, f"{base}/collections/{handle}/products.json",
                                  {"limit": 250, "page": page}, f"{handle} page {page}", deadline)
            if not ok:
                partial = True; break
            items = data.get("products", [])
            if not items: break
            for p in items:
                if p.get("id") not in seen:
                    seen.add(p.get("id")); out.append(p)
            if len(items) < 250: break
            page += 1
    return out, partial

def shopify_products(base: str, session: requests.Session, deadline=None) -> tuple[list[dict], bool]:
    """Pagine /products.json?limit=250&page=N (fallback page_info non nécessaire en lecture publique
    sur la plupart des stores ; si vide dès la page 1, on tente /collections/all/products.json)."""
    out, partial = [], False
    for path in ("/products.json", "/collections/all/products.json"):
        out, partial, page = [], False, 1
        while True:
            data, ok = fetch_json(session, f"{base}{path}", {"limit": 250, "page": page},
                                  f"{path} page {page}", deadline)
            if not ok:
                partial = bool(out)   # des produits déjà collectés → catalogue TRONQUÉ, pas terminé
                break
            items = data.get("products", [])
            if not items: break
            out.extend(items)
            if len(items) < 250: break
            page += 1
        if out: break
    return out, partial

def collect_shop(shop: dict, skus: list[dict], conn: sqlite3.Connection, seen_at: str) -> tuple[int, int, bool]:
    s = requests.Session(); s.headers["User-Agent"] = UA
    def skip(msg, why):
        print(f"  [{shop['key']}] {msg}")
        conn.execute("INSERT OR REPLACE INTO crawl_runs VALUES (?,?,?,?,?,?)",
                     (shop["key"], seen_at, 0, 0, 0.0, f"SKIPPED:{why}")); conn.commit()
        return (0, 0, False)
    if shop.get("status") == "reject":
        return skip(f"status=reject \(qualifié sur données réelles → 0 sealed 2023-24\) → skip", "REJECT")
    if shop["type"] == "marketplace":
        return skip(f"type=marketplace \(source de market_sold / achat direct\) → skip", "MARKETPLACE")
    if shop["type"] == "breaks":
        return skip(f"type=breaks \(breaker, hors périmètre sealed\) → skip", "BREAKS")
    if shop["type"] != "shopify_json":
        return skip(f"type={shop['type']} non géré en v1 → skip", "UNSUPPORTED_TYPE")
    t0 = time.monotonic()
    deadline = t0 + HARD_TIMEOUT_S
    reason = None
    try:
        if shop.get("paginate") == "collections":
            prods, partial = shopify_by_collections(shop["base_url"], s, shop.get("collections_match"), deadline)
        else:
            prods, partial = shopify_products(shop["base_url"], s, deadline)
    except ShopTimeout as e:
        # budget épuisé : ce shop s'arrête, le run global continue. Tout ce qui a été collecté
        # avant l'interruption est PARTIAL et ne deviendra jamais un passage de référence.
        dur = time.monotonic() - t0
        print(f"  [{shop['key']}] ⏱ HARD TIMEOUT après {dur/60:.1f} min sur {e} → PARTIAL/TIMEOUT")
        conn.execute("INSERT OR REPLACE INTO crawl_runs VALUES (?,?,?,?,?,?)",
                     (shop["key"], seen_at, 1, 0, dur, "TIMEOUT")); conn.commit()
        return (0, 0, True)
    except Exception as e:
        dur = time.monotonic() - t0
        print(f"  [{shop['key']}] erreur collecte: {e}")
        conn.execute("INSERT OR REPLACE INTO crawl_runs VALUES (?,?,?,?,?,?)",
                     (shop["key"], seen_at, 1, 0, dur, f"ERROR:{e.__class__.__name__}")); conn.commit()
        return (0, 0, True)
    n_raw = n_obs = 0
    for p in prods:
        title = p.get("title", ""); handle = p.get("handle", "")
        variants = p.get("variants") or []
        if not variants: continue
        url = f"{shop['base_url']}/products/{handle}"
        imgs = p.get("images") or []
        image_url = (imgs[0].get("src") if imgs else None)
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
                sku_obj = next((x for x in skus if x["id"] == m.sku_id), {})
                tn = norm(full)
                ct = comp_type_of(tn, sku_obj)
                qty = parse_quantity(tn, sku_obj)
                # le prix collecté est TOUJOURS le total de l'offre ; l'unitaire en dérive
                unit = round(price / qty, 2) if qty else price
                conn.execute("INSERT OR REPLACE INTO observations (sku_id,shop,title,variant_title,price,available,url,match_score,seen_at,matcher_version,image_url,comp_type,quantity,unit_price,exact_comp_key,sealed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m.sku_id, shop["key"], full, vt_clean, price, available, url, m.score, seen_at,
                     MATCHER_VERSION, image_url, ct, qty, unit, exact_comp_key(m.sku_id, tn, sku_obj),
                     1 if sealed_product(tn) else 0))
                n_obs += 1
    dur = time.monotonic() - t0
    if dur > SLOW_CRAWL_S:
        reason = "SLOW_CRAWL"
        print(f"  [{shop['key']}] ⚠️ SLOW_CRAWL : {dur/60:.1f} min (> {SLOW_CRAWL_S//60} min)")
    if partial and not reason: reason = "PAGINATION_INCOMPLETE"
    conn.execute("INSERT OR REPLACE INTO crawl_runs VALUES (?,?,?,?,?,?)",
                 (shop["key"], seen_at, 1 if partial else 0, n_raw, dur, reason))
    conn.commit()
    return (n_raw, n_obs, partial)

# ---------------------------------------------------------------- décision / rapport
def sku_label(s: dict) -> str:
    """Libellé humain d'un SKU. Doit inclure league et configuration : sans elles, le Prizm
    EuroLeague s'affichait '2023-24 Panini Prizm Blaster', identique au Prizm NBA — trompeur
    sur une ligne GO."""
    bits = [s["season"], s["manufacturer"], s["set"]]
    if s.get("league"): bits.append(s["league"])
    bits.append(s["format"])
    if s.get("configuration"): bits.append(f"({s['configuration']})")
    return " ".join(str(b) for b in bits)

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


# ================================================================ V2-a : mémoire et badges
def sold_confidence(sku: dict) -> str | None:
    """Dérivée, jamais saisie. HIGH n>=5 et <=60 j · MEDIUM n>=2 et <=90 j · LOW sinon.
    None = aucune vente réalisée renseignée."""
    if sku.get("market_sold_us") is None: return None
    n = sku.get("market_sold_n") or 0
    w = sku.get("market_sold_window_days")
    if n >= 5 and w is not None and w <= 60: return "HIGH"
    if n >= 2 and w is not None and w <= 90: return "MEDIUM"
    return "LOW"

def market_ref(sku: dict) -> tuple[float | None, str | None]:
    """Référence de marché : sold si présent, sinon ask. Aucune des deux -> pas de référence."""
    if sku.get("market_sold_us") is not None: return float(sku["market_sold_us"]), "sold"
    # un ask sans provenance n'est pas une référence : on ne sait pas d'où il vient, donc on ne
    # peut ni juger l'auto-sourçage ni le dater. Traité comme absent.
    if sku.get("market_ask_us") is not None and (sku.get("market_ask_from") or []):
        return float(sku["market_ask_us"]), "ask"
    return None, None

def backfill_comp(conn, skus):
    """Les observations antérieures à H/I n'ont ni exact_comp_key ni sealed. On les recalcule une
    fois, sinon l'historique repartirait de zéro. Migration idempotente."""
    smap = {x["id"]: x for x in skus}
    todo = conn.execute("SELECT rowid, sku_id, title, price FROM observations WHERE exact_comp_key IS NULL").fetchall()
    for rid, sid, title, price in todo:
        tn = norm(title or "")
        sk = smap.get(sid, {})
        q = parse_quantity(tn, sk)
        conn.execute("UPDATE observations SET quantity=?, unit_price=?, exact_comp_key=?, sealed=? WHERE rowid=?",
                     (q, round((price or 0) / q, 2) if q else price,
                      exact_comp_key(sid, tn, sk), 1 if sealed_product(tn) else 0, rid))
    if todo: conn.commit()
    return len(todo)

def historical_low(conn, key, upto=None):
    """Plus bas prix UNITAIRE jamais observé pour cette cloison de comparabilité.
    C'est un FAIT HISTORIQUE, jamais une valeur de marché : il ne sert qu'à surveiller un retour
    en stock. Strictement cloisonné par exact_comp_key et réservé aux lignes sealed=1 — un single,
    une autre configuration ou un lot de quantité différente ne peut pas le contaminer."""
    q = ("SELECT unit_price, seen_at, shop FROM observations "
         "WHERE exact_comp_key=? AND sealed=1 AND unit_price IS NOT NULL")
    args = [key]
    if upto: q += " AND seen_at<=?"; args.append(upto)
    rows = conn.execute(q + " ORDER BY unit_price", args).fetchall()
    if not rows: return None
    return {"low": rows[0][0], "at": rows[0][1], "shop": rows[0][2],
            "n_shops": len({r[2] for r in rows}), "n_obs": len(rows)}

def line_memory(conn, sku_id, shop, url, vt, upto):
    """Restitution pure depuis observations — aucune collecte supplémentaire."""
    rows = conn.execute("""SELECT seen_at, price, available FROM observations
        WHERE sku_id=? AND shop=? AND url=? AND variant_title=? AND seen_at<=?
        ORDER BY seen_at""", (sku_id, shop, url, vt, upto)).fetchall()
    if not rows: return None
    prices = [r[1] for r in rows]
    m = {"first_seen": rows[0][0], "last_seen": rows[-1][0], "n_obs": len(rows),
         "min_price_ever": min(prices), "min_price_before": min(prices[:-1]) if len(prices) > 1 else None,
         "price_history": [(r[0], r[1]) for r in rows],
         "prev_price": prices[-2] if len(rows) > 1 else None,
         "days_oos_before_return": None, "days_in_stock_same_price": None}
    def days(a, b):
        try: return max(0, (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days)
        except Exception: return None
    if rows[-1][2] == 1:
        # remontée : depuis quand en rupture avant ce retour ?
        oos_start = None
        for r in reversed(rows[:-1]):
            if r[2] == 0: oos_start = r[0]
            else: break
        if oos_start: m["days_oos_before_return"] = days(oos_start, rows[-1][0])
        # depuis quand en stock au même prix ?
        same = rows[-1][0]
        for r in reversed(rows[:-1]):
            if r[2] == 1 and abs(r[1] - rows[-1][1]) < 0.01: same = r[0]
            else: break
        m["days_in_stock_same_price"] = days(same, rows[-1][0])
    return m

def ref_self_sourced(sku: dict, shop: str, kind: str | None) -> bool:
    """La référence vient-elle UNIQUEMENT de ce shop ? Un 'seul en stock au prix de la référence'
    n'est pas une opportunité quand c'est ce shop lui-même qui a fixé la référence : on compare
    le prix à son propre prix. Superior Optic Hanger 75 avec ask=75 relevé chez Superior seul.
    Un sold externe (StockX, eBay, SportsCardsPro) n'est jamais auto-sourcé."""
    if kind != "ask": return False
    froms = sku.get("market_ask_from") or []
    return len(froms) == 1 and froms[0] == shop

def compute_badges(o, mem, sku, trust_level, in_stock_lines):
    """Renvoie (déclencheurs, descriptifs, gap_pct, ref, ref_kind). Aucun score composite :
    chaque badge est un fait vérifiable, et les descriptifs ne déclenchent jamais HOT NOW."""
    price, available = o[3], o[4]
    ref, kind = market_ref(sku)
    gap = round((price - ref) / ref * 100, 1) if ref else None
    trig, desc = [], []

    if mem and mem.get("days_oos_before_return") is not None and available:
        trig.append(f"RESTOCK +{mem['days_oos_before_return']}j")
    # NEW_LOW est un événement, pas un état : un prix stable observé trois fois n'est pas un
    # nouveau plus-bas. Constaté le 18/08 — 11 des 15 lignes HOT NOW étaient des prix inchangés.
    if (mem and available and mem["n_obs"] >= 3 and mem["min_price_before"] is not None
            and price < mem["min_price_before"] - 1e-9):
        trig.append("NEW_LOW")
    if mem and mem.get("prev_price") and price < mem["prev_price"] - 1e-9:
        trig.append(f"PRICE_DROP -{round((mem['prev_price'] - price) / mem['prev_price'] * 100)}%")
    if available and len(in_stock_lines) == 1:
        sold = sku.get("market_sold_us"); ask = sku.get("market_ask_us")
        cheap = (ask is not None and price <= ask) or (sold is not None and price <= 1.10 * float(sold))
        cheap = cheap and not ref_self_sourced(sku, o[1], kind)
        (trig if cheap else desc).append("SEUL_EN_STOCK" if cheap else "ONLY_STOCK_SEEN")
    if gap is not None and available:
        if gap <= -20: trig.append(f"STRONG_DEAL {gap:.0f}%")
        elif gap <= -10: trig.append(f"DEAL {gap:.0f}%")

    if sku.get("wemby_rc"): desc.append("RC_YEAR")
    if sku.get("wemby_year2"): desc.append("YEAR2")
    if sku.get("trophy"): desc.append("TROPHY")
    lic = sku.get("licensed", True)
    if lic is False: desc.append("UNLICENSED")
    elif lic == "nbpa": desc.append("NBPA")
    elif lic == "euroleague": desc.append("EUROLEAGUE")
    if sku.get("league") == "EuroLeague" and "EUROLEAGUE" not in desc: desc.append("EUROLEAGUE")
    if trust_level == "watch": desc.append("VERIFY")
    elif trust_level == "high_risk": desc.append("VERIFY SELLER")
    if available and len(in_stock_lines) > 1 and price == min(l[3] for l in in_stock_lines):
        desc.append(f"cheapest of {len(in_stock_lines)} in stock")
    if ref is None: desc.append("MARKET DATA INSUFFICIENT")
    return trig, desc, gap, ref, kind

def source_health(conn, shop_keys, lookback=6):
    """O — santé d'une source, jugée sur son propre historique plutôt que sur un seuil unique.

    HEALTHY  : dernier passage complet et volume conforme à sa base récente.
    PARTIAL  : dernier passage interrompu (timeout, erreur, pagination incomplète).
               Ce n'est PAS une source morte : le chrono ou le réseau l'ont coupée.
    DEGRADED : volume effondré vs sa propre base, ou PARTIAL répétés, ou dernier passage
               complet trop ancien.
    DEAD     : plusieurs passages consécutifs à zéro produit, sans interruption pour l'expliquer.
    """
    out = {}
    for k in shop_keys:
        runs = conn.execute("""SELECT seen_at, partial, n_raw, reason, duration_s FROM crawl_runs
                               WHERE shop=? ORDER BY seen_at DESC LIMIT ?""", (k, lookback)).fetchall()
        if not runs:
            out[k] = ("UNKNOWN", "aucun passage enregistré"); continue
        seen_at, partial, n_raw, reason, dur = runs[0]
        if (reason or "").startswith("SKIPPED"):
            out[k] = ("SKIPPED", reason.split(":", 1)[1].lower()); continue
        complete = [r for r in runs if not r[1]]
        zeros = [r for r in runs if not r[1] and (r[2] or 0) == 0]
        if len(zeros) >= 2 and len(zeros) == len(complete):
            out[k] = ("DEAD", f"{len(zeros)} passages complets consécutifs à 0 produit"); continue
        if partial:
            n_part = sum(1 for r in runs if r[1])
            if n_part >= 3:
                out[k] = ("DEGRADED", f"{n_part} passages interrompus sur {len(runs)} (dernier : {reason})")
            else:
                out[k] = ("PARTIAL", f"dernier passage interrompu ({reason}"
                                     + (f", {dur/60:.1f} min)" if dur else ")"))
            continue
        base = [r[2] or 0 for r in complete[1:]]
        if base:
            med = sorted(base)[len(base) // 2]
            if med and n_raw < med * 0.5:
                out[k] = ("DEGRADED", f"volume {n_raw} contre une base récente de {med}"); continue
        out[k] = ("HEALTHY", f"{n_raw} produits" + (f", {dur/60:.1f} min" if dur else ""))
    return out

def watchlist_layers(entries):
    """N — trois couches, pour que la watchlist redevienne actionnable.

    1. RESTOCK PRIORITY : en rupture, historique cloisonné, et l'ancien bas est nettement sous
       la référence de marché disponible. Sans référence exploitable on ne peut PAS qualifier
       une priorité honnêtement — la ligne descend en historique, elle n'est pas promue.
    2. HISTORICAL LOWS : un historique existe, mais rien ne justifie l'urgence.
    3. ALL OOS : le reste, replié.
    """
    prio, lows, rest = [], [], []
    seen = set()
    for e in entries:
        if e["available"]: continue
        # une ligne par produit, pas par annonce : l'historique est déjà cloisonné par
        # exact_comp_key, cinq shops en rupture sur le même produit = une seule entrée.
        k = e.get("key")
        if k in seen: continue
        seen.add(k)
        h = e.get("hist")
        if not h: rest.append(e); continue
        ref, kind = e.get("ref"), e.get("kind")
        # Qualifier une priorité exige une référence NON CIRCULAIRE : un sold externe, ou un ask
        # relevé chez au moins deux sources. Comparer un ancien bas d'un shop à l'ask du même shop
        # ne prouve rien. Sans cela la ligne descend en historique — elle n'est pas promue.
        solid = kind == "sold" or (kind == "ask" and len(e["sku"].get("market_ask_from") or []) >= 2)
        if ref and solid and h["low"] <= ref * 0.90:
            e["restock_gap"] = round((h["low"] - ref) / ref * 100, 1)
            prio.append(e)
        else:
            e["restock_gap"] = None
            lows.append(e)
    prio.sort(key=lambda e: e["restock_gap"])
    lows.sort(key=lambda e: e["hist"]["low"])
    return prio, lows, rest

def hot_now(entries, limit=15):
    """Lignes EN STOCK avec >=1 déclencheur ET une référence de marché. Triées par nombre de
    déclencheurs puis par écart croissant. Une ligne sans référence n'y entre jamais."""
    # invariant : une ligne plus chère que la référence de marché n'est pas une opportunité,
    # quel que soit le déclencheur qui l'accompagne.
    elig = [e for e in entries if e["available"] and e["triggers"] and e["ref"] is not None
            and e["gap"] is not None and e["gap"] <= 0]
    elig.sort(key=lambda e: (-len(e["triggers"]), e["gap"] if e["gap"] is not None else 0))
    return elig[:limit]

def decide(status_active, gap, conf, comp, buy_below, price):
    """GO exige : SKU ACTIVE, comparaison EXACT, sold_confidence >= MEDIUM, et prix sous le seuil.
    Sans sold fiable, une anomalie de prix reste une anomalie — jamais un ordre d'achat."""
    if not status_active: return None
    under = buy_below is not None and price <= buy_below
    if not under: return None
    if comp != "EXACT": return "PRICE ANOMALY — RELATED COMP"
    if conf is None: return "PRICE ANOMALY — NO SOLD DATA"
    if conf == "LOW": return "PRICE ANOMALY — LOW MARKET CONFIDENCE"
    return "GO"

def report(cat: dict, conn: sqlite3.Connection, seen_at: str | None, trust: dict | None = None):
    trust = trust or {}
    skus = {s["id"]: s for s in cat["skus"]}
    nb = cat["landed_cost"].get("bundle_boxes", 8)
    n_mig = backfill_comp(conn, cat["skus"])
    if n_mig: print(f"(migration : {n_mig} observation(s) enrichies en exact_comp_key / sealed)")
    n_purged = purge_stale(conn, cat["skus"])
    if n_purged: print(f"(purge : {n_purged} observation(s) obsolètes retirées — matchées par une ancienne version du code)")
    # dernier passage RÉUSSI par shop (dernier seen_at où le shop a renvoyé au moins 1 produit brut)
    # dernier passage RÉUSSI = le plus récent qui n'est PAS marqué PARTIAL. Un crawl tronqué par
    # une erreur réseau ne devient jamais la référence : les observations du dernier passage complet
    # restent en place plutôt que de disparaître du classement.
    last_by_shop = dict(conn.execute("""
        SELECT shop, MAX(seen_at) FROM products_raw p
        WHERE NOT EXISTS (SELECT 1 FROM crawl_runs c
                          WHERE c.shop=p.shop AND c.seen_at=p.seen_at AND c.partial=1)
        GROUP BY shop""").fetchall())
    part = conn.execute("""SELECT shop, seen_at, n_raw FROM crawl_runs WHERE partial=1
                           AND seen_at=(SELECT MAX(seen_at) FROM crawl_runs)""").fetchall()
    for sh, sa, nr in part:
        print(f"⚠️  [{sh}] passage {sa} PARTIAL ({nr} produits) — ignoré, référence = dernier passage complet")
    # dernière observation par (sku, shop, url, variante)
    rows = conn.execute("""
      SELECT o.sku_id, o.shop, o.title, o.price, o.available, o.url, o.match_score, o.seen_at, o.variant_title, o.comp_type, o.image_url, o.quantity, o.unit_price, o.exact_comp_key
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
    html = []          # lignes pour la page web
    all_entries = []   # toutes les lignes enrichies (mémoire + badges) pour HOT NOW et signals
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
                conf = sold_confidence(s)
                entries = []
                for o in obs:
                    mem = line_memory(conn, sid, o[1], o[5], o[8], o[7])
                    tg, dsc, gap, ref, kind = compute_badges(o, mem, s, trust_of(o[1], trust), in_stock)
                    key = o[13] if len(o) > 13 and o[13] else exact_comp_key(sid, norm(o[2]), s)
                    hist = historical_low(conn, key, o[7])
                    entries.append({"o": o, "key": key, "hist": hist,
                                    "available": bool(o[4]), "triggers": tg, "descriptors": dsc,
                                    "gap": gap, "ref": ref, "kind": kind, "mem": mem,
                                    "comp": (o[9] or "EXACT"), "sku": s, "sid": sid})
                all_entries.extend(entries)
                by_line = {id(e["o"]): e for e in entries}
                # status du SKU : le matching tourne sur TOUS les statuts, la classification GO/NO_GO
                # ne concerne que les ACTIVE. WATCH/CANDIDATE sont observés, jamais recommandés à l'achat.
                sk_st = s.get("status", "ACTIVE")
                if sk_st != "ACTIVE":
                    status, icon = ("SUIVI" if sk_st == "WATCH" else "CANDIDAT"), "·"
                elif best and s.get("buy_below_usd") and best[3] <= s["buy_below_usd"]:
                    d = decide(True, None, conf, by_line[id(best)]["comp"], s.get("buy_below_usd"), best[3])
                    status, icon = ("GO", "🔥") if d == "GO" else (d, "⚡")
                elif best and s.get("watch_below_usd") and best[3] <= s["watch_below_usd"]: status, icon = "WATCH", "👀"
                elif best: status, icon = "NO_GO", "⛔"
                else: status, icon = ("NO_STOCK" if obs else "NO_DATA"), "—"
                lic = "" if s.get("licensed", True) is True else f"  ⚑ {s.get('licensed')}"
                bpc = s.get("boxes_per_case")
                print(f"\n{icon} {status}   {sku_label(s)}   [{sid}]{lic}")
                rs = {id(r[0]) for r in restocks}
                for i, o in enumerate(obs[:6], 1):
                    stock = "IN STOCK" if o[4] else "SOLD OUT"
                    flag = "  🔔" if any(o is r for r,_ in restocks) else ""
                    q = (o[11] if len(o) > 11 and o[11] else None) or bpc
                    unit = f"  ({q} boîtes = ${o[3]/q:>7.2f}/boîte)" if q and q > 1 else ""
                    e = by_line[id(o)]
                    bl = "  ".join(["🔹" + x for x in e["triggers"]] + e["descriptors"])
                    print(f"   {i}. {o[1]:<16} ${o[3]:>8.2f}{unit}  {stock:<9} landed≈€{landed_eur(o[3]/bpc if bpc else o[3],cat):>7.2f}  (score {o[6]:.2f}){flag}")
                    if bl: print(f"        {bl}")
                ask = s.get("market_ask_us"); sold = s.get("market_sold_us"); eu = s.get("eu_reference_eur")
                ssrc = s.get("market_sold_source"); schk = s.get("market_sold_checked_at")
                prov = f" [{ssrc}{' ' + str(schk) if schk else ''}]" if sold and ssrc else ""
                print(f"   ask {money(ask):<8} sold {money(sold):<8}{prov} | buy ≤ {money(s.get('buy_below_usd')):<8} | watch ≤ {money(s.get('watch_below_usd')):<8} | EU {money(eu, '€')}")
                # M : l'historique est un FAIT, jamais une référence de marché. Il est affiché
                # séparément du prix live et ne peut produire ni DEAL ni GO.
                he = next((e for e in entries if e["hist"]), None)
                if he:
                    h = he["hist"]
                    live = min((x[3] for x in in_stock), default=None)
                    print(f"   HISTORICAL LOW ${h['low']:.2f} (le {h['at'][:10]}, {h['shop']}, "
                          f"{h['n_shops']} shop(s) vus)" + (f" | cheapest live ${live:.2f}" if live else " | aucun live"))
                    if not in_stock: print(f"   RESTOCK TARGET ${h['low']:.2f}  — surveillance, pas une valeur de marché")
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
    # P : chaque ligne porteuse d'un déclencheur est enregistrée — base du backtesting à N jours
    stamp_now = seen_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    for e in all_entries:
        if not e["triggers"]: continue
        o = e["o"]
        conn.execute("INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (e["sid"], o[1], o[5], o[8], o[3], json.dumps(e["triggers"] + e["descriptors"]),
                      e["ref"], e["kind"], e["gap"], stamp_now))
    conn.commit()
    prio, lows, rest = watchlist_layers(all_entries)
    print("\n" + "="*72 + f"\n  👀 WATCHLIST — {len(prio)} prioritaires / {len(lows)} historiques / {len(rest)} autres\n" + "="*72)
    for e in prio[:15]:
        h = e["hist"]
        print(f"  🔔 RESTOCK PRIORITY  {sku_label(e['sku'])[:40]:<42} target ${h['low']:>8.2f} "
              f"({h['at'][:10]}, {h['n_shops']} shop(s))  {e['restock_gap']:>6.1f}% vs {e['kind']} ${e['ref']:.2f}")
    if not prio:
        print("  (aucune priorité qualifiable : il faut une référence de marché pour dire qu'un ancien prix mérite surveillance)")
    for e in lows[:10]:
        h = e["hist"]
        print(f"     historical low     {sku_label(e['sku'])[:40]:<42} ${h['low']:>8.2f} ({h['at'][:10]}, {h['n_shops']} shop(s))")
    health = source_health(conn, [x["key"] for x in yaml.safe_load((ROOT/"sources.yaml").read_text(encoding="utf-8"))["shops"]])
    # UNKNOWN = aucun passage encore enregistré : absence de donnée, pas anomalie. Après un run
    # complet aucun shop crawlable ne reste UNKNOWN — le compteur de synthèse le montre.
    anomalies = {k: v for k, v in health.items() if v[0] not in ("HEALTHY", "SKIPPED", "UNKNOWN")}
    print("\n" + "="*72 + f"\n  🩺 SANTÉ DES SOURCES — {len(anomalies)} anomalie(s)\n" + "="*72)
    for k, (st, why) in sorted(anomalies.items()):
        print(f"  {st:<9} {k:<20} {why}")
    if not anomalies: print("  (aucune anomalie : toutes les sources crawlées ont rendu un passage complet)")
    import collections as _c
    print("  " + " · ".join(f"{n} {st}" for st, n in _c.Counter(v[0] for v in health.values()).most_common()))
    hn = hot_now(all_entries)
    print("\n" + "="*72 + f"\n  🔥 HOT NOW — {len(hn)} ligne(s)\n" + "="*72)
    for e in hn:
        o = e["o"]
        print(f"  {sku_label(e['sku'])[:44]:<46} ${o[3]:>8.2f} {o[1]:<16} {e['gap']:>6.1f}%  "
              + " ".join(e["triggers"]))
    if not hn: print("  (aucune ligne en stock ne cumule un déclencheur et une référence de marché)")
    write_html(cat, html, restocks, q, seen_at, trust, hn, all_entries, SHOP_COUNTS)
    print(f"\nCSV → {csv_path}\nHTML → {OUT/'index.html'}")

BUCKETS = [("retail",  {"Blaster","Mega","Hanger","Retail Box","Pack","Value Box","Fat Pack","Cello"}),
           ("premium", {"Hobby Blaster","Hobby Mega","Fast Break","Choice","H2","International","Chinese New Year","FOTL"}),
           ("hobby",   {"Hobby"}),
           ("ultra",   {"Case"})]

def sku_bucket(s: dict) -> str:
    if s.get("trophy"): return "ultra"
    for name, fmts in BUCKETS:
        if s["format"] in fmts: return name
    return "retail"

def A(url, label, cls=""):
    """Tout lien sortant : nouvel onglet, sans fuite de referrer ni accès à window.opener."""
    c = f" class={cls}" if cls else ""
    return f"<a{c} href='{url}' target=\"_blank\" rel=\"noopener noreferrer\">{label}</a>"

def thumb(e, always=False):
    src = e["o"][10] if len(e["o"]) > 10 else None
    if not src: return ""
    alt = (e["o"][2] or "").replace("'", "&#39;")[:120]
    return f"<img class=th src='{src}' alt='{alt}' loading=\"lazy\" width=56 height=56>" if always else ""

def badge_html(e):
    out = "".join(f"<span class='b t'>{x}</span>" for x in e["triggers"])
    out += "".join(f"<span class='b d'>{x}</span>" for x in e["descriptors"])
    return out

def write_html(cat, blocks, restocks, review, seen_at, trust=None, hot=None, entries=None, shopcount=None):
    trust = trust or {}; hot = hot or []; entries = entries or []; shopcount = shopcount or []
    nb = cat["landed_cost"].get("bundle_boxes", 8)
    col = {"GO":"#1b7f3b","WATCH":"#b8860b","NO_GO":"#b22222","NO_STOCK":"#666","NO_DATA":"#999",
           "SUIVI":"#4a5568","CANDIDAT":"#8a8a8a"}
    h = ["<!doctype html><meta charset='utf-8'><meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>Wemby Hunt</title><style>",
         ":root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e5e5e5;--card:#fafafa}",
         "@media(prefers-color-scheme:dark){:root{--bg:#141414;--fg:#ededed;--mut:#9a9a9a;--line:#2c2c2c;--card:#1c1c1c}}",
         "*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;",
         "max-width:780px;margin:0 auto;padding:12px;color:var(--fg);background:var(--bg);line-height:1.45}",
         "h1{font-size:1.35rem;margin:.2em 0}h2{font-size:1.05rem;margin:1.6em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.3em}",
         "h3{font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:1.1em 0 .4em}",
         ".small{color:var(--mut);font-size:.8rem}",
         ".hot{display:flex;gap:10px;align-items:center;padding:10px;border:1px solid var(--line);",
         "border-radius:10px;margin:8px 0;background:var(--card)}",
         ".th{border-radius:6px;object-fit:cover;flex:0 0 56px;background:var(--line)}",
         ".hb{flex:1;min-width:0}.nm{font-weight:600;font-size:.92rem}",
         ".pr{font-weight:700;font-size:1.05rem;white-space:nowrap}",
         ".b{display:inline-block;font-size:.7rem;padding:1px 6px;border-radius:99px;margin:2px 3px 0 0}",
         ".b.t{background:#1b7f3b;color:#fff}.b.d{background:var(--line);color:var(--mut)}",
         ".st{font-weight:700;color:#fff;padding:1px 7px;border-radius:4px;font-size:.75rem}",
         "table{width:100%;border-collapse:collapse}td,th{padding:4px 6px;border-bottom:1px solid var(--line);",
         "text-align:left;font-size:.8rem}.oos{color:var(--mut)}",
         ".sku{border:1px solid var(--line);border-radius:8px;padding:10px;margin:10px 0}",
         "details{margin:.4em 0}summary{cursor:pointer;color:var(--mut);font-size:.85rem}",
         "a{color:inherit}.wrap{overflow-x:auto}</style>",
         "<h1>🏀 Wemby Hunt</h1>",
         f"<p class=small>Dernier passage : {seen_at or ''} UTC · landed = coût rendu France ESTIMÉ par boîte "
         f"dans un panier de {nb} boîtes.</p>"]

    # ---------------- C : HOT NOW, en tête, format téléphone
    h.append(f"<h2>🔥 Hot now — {len(hot)}</h2>")
    if not hot:
        h.append("<p class=small>Rien à faire aujourd'hui : aucune ligne en stock ne cumule un déclencheur "
                 "et une référence de marché plus chère que le prix affiché.</p>")
    for e in hot:
        o = e["o"]
        h.append("<div class=hot>" + thumb(e, always=True) +
                 f"<div class=hb><div class=nm>{A(o[5], sku_label(e['sku']))}</div>"
                 f"<div class=small>{o[1]}{' · ' + f'{e[chr(39)+chr(39)]}' if False else ''}"
                 f" · réf {e['kind']} ${e['ref']:.2f} · écart {e['gap']:.1f} %</div>"
                 f"<div>{badge_html(e)}</div></div>"
                 f"<div class=pr>${o[3]:.2f}</div></div>")
    extra = len([x for x in entries if x["available"] and x["triggers"]]) - len(hot)
    if extra > 0:
        h.append(f"<p class=small><a href='#complet'>Voir les {extra} opportunité(s) restantes →</a></p>")

    # ---------------- D : sections
    def block_card(b, obs, show_thumb=False):
        t, status, icon, s = b[0], b[1], b[2], b[3]
        bg = col.get(status, "#8a5a00")
        ask=s.get("market_ask_us"); sold=s.get("market_sold_us"); conf = sold_confidence(s)
        r = [f"<div class=sku><span class=st style='background:{bg}'>{icon} {status}</span> "
             f"<b>{sku_label(s)}</b>"
             f"<div class=small>ask {money(ask)} · sold {money(sold)}"
             f"{' (' + conf + ')' if conf else ''} · buy ≤ {money(s.get('buy_below_usd'))}"
             f" · watch ≤ {money(s.get('watch_below_usd'))}</div>"]
        if obs:
            r.append("<div class=wrap><table><tr><th>Shop</th><th>Produit</th><th>Prix</th><th>Stock</th><th>Landed €</th></tr>")
            seen = set()
            for e in obs:
                o = e["o"]
                k = (o[1], o[5], o[8], round(o[3], 2), o[4])
                if k in seen: continue
                seen.add(k)
                if len(seen) > 12: break
                cls = "" if o[4] else " class=oos"
                bpc = s.get("boxes_per_case")
                r.append(f"<tr{cls}><td>{o[1]}</td><td>{thumb(e, show_thumb)}{A(o[5], o[2][:70])}"
                         f"<div>{badge_html(e)}</div></td><td>${o[3]:.2f}</td>"
                         f"<td>{'IN STOCK' if o[4] else 'sold out'}</td>"
                         f"<td>€{landed_eur(o[3]/bpc if bpc else o[3], cat):.2f}</td></tr>")
            r.append("</table></div>")
        r.append("</div>")
        return "".join(r)

    by_sid = {}
    for e in entries: by_sid.setdefault(e["sid"], []).append(e)

    def section(title, pred, show_thumb=False, note=None):
        sel = [b for b in blocks if pred(b[3])]
        h.append(f"<h2>{title} — {len(sel)}</h2>")
        if note: h.append(f"<p class=small>{note}</p>")
        if not sel: h.append("<p class=small>Aucun SKU dans cette section.</p>")
        return sel

    sel = section("🏀 Rookie 23/24", lambda s: s["season"] == "2023-24" and not s.get("trophy") and not s.get("wemby_year2"))
    for bname, label in [("retail","Retail"),("premium","Premium"),("hobby","Hobby"),("ultra","Ultra")]:
        grp = [b for b in sel if sku_bucket(b[3]) == bname]
        if not grp: continue
        h.append(f"<h3>{label} — {len(grp)}</h3>")
        for b in grp: h.append(block_card(b, by_sid.get(b[3]['id'], [])))

    for b in section("⭐ Year 2 24/25", lambda s: bool(s.get("wemby_year2"))):
        h.append(block_card(b, by_sid.get(b[3]['id'], [])))
    for b in section("💎 Trophy", lambda s: bool(s.get("trophy")), show_thumb=True,
                     note="Affiché même sans vente réalisée : ces SKU portent MARKET DATA INSUFFICIENT tant que market_sold_us est vide."):
        h.append(block_card(b, by_sid.get(b[3]['id'], []), True))

    # 🔔 Mouvements récents
    mv = [e for e in entries if any(t.startswith(("RESTOCK", "PRICE_DROP", "NEW_LOW")) for t in e["triggers"])]
    h.append(f"<h2>🔔 Mouvements récents — {len(mv)}</h2>")
    if not mv: h.append("<p class=small>Aucun mouvement depuis le passage précédent.</p>")
    else:
        h.append("<div class=wrap><table><tr><th>SKU</th><th>Shop</th><th>Prix</th><th>Mouvement</th></tr>")
        for e in mv[:30]:
            h.append(f"<tr><td>{A(e['o'][5], sku_label(e['sku'])[:40])}</td><td>{e['o'][1]}</td>"
                     f"<td>${e['o'][3]:.2f}</td><td>{badge_html(e)}</td></tr>")
        h.append("</table></div>")

    # 👀 Watchlist en trois couches (N)
    wprio, wlows, wrest = watchlist_layers(entries)
    h.append(f"<h2>👀 Watchlist — {len(wprio)} prioritaire(s)</h2>")
    h.append("<p class=small>Un ancien prix n'est jamais une valeur de marché. Une priorité n'est "
             "affichée que si une référence de marché permet de la justifier.</p>")
    def wl_table(items, cols_gap):
        r = ["<div class=wrap><table><tr><th>Produit</th><th>Historical low</th><th>Vu le</th><th>Shops</th>"
             + ("<th>vs réf</th>" if cols_gap else "") + "</tr>"]
        for e in items:
            hh = e["hist"]
            r.append(f"<tr><td>{A(e['o'][5], sku_label(e['sku'])[:44])}</td><td>${hh['low']:.2f}</td>"
                     f"<td class=small>{hh['at'][:10]}</td><td>{hh['n_shops']}</td>"
                     + (f"<td>{e['restock_gap']:.1f} %</td>" if cols_gap else "") + "</tr>")
        return "".join(r) + "</table></div>"
    if wprio:
        h.append("<h3>🔔 Restock priority</h3>" + wl_table(wprio[:20], True))
    else:
        h.append("<p class=small>Aucune priorité qualifiable aujourd'hui : sans référence de marché, "
                 "un ancien prix bas ne suffit pas à justifier une surveillance.</p>")
    if wlows:
        h.append(f"<details><summary>📉 Historical lows — {len(wlows)}</summary>" + wl_table(wlows[:40], False) + "</details>")
    if wrest:
        h.append(f"<details><summary>🗂 Toutes les observations en rupture — {len(wrest)}</summary>"
                 "<div class=wrap><table><tr><th>Produit</th><th>Shop</th><th>Dernier prix</th></tr>"
                 + "".join(f"<tr><td>{A(e['o'][5], sku_label(e['sku'])[:44])}</td><td>{e['o'][1]}</td>"
                           f"<td>${e['o'][3]:.2f}</td></tr>" for e in wrest[:60])
                 + "</table></div></details>")

    # 🔎 Shops découverts
    # le fragment de discover.py porte son propre titre : on le retire pour garder l'ordre des sections
    frag = ROOT / "discovered" / "candidates.html"
    h.append("<h2>🔎 Shops découverts</h2>")
    if frag.exists():
        h.append(re.sub(r"<h2>.*?</h2>", "", frag.read_text(encoding="utf-8"), count=1, flags=re.S))
    else:
        h.append("<p class=small>Aucune prospection enregistrée.</p>")

    # ⚠️ Review
    h.append(f"<h2>⚠️ À revoir — {len(review)}</h2>")
    if review:
        h.append("<div class=wrap><table><tr><th>Shop</th><th>Titre</th><th>Prix</th><th>Stock</th><th>Candidats</th></tr>")
        for shop, title, price, av, cands, sc, url in review:
            h.append(f"<tr><td>{shop}</td><td>{A(url, title[:70])}</td><td>${price:.2f}</td>"
                     f"<td>{'IN' if av else 'OOS'}</td><td class=small>{cands}</td></tr>")
        h.append("</table></div>")

    # 🗃 Rapport complet + compteurs techniques, hors premier écran
    h.append("<h2 id=complet>🗃 Rapport complet</h2><details><summary>Tous les SKU et toutes les lignes</summary>")
    for b in blocks: h.append(block_card(b, by_sid.get(b[3]['id'], [])))
    h.append("</details><details><summary>Compteurs par source</summary><div class=wrap><table>"
             "<tr><th>Shop</th><th>trust</th><th>bruts</th><th>matchés</th></tr>")
    for k, tr, raw, mt in shopcount:
        h.append(f"<tr><td>{k}</td><td>{tr}</td><td>{raw}</td><td>{mt}</td></tr>")
    h.append("</table></div></details>")
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
            n_raw, n_obs, partial = collect_shop(sh, skus, conn, seen_at)
            SHOP_COUNTS.append((sh["key"], sh.get("trust", "trusted"), n_raw, n_obs))
            tag = "  ⚠️ PARTIAL — passage NON retenu comme référence" if partial else ""
            print(f"  {n_raw} produits bruts, {n_obs} rattachés à un SKU{tag}")
        report(cat, conn, seen_at, trust)
    else:
        report(cat, conn, None, trust)

if __name__ == "__main__":
    main()
