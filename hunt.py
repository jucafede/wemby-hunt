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
    # Le séparateur optionnel couvre les titres Shopify du type « Select Basketball Hobby, Mega Box » :
    # la virgule sépare le canal du format réel, elle ne fait pas du produit une boîte hobby.
    ("Hobby Mega", r"hobby\s*[,/&·-]?\s*mega|mega\s*[,/&·-]?\s*hobby"),
    ("Hobby Blaster", r"hobby\s*[,/&·-]?\s*blaster|blaster\s*[,/&·-]?\s*hobby"),
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
SPORT_HINTS = {"basketball": ["basketball", "nba", "bball", "hoops"], "not_basketball": ["football", "nfl", "baseball", "mlb", "hockey", "nhl", "soccer", "wnba", "pokemon", "ufc", "wrestling", "f1", "euroleague", "golf", "nascar", "racing", "wwe", "tennis", "mma", "boxing", "pfl", "fighters", "bundesliga", "fifa", "la liga", "serie a", "ligue 1", "champions league", "\bmls\b", "eredivisie", "college", "draft picks", "world cup", "premier league"]}
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
# « chrome black » et non « black » : le mot seul apparaît partout (Black Friday, blackout).
# Topps Chrome Black est une gamme premium distincte, autour de 700-1000 $ la boîte, contre
# ~300 $ pour Chrome Hobby. Confondues, elles gonflaient la médiane demandée du Chrome Hobby
# à 960 $ sur 11 vendeurs et faisaient passer une présale Chrome Black à 700 $ pour un deal.
EDITION_TOKENS = ("sapphire", "monster", "first day", "cactus jack", "china", "gravity feed",
                  "chrome black")

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

# Une précommande n'est pas le même produit commercial qu'une boîte en stock : on paie
# maintenant pour livraison dans plusieurs mois, avec le risque vendeur en prime. Elle rejoint
# donc la dimension édition de la clé de comparabilité. Le sens de l'erreur est le bon : au pire
# le vivier se fragmente et la ligne passe en DATA INSUFFICIENT — jamais en faux deal.
PREORDER_RE = re.compile(r"pre[- ]?order|pre[- ]?sale|presale|releases?\s+\d{1,2}[/-]\d{1,2}")

def exact_comp_key(sku_id: str, t: str, sku: dict | None = None, url: str = "") -> str:
    """Cloison de comparabilité commerciale. SOLD, LIVE MARKET, cheapest, historique et signaux
    ne doivent JAMAIS traverser cette clé. Deux offres de clés différentes ne se comparent pas.

    L'URL compte : sportscardjunction titre « 2025-26 Bowman Basketball Blaster Box » et range
    le produit sous /products/pre-order-...-releases-4-22-26. Le titre ment par omission,
    le slug dit la vérité."""
    qty = parse_quantity(t, sku)
    toks = [tok.replace(" ", "") for tok in EDITION_TOKENS if tok in t]
    if PREORDER_RE.search(t) or PREORDER_RE.search((url or "").lower().replace("-", " ")):
        toks.append("preorder")
    ed = "+".join(toks) or "std"
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

# Un produit n'est jamais à la fois une boîte hobby et un format retail. Quand les deux mots
# cohabitent, c'est le format retail qui décrit le produit et « hobby » qui décrit le canal.
# Cas réel du 23/08 : « 2024-25 Panini Select Basketball Hobby, Blaster Box (Green & Red Mojo) »
# à 38 $ était rattaché au SKU Select HOBBY, dont les vendeurs demandent 422 $ — soit un
# faux ASK DEAL à -91 %.
RETAIL_WITH_HOBBY = r"\b(blasters?|megas?|hangers?)\b"

def format_guard_ok(fmt: str | None, t: str) -> bool:
    """False si le format « Hobby » a été retenu alors que le titre nomme un format retail."""
    return not (fmt == "Hobby" and re.search(RETAIL_WITH_HOBBY, t))

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
    # « Hobby » + un mot de format retail dans le même titre : le produit est le format retail.
    # Plutôt que de deviner lequel, on refuse le format — sans format, aucun SKU boîte ne matche.
    if not format_guard_ok(fmt, t): fmt = None
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
        fmt_ok = fmt == s["format"] or fmt in (s.get("format_aliases") or [])
        if fmt_ok: sc += 0.25                                 # format
        elif fmt is None: sc += 0.0                           # format inconnu → jamais >= 0.80 → REVIEW
        else: continue                                        # mauvais format = jamais
        if eff_sport == "basketball": sc += 0.05
        elif eff_sport == "other": continue
        else:
            # sport indéterminé : aucune preuve de basket dans le titre. Blacklister les ligues
            # une par une ne tient pas — il en existe trop. On plafonne sous le seuil de
            # rattachement : la ligne reste visible en REVIEW mais n'atteint jamais la couche
            # décisionnelle. Un 'Topps Chrome Bundesliga Value Blaster' sortait sinon à 0,97
            # et occupait une place HOT NOW à -37,5 %.
            sc = min(sc, 0.75)
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
                "quantity INTEGER", "unit_price REAL", "exact_comp_key TEXT", "sealed INTEGER",
                "market_region TEXT", "currency TEXT"):
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
    if shop["type"] == "eu_reference":
        return skip(f"type=eu_reference ({shop.get('country','')}, {shop.get('platform','')}) "
                    f"→ référence de prix EU, non crawlée", "EU_REFERENCE")
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
                conn.execute("INSERT OR REPLACE INTO observations (sku_id,shop,title,variant_title,price,available,url,match_score,seen_at,matcher_version,image_url,comp_type,quantity,unit_price,exact_comp_key,sealed,market_region,currency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m.sku_id, shop["key"], full, vt_clean, price, available, url, m.score, seen_at,
                     MATCHER_VERSION, image_url, ct, qty, unit, exact_comp_key(m.sku_id, tn, sku_obj, url),
                     1 if sealed_product(tn) else 0,
                     shop.get("market_region", "US"), shop.get("currency", "USD")))
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
    mfr, st = str(s["manufacturer"]), str(s["set"])
    bits = [s["season"]] + ([st] if st.lower().startswith(mfr.lower()) else [mfr, st])
    if s.get("league"): bits.append(s["league"])
    bits.append(str(s["format"]))
    # un Case doit dire de QUOI il est le case : cinq cases Bowman s'affichaient tous
    # « 2025-26 Topps Bowman Case » et devenaient indistinguables (constaté le 21/08).
    if s.get("case_of"): bits.append(f"de {s['case_of']}")
    if s.get("boxes_per_case"): bits.append(f"({s['boxes_per_case']} boîtes)")
    # l'édition distingue Sapphire / Monster / First Day Issue du produit standard : sans elle,
    # deux blocs « 2023-24 Topps Chrome Hobby » coexistaient dans la page.
    ed = s.get("configuration") or s.get("configuration_note")
    if ed: bits.append(f"[{ed}]")
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
STALE_THRESHOLD_DAYS = 30

def threshold_age(sku: dict, today: str | None = None):
    """Q — âge d'un seuil manuel buy/watch. Renvoie (jours, stale) ou (None, False) si le SKU
    n'a pas de seuil. Le moteur ne recalcule JAMAIS un seuil : il signale qu'il a vieilli.
    Hiérarchie visée, à brancher quand le dataset SOLD arrivera :
    sold fiable > information marché récente > seuil manuel."""
    if sku.get("buy_below_usd") is None and sku.get("watch_below_usd") is None:
        return None, False
    d = sku.get("thresholds_reviewed_at")
    if not d: return None, True          # jamais revu = périmé par défaut, conservateur
    try:
        ref = datetime.fromisoformat(str(today)[:10]) if today else datetime.now(timezone.utc).replace(tzinfo=None)
        age = (ref - datetime.fromisoformat(str(d)[:10])).days
    except Exception:
        return None, True
    return age, age > STALE_THRESHOLD_DAYS

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
    todo = conn.execute("SELECT rowid, sku_id, title, price, url FROM observations WHERE exact_comp_key IS NULL").fetchall()
    for rid, sid, title, price, url in todo:
        tn = norm(title or "")
        sk = smap.get(sid, {})
        q = parse_quantity(tn, sk)
        conn.execute("UPDATE observations SET quantity=?, unit_price=?, exact_comp_key=?, sealed=? WHERE rowid=?",
                     (q, round((price or 0) / q, 2) if q else price,
                      exact_comp_key(sid, tn, sk, url), 1 if sealed_product(tn) else 0, rid))
    # Rattrapage des précommandes : leur clé a été calculée avant que le slug d'URL ne compte.
    # Tant qu'elles gardent l'ancienne clé, elles continuent de peser sur la médiane demandée
    # des boîtes réellement disponibles.
    pre = conn.execute("SELECT rowid, sku_id, title, url, exact_comp_key FROM observations "
                       "WHERE exact_comp_key IS NOT NULL AND exact_comp_key NOT LIKE '%preorder%'").fetchall()
    n_pre = 0
    for rid, sid, title, url, k in pre:
        tn = norm(title or "")
        nk = exact_comp_key(sid, tn, smap.get(sid, {}), url or "")
        if nk != k:
            conn.execute("UPDATE observations SET exact_comp_key=? WHERE rowid=?", (nk, rid))
            n_pre += 1
    if todo or n_pre: conn.commit()
    if n_pre: print(f"({n_pre} observation(s) reclassées en précommande d'après leur URL)")
    return len(todo)

# ================================================================ CURRENT MARKET
# Doctrine : CURRENT MARKET > STALE HISTORY · SOLD > ASK · RECENT > OLD ·
#            MULTI-SAMPLE > SINGLE · MÉDIANE > MOYENNE · UNKNOWN > FAUSSE PRÉCISION.
# Un plus-bas historique est un CONTEXTE, jamais la valeur actuelle.
FRESH_D, AGING_D = 30, 90

def freshness(age_days: int | None) -> str:
    if age_days is None: return "UNKNOWN"
    if age_days <= FRESH_D: return "FRESH"
    if age_days <= AGING_D: return "AGING"
    return "STALE"

def _age_days(seen_at, now=None):
    try:
        a = datetime.fromisoformat(str(seen_at)[:19].replace("Z", ""))
        b = datetime.fromisoformat(str(now)[:19]) if now else datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0, (b - a).days)
    except Exception:
        return None

def _median(v):
    v = sorted(v); n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

def _trim_outliers(vals):
    """Une observation aberrante ne doit jamais écraser la cote. On écarte ce qui s'éloigne
    de plus de 50 % de la médiane — un ask à 9 $ face à un marché à 187 $, un blaster à 25 $
    face à un cluster à 100 $. Sous 4 valeurs on ne coupe rien : trop peu pour juger."""
    if len(vals) < 4: return vals, []
    m = _median(vals)
    keep = [v for v in vals if m and 0.5 * m <= v <= 1.5 * m]
    return (keep, [v for v in vals if v not in keep]) if len(keep) >= 3 else (vals, [])

_SOLD_CACHE = {}

def load_sold():
    """Ventes réalisées saisies à la main, cloisonnées par exact_comp_key. Le moteur LIT ce
    fichier, il ne l'écrit jamais. Une vente sans date ni source est ignorée."""
    if not _SOLD_CACHE:
        f = ROOT / "sold.yaml"
        d = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("sales", {}) if f.exists() else {}
        _SOLD_CACHE.update(d or {})
    return _SOLD_CACHE

def sold_stats(key: str, now=None):
    """Distribution des ventes réalisées par fenêtre. Renvoie None si aucune vente exploitable.

    La confiance ne dépend PAS que de n : elle tient compte de la taille d'échantillon, de la
    récence ET de la dispersion. Six ventes serrées sur 30 jours ne valent pas six ventes
    éclatées de 600 à 1300 sur six mois."""
    e = load_sold().get(key)
    if not e or not e.get("items") or not e.get("source"): return None
    ref = datetime.fromisoformat(str(now)[:10]) if now else datetime.now(timezone.utc).replace(tzinfo=None)
    pts = []
    for it in e["items"]:
        if not it.get("date") or it.get("price") is None: continue
        age = (ref - datetime.fromisoformat(str(it["date"])[:10])).days
        pts.append((age, float(it["price"])))
    if not pts: return None
    out = {"source": e["source"], "source_url": e.get("source_url"),
           "collected_at": str(e.get("collected_at") or ""), "windows": {}, "n_total": len(pts)}
    for w in (30, 60, 90):
        v = [p for a, p in pts if a <= w]
        if v:
            m = _median(v)
            out["windows"][w] = {"n": len(v), "median": round(m, 2), "min": min(v), "max": max(v),
                                 "dispersion": round((max(v) - min(v)) / m * 100, 1) if m else None}
    # fenêtre de référence : la plus récente qui porte assez de ventes
    ref_w = next((w for w in (30, 60, 90) if out["windows"].get(w, {}).get("n", 0) >= 5), None)
    out["ref_window"] = ref_w
    if ref_w:
        d = out["windows"][ref_w]
        out["value"] = d["median"]
        n, disp = d["n"], d["dispersion"] or 0
        if n >= 6 and ref_w <= 30 and disp <= 50: out["confidence"] = "HIGH"
        elif n >= 5 and ref_w <= 60 and disp <= 80: out["confidence"] = "MEDIUM"
        else: out["confidence"] = "LOW"
    else:
        out["value"], out["confidence"] = None, "LOW"
    # tendance : simple constat, aucune prédiction
    a, b = out["windows"].get(30, {}).get("median"), out["windows"].get(90, {}).get("median")
    out["trend"] = "UNKNOWN"
    if a and b:
        delta = (a - b) / b * 100
        out["trend"] = "UP" if delta > 10 else "DOWN" if delta < -10 else "FLAT"
        out["trend_pct"] = round(delta, 1)
    return out

ASK_DEAL_PCT, DEAL_PCT, STRONG_PCT, FAIR_PCT = -20.0, -10.0, -20.0, 10.0

def current_ask_reference(conn, key, now=None, region="US", exclude_url=None):
    """Référence des PRIX DEMANDÉS, quand aucune vente réalisée n'est disponible.

    Ce n'est pas une valeur de marché : c'est « ce que les autres vendeurs demandent
    aujourd'hui ». L'offre jugée est exclue de sa propre référence — se comparer à soi-même
    ne prouve rien. Priorité au stock disponible ; les ruptures récentes ne servent de contexte
    que si le stock ne suffit pas à constituer un échantillon."""
    rows = conn.execute(
        "SELECT unit_price, seen_at, shop, available, url FROM observations "
        "WHERE exact_comp_key=? AND sealed=1 AND unit_price IS NOT NULL AND unit_price>0 "
        "AND COALESCE(market_region,'US')=?", (key, region)).fetchall()
    def age(sa):
        a = _age_days(sa, now)
        return 999 if a is None else a
    rows = [r for r in rows if age(r[1]) <= AGING_D and r[4] != exclude_url]
    ins = [r for r in rows if r[3]]
    used, basis = (ins, "in_stock") if len({r[2] for r in ins}) >= 3 else (rows, "in_stock+oos")
    if not used: return None
    vals = [r[0] for r in used]
    keep, dropped = _trim_outliers(vals)
    med = _median(keep)
    shops = len({r[2] for r in used})
    ages = [age(r[1]) for r in used]
    disp = round((max(keep) - min(keep)) / med * 100, 1) if med else None
    conf = "LOW"
    if shops >= 3 and min(ages) <= FRESH_D and (disp or 0) <= 80: conf = "HIGH" if shops >= 4 else "MEDIUM"
    elif shops >= 2 and min(ages) <= AGING_D: conf = "LOW"
    return {"region": region, "currency": "USD" if region == "US" else "EUR",
            "value": round(med, 2), "sample_size": len(keep), "shops": shops, "basis": basis,
            "confidence": conf, "dispersion": disp, "outliers": sorted(dropped),
            "age_days": min(ages), "freshness": freshness(min(ages)),
            "in_stock_n": len({r[2] for r in ins})}

def price_verdict(price, cm, ask_ref):
    """Deux niveaux de preuve, jamais confondus.

    SOLD-BACKED : l'écart se mesure contre des ventes RÉALISÉES -> STRONG BUY / BUY / FAIR / EXPENSIVE.
    ASK-BACKED  : aucune vente fiable, mais plusieurs vendeurs comparables -> ASK DEAL, qui dit
                  « moins cher que ce que les autres DEMANDENT », jamais « sous la valeur ».
    Sinon : DATA INSUFFICIENT. Un ASK DEAL n'est JAMAIS un BUY.
    """
    if price is None or price <= 0:
        return {"verdict": "DATA INSUFFICIENT", "basis": None, "gap": None, "ref": None,
                "why": "prix indisponible"}
    if cm and cm.get("basis") == "exact_sold" and cm.get("confidence") in ("HIGH", "MEDIUM") \
            and cm.get("value"):
        g = round((price - cm["value"]) / cm["value"] * 100, 1)
        v = ("STRONG BUY" if g <= STRONG_PCT else "BUY" if g <= DEAL_PCT
             else "FAIR" if g <= FAIR_PCT else "EXPENSIVE")
        n, w = cm.get("sample_size"), cm.get("window_days")
        return {"verdict": v, "basis": "sold", "gap": g, "ref": cm["value"],
                "confidence": cm["confidence"],
                "why": f"{n} vente(s) réalisée(s) sur {w} j · médiane ${cm['value']:.2f} · {cm['confidence']}"}
    if ask_ref and ask_ref["confidence"] in ("HIGH", "MEDIUM") and ask_ref.get("value"):
        g = round((price - ask_ref["value"]) / ask_ref["value"] * 100, 1)
        v = "ASK DEAL" if g <= ASK_DEAL_PCT else "ASK FAIR" if g <= FAIR_PCT else "ASK EXPENSIVE"
        return {"verdict": v, "basis": "ask", "gap": g, "ref": ask_ref["value"],
                "confidence": ask_ref["confidence"],
                "why": (f"{ask_ref['shops']} vendeur(s) · médiane demandée ${ask_ref['value']:.2f} · "
                        f"{ask_ref['confidence']} · AUCUNE VENTE RÉALISÉE CONNUE")}
    return {"verdict": "DATA INSUFFICIENT", "basis": None, "gap": None, "ref": None,
            "confidence": "LOW",
            "why": "ni vente réalisée fiable, ni assez de vendeurs comparables"}

VERDICT_RANK = {"STRONG BUY": 0, "BUY": 1, "ASK DEAL": 2, "ASK FAIR": 3, "FAIR": 3,
                "ASK EXPENSIVE": 4, "EXPENSIVE": 4, "DATA INSUFFICIENT": 5}

def buy_below_v2(cm: dict):
    """« À quel prix est-ce une bonne opportunité AUJOURD'HUI ? », pas « quel était un bon prix
    autrefois ». Dérivé du marché actuel et de sa confiance : on exige une marge plus large
    quand on est moins sûr. Sans marché fiable, pas de seuil — UNKNOWN plutôt qu'un chiffre.

    La phrase nomme la nature de la référence. Écrire « sous la médiane des ventes récentes »
    au-dessus d'un objectif calculé sur des prix DEMANDÉS serait précisément la confusion que
    tout ce moteur existe pour empêcher."""
    if not cm or cm.get("value") is None: return None, "aucun marché actuel fiable"
    quoi = "des prix demandés" if cm.get("basis") == "ask" else "des ventes récentes"
    conf = cm.get("confidence")
    if conf == "HIGH":   return round(cm["value"] * 0.90, 2), f"10 % sous la médiane {quoi}"
    if conf == "MEDIUM": return round(cm["value"] * 0.85, 2), f"15 % sous la médiane {quoi} (confiance moyenne)"
    return None, "confiance insuffisante pour fixer un seuil"

def current_market(conn, sku: dict, key: str, now=None, region: str = "US"):
    """Référence de marché ACTUELLE, distincte de historical_low.

    Hiérarchie : un sold récent et exact prime sur tout ; sinon les asks courants observés
    chez plusieurs boutiques ; sinon rien. On ne fabrique jamais une valeur à partir d'un
    historique ancien, et on ne convertit jamais un ask en sold.
    Cloisonné par exact_comp_key ET par région : une offre FR n'entre pas dans le marché US.
    """
    out = {"value": None, "basis": None, "sample_size": 0, "window_days": None,
           "confidence": "LOW", "freshness": "UNKNOWN", "dispersion": None,
           "shops": 0, "outliers": [], "age_days": None,
           # la zone et la devise voyagent avec la référence : un ask japonais ne se compare
           # pas à des ventes eBay US, et la valeur seule ne dit pas dans quelle monnaie elle est
           "region": region, "currency": "USD" if region == "US" else "EUR"}

    # 0) ventes réalisées datées : la meilleure base possible
    st = sold_stats(key, now) if region == "US" else None
    if st and st.get("value") is not None:
        w = st["ref_window"]; d = st["windows"][w]
        out.update(value=st["value"], basis="exact_sold", sample_size=d["n"], window_days=w,
                   confidence=st["confidence"], freshness=freshness(w), dispersion=d["dispersion"],
                   age_days=None)
        out["trend"] = st.get("trend"); out["sold_source"] = st["source"]
        out["windows"] = st["windows"]
        return out

    # 1) sold scalaire renseigné à la main, avec ses métadonnées
    sold, conf = sku.get("market_sold_us"), sold_confidence(sku)
    if sold is not None and conf in ("HIGH", "MEDIUM"):
        age = _age_days(sku.get("market_sold_checked_at"), now)
        out.update(value=float(sold), basis="exact_sold", sample_size=sku.get("market_sold_n") or 0,
                   window_days=sku.get("market_sold_window_days"), confidence=conf,
                   freshness=freshness(age), age_days=age)
        return out

    # 2) à défaut, les asks RÉELLEMENT observés chez nos boutiques, sur la même cloison
    rows = conn.execute(
        "SELECT unit_price, seen_at, shop, available FROM observations "
        "WHERE exact_comp_key=? AND sealed=1 AND unit_price IS NOT NULL AND unit_price>0 "
        "AND COALESCE(market_region,'US')=?", (key, region)).fetchall()
    # `_age_days(...) or 999` serait faux : une observation du JOUR MÊME vaut 0, qui est falsy,
    # et se ferait filtrer comme vieille de 999 jours.
    def _age(sa):
        a = _age_days(sa, now)
        return 999 if a is None else a
    fresh = [(u, sa, sh) for u, sa, sh, _ in rows if _age(sa) <= AGING_D]
    if not fresh:
        return out
    vals = [u for u, _, _ in fresh]
    keep, dropped = _trim_outliers(vals)
    med = _median(keep)
    shops = len({sh for _, _, sh in fresh})
    ages = [_age(sa) for _, sa, _ in fresh]
    disp = round((max(keep) - min(keep)) / med * 100, 1) if med else None
    # la confiance monte avec le nombre de boutiques distinctes et la fraîcheur, pas avec le
    # nombre de lignes : cinq annonces du même shop ne valent pas cinq boutiques.
    conf = "LOW"
    if shops >= 3 and min(ages) <= FRESH_D and (disp or 0) <= 60: conf = "MEDIUM"
    out.update(value=round(med, 2), basis="observed_ask", sample_size=len(keep),
               window_days=AGING_D, confidence=conf, freshness=freshness(min(ages)),
               dispersion=disp, shops=shops, outliers=sorted(dropped), age_days=min(ages))
    return out

def historical_low(conn, key, upto=None, region="US"):
    """Plus bas prix UNITAIRE jamais observé pour cette cloison de comparabilité.
    C'est un FAIT HISTORIQUE, jamais une valeur de marché : il ne sert qu'à surveiller un retour
    en stock. Strictement cloisonné par exact_comp_key et réservé aux lignes sealed=1 — un single,
    une autre configuration ou un lot de quantité différente ne peut pas le contaminer."""
    q = ("SELECT unit_price, seen_at, shop FROM observations "
         "WHERE exact_comp_key=? AND sealed=1 AND unit_price IS NOT NULL AND unit_price > 0 "
         "AND COALESCE(market_region,'US')=?")
    args = [key, region]
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
    # Un prix à 0 n'est pas un prix : précommande, fiche sans tarif, variante placeholder.
    # Il produisait un STRONG_DEAL à -100 % (bleecker, run du 19/08). Aucun déclencheur possible.
    if not o[3] or o[3] <= 0:
        return [], ["NO_PRICE"], None, None, None
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

def best_fr(entries):
    """Meilleure offre FR par cloison de comparabilité.

    BEST FR = l'offre EXACTEMENT comparable la moins chère ACTUELLEMENT EN STOCK. Une offre en
    rupture ne gagne jamais. Un pack ne gagne jamais contre une boîte — exact_comp_key l'interdit
    déjà. Pour un lot, c'est l'unitaire qui départage, le total reste affiché.

    Ce n'est PAS une valeur de marché : ça répond à « où acheter en France aujourd'hui ? »,
    jamais à « combien vaut cette boîte ? »."""
    by_key = {}
    for e in entries:
        if e.get("region") != "FR" or not e["available"]: continue
        o = e["o"]
        if not o[3] or o[3] <= 0: continue
        k = e.get("key")
        by_key.setdefault(k, []).append(e)
    out = {}
    for k, offers in by_key.items():
        offers.sort(key=lambda e: (e["o"][12] or e["o"][3]))
        best = offers[0]
        out[k] = {"price": best["o"][3], "unit": best["o"][12] or best["o"][3], "shop": best["o"][1],
                  "url": best["o"][5], "qty": best["o"][11] or 1, "checked_at": best["o"][7],
                  "currency": best.get("currency", "EUR"), "others": len(offers) - 1,
                  "all": [(e["o"][1], e["o"][3]) for e in offers]}
    return out

def fr_market_status(health, sources):
    """Une panne d'un vendeur FR ne supprime pas le marché FR, mais on ne laisse pas croire que
    les trois ont été vérifiés."""
    fr = [x["key"] for x in sources if x.get("market_region") == "FR"]
    bad = [k for k in fr if health.get(k, ("UNKNOWN",))[0] not in ("HEALTHY",)]
    if not fr: return None
    if not bad: return f"FR MARKET COMPLET ({len(fr)} source(s))"
    return f"FR MARKET PARTIAL — {len(fr) - len(bad)}/{len(fr)} source(s) vérifiée(s) : " + ", ".join(
        f"{k} {health.get(k, ('UNKNOWN', ''))[0]}" for k in bad)

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
    # HOT NOW est une décision sur le marché US : une offre FR est un canal d'achat, pas un
    # signal de marché, et son prix est en euros. Le garde-fou est ICI, pas au point d'appel.
    # Une opportunité entre dans HOT NOW si elle est adossée à une PREUVE : des ventes
    # réalisées (sold-backed) ou, à défaut, plusieurs vendeurs comparables (ask-backed).
    # Un ASK DEAL n'est jamais un BUY, et ne passe jamais devant un deal sold-backed.
    KEEP = {"STRONG BUY", "BUY", "ASK DEAL"}
    elig = []
    for e in entries:
        if e.get("region", "US") != "US" or not e["available"]: continue
        if not e["o"][3] or e["o"][3] <= 0: continue
        pv = e.get("pv") or {}
        if pv.get("verdict") in KEEP:
            elig.append(e); continue
        # Un verdict de marché adverse est SANS APPEL : ni restock, ni plus-bas historique, ni
        # seuil manuel ne remontent une offre que les ventes ou les prix demandés condamnent.
        # Le Topps Chrome à 75 $ entrait ici par un -38 % vs seuil manuel, alors que sept ventes
        # réelles le donnaient à 64 $.
        if pv.get("verdict") and pv["verdict"] != "DATA INSUFFICIENT": continue
        # sans aucune preuve de marché, les déclencheurs historiques restent recevables
        if e["triggers"] and e["ref"] is not None and e["gap"] is not None and e["gap"] <= 0:
            elig.append(e)
    elig.sort(key=lambda e: (VERDICT_RANK.get((e.get("pv") or {}).get("verdict"), 5),
                             -len(e["triggers"]),
                             (e.get("pv") or {}).get("gap") if (e.get("pv") or {}).get("gap") is not None
                             else (e["gap"] if e["gap"] is not None else 0)))
    # une place HOT par produit : quatre shops sur le même EuroLeague Blaster, c'est UNE ligne
    # et trois autres offres, pas quatre alertes.
    best_by_key, others = [], {}
    for e in elig:
        k = e.get("key") or e["sid"]
        if k in others:
            others[k] += 1
        else:
            others[k] = 0; best_by_key.append(e)
    for e in best_by_key: e["other_offers"] = others[e.get("key") or e["sid"]]
    return best_by_key[:limit]

def threshold_vs_market(sku: dict, cm: dict):
    """Un seuil manuel qui a décroché du marché actuel doit être signalé, jamais réécrit en
    silence. Constaté le 23/08 : buy_below 35 $ face à des ventes récentes médianes à 64 $ —
    le seuil rendait invisible toute offre entre 35 et 64 $."""
    b = sku.get("buy_below_usd")
    if b is None or not cm or cm.get("value") is None or cm.get("confidence") == "LOW":
        return None
    ratio = float(b) / cm["value"]
    if ratio < 0.6: return ("OBSOLETE_LOW", f"seuil {b:.2f} $ contre un marché à {cm['value']:.2f} $ "
                                            f"— trop bas de {100 * (1 - ratio):.0f} %, plus aucune offre ne peut le franchir")
    if ratio > 1.1: return ("OBSOLETE_HIGH", f"seuil {b:.2f} $ AU-DESSUS du marché à {cm['value']:.2f} $ "
                                             f"— déclencherait un achat au-dessus des ventes réelles")
    return None

def threshold_coherent(sku: dict) -> bool:
    """Un seuil d'achat au-dessus des ventes réalisées n'est pas un seuil : il ordonnerait
    d'acheter plus cher que le marché. Vécu le 22/08 sur Phoenix Blaster — le sold sourcé est
    passé de 28,50 à 20,00 et le buy de 27,00 est devenu incohérent. On ne recalcule jamais un
    seuil (doctrine Q), mais un seuil incohérent ne peut plus produire de GO."""
    sold, buy = sku.get("market_sold_us"), sku.get("buy_below_usd")
    if sold is None or buy is None: return True
    return float(buy) <= float(sold)

def decide(status_active, gap, conf, comp, buy_below, price, sku=None):
    """GO exige : SKU ACTIVE, comparaison EXACT, sold_confidence >= MEDIUM, et prix sous le seuil.
    Sans sold fiable, une anomalie de prix reste une anomalie — jamais un ordre d'achat."""
    if not status_active: return None
    under = buy_below is not None and price <= buy_below
    if not under: return None
    if sku is not None and not threshold_coherent(sku):
        return "SEUIL À REVOIR — buy au-dessus du sold"
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
      SELECT o.sku_id, o.shop, o.title, o.price, o.available, o.url, o.match_score, o.seen_at, o.variant_title, o.comp_type, o.image_url, o.quantity, o.unit_price, o.exact_comp_key, COALESCE(o.market_region,'US'), COALESCE(o.currency,'USD')
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
            # buy_below_usd est explicitement null sur les SKU WATCH/CANDIDATE : .get(clé, 0)
            # renvoie None et non 0. Sans seuil, un restock n'est jamais un « restock deal ».
            bb = skus.get(r[0], {}).get("buy_below_usd")
            deal = bb is not None and r[3] is not None and r[3] <= bb
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
                    key = o[13] if len(o) > 13 and o[13] else exact_comp_key(sid, norm(o[2]), s, o[5])
                    hist = historical_low(conn, key, o[7])
                    reg = o[14] if len(o) > 14 else "US"
                    cmk = current_market(conn, s, key, region=reg) if reg == "US" else None
                    askr = current_ask_reference(conn, key, region=reg, exclude_url=o[5]) if reg == "US" else None
                    pv = price_verdict(o[3], cmk, askr) if reg == "US" else None
                    region = o[14] if len(o) > 14 else "US"
                    if region != "US":
                        # un vendeur FR est un canal d'achat, pas un signal de marché US :
                        # comparer un prix EUR à un ask USD n'aurait aucun sens.
                        tg, dsc = [], dsc + ["FR"]
                    entries.append({"o": o, "key": key, "hist": hist, "region": region,
                                    "cm": cmk, "ask_ref": askr, "pv": pv,
                                    "currency": (o[15] if len(o) > 15 else "USD"),
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
                    d = decide(True, None, conf, by_line[id(best)]["comp"], s.get("buy_below_usd"), best[3], s)
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
                age, stale = threshold_age(s, seen_at)
                tinfo = ("  ⏳ STALE THRESHOLD" + (f" ({age} j)" if age is not None else " (jamais revu)")) if stale else ""
                print(f"   ask {money(ask):<8} sold {money(sold):<8}{prov} | buy ≤ {money(s.get('buy_below_usd')):<8} | watch ≤ {money(s.get('watch_below_usd')):<8} | EU {money(eu, '€')}{tinfo}")
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
    fr_best = best_fr(all_entries)
    hn = hot_now([e for e in all_entries if e.get("region", "US") == "US"])
    print("\n" + "="*72 + f"\n  🔥 HOT NOW — {len(hn)} ligne(s)\n" + "="*72)
    for e in hn:
        o = e["o"]
        extra = f"  (+{e['other_offers']} autre(s) offre(s))" if e.get("other_offers") else ""
        pv = e.get("pv") or {}
        # l'écart affiché est celui du verdict quand il existe ; sinon celui du déclencheur
        g = pv.get("gap") if pv.get("gap") is not None else e["gap"]
        gs = f"{g:>6.1f}%" if g is not None else "     —"
        tag = {"sold": "[ventes]", "ask": "[demandés]"}.get(pv.get("basis"), "")
        print(f"  {sku_label(e['sku'])[:44]:<46} ${o[3]:>8.2f} {o[1]:<16} {gs} {tag:<10} "
              + " ".join(e["triggers"]) + extra)
    if not hn: print("  (aucune ligne en stock ne cumule un déclencheur et une référence de marché)")
    frs = fr_market_status(health, yaml.safe_load((ROOT/"sources.yaml").read_text(encoding="utf-8"))["shops"])
    if fr_best:
        print("\n" + "="*72 + f"\n  🇫🇷 MARCHÉ FR — {len(fr_best)} produit(s) avec une offre en stock\n" + "="*72)
        if frs: print(f"  {frs}")
        for k, b in sorted(fr_best.items(), key=lambda x: x[1]["unit"])[:20]:
            extra = f"  (+{b['others']} autre(s) offre(s) FR)" if b["others"] else ""
            print(f"  {k.split('|')[0].replace('PANINI_','').replace('TOPPS_','')[:38]:<40} "
                  f"€{b['unit']:>8.2f}  {b['shop']:<12}{extra}")
    write_html(cat, html, restocks, q, seen_at, trust, hn, all_entries, SHOP_COUNTS, health, fr_best)
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

# ---------------------------------------------------------------- restitution : cockpit
# Doctrine UX : CONCLUSION FIRST, EVIDENCE SECOND, ENGINE LAST.
# Aucune règle moteur n'est touchée ici : on ne fait que hiérarchiser ce qu'il a calculé.

# (clé, titre de section, formulation courte pour l'état vide)
WEMBY_SECTIONS = [("rc",     "🏀 Wemby Rookie 23/24",      "sur Wemby Rookie 23/24"),
                  ("y2",     "⭐ Wemby Year 2 24/25",       "sur Wemby Year 2 24/25"),
                  ("trophy", "💎 Wemby Premium / Trophy",   "sur Premium / Trophy"),
                  ("autre",  "📦 Autres opportunités",      "hors Wemby")]

def wemby_bucket(s: dict) -> str:
    """Priorité d'AFFICHAGE uniquement. N'influence ni le calcul du deal, ni la référence
    marché, ni les badges, ni la confiance."""
    if s.get("trophy") or s.get("program") == "hot_box": return "trophy"
    if s.get("wemby_year2"): return "y2"
    if s.get("wemby_rc") and s.get("season") == "2023-24": return "rc"
    return "autre"

def gap_phrase(e) -> str:
    """Jamais « -18 % marché » : la nature de la référence doit être lisible."""
    if e.get("ref") is None or e.get("gap") is None: return "Marché insuffisant"
    return f"{e['gap']:+.0f} % vs {e['kind']}"

def landed_phrase(price, qty, cat) -> str:
    """Convention UNIQUE pour les lots et les cases : le total ET l'unitaire, toujours dans
    cet ordre. La page mélangeait trois conventions (€/boîte, case entière, €/boîte)."""
    if not price: return "—"
    if qty and qty > 1:
        return (f"case €{landed_eur(price / qty, cat) * qty:.2f} · "
                f"€{landed_eur(price / qty, cat):.2f}/boîte")
    return f"€{landed_eur(price, cat):.2f}"

def money_or(v, dash="—"): 
    try: return f"${float(v):.2f}"
    except (TypeError, ValueError): return dash

def buy_target(s: dict) -> float | None:
    b = s.get("buy_below_usd")
    return float(b) if b is not None else None

def near_buy_lines(entries):
    """En stock, un seuil d'achat existe, et le prix est au-dessus : combien manque-t-il ?"""
    best = {}
    for e in entries:
        if not e["available"] or not e["o"][3] or e["o"][3] <= 0: continue
        b = buy_target(e["sku"])
        if b is None or e["o"][3] <= b: continue
        if not ref_is_usable(e): continue      # référence auto-sourcée -> Explorer, pas Surveiller
        # une ligne par produit : c'est l'offre la MOINS chère qui dit ce qu'il reste à attendre.
        # Sans cette déduplication, un produit vendu par 5 shops occupe 5 lignes de la même
        # information, et la section redevient un catalogue.
        k = e.get("key") or e["sid"]
        if k not in best or e["o"][3] < best[k]["o"][3]: best[k] = e
    out = [(e["o"][3] - buy_target(e["sku"]), e) for e in best.values()]
    out.sort(key=lambda x: (x[0], x[0] / buy_target(x[1]["sku"])))
    return out

def restock_lines(entries):
    """OOS avec un historique ET un seuil : ce qu'on guette au retour en stock."""
    seen, out = set(), []
    for e in entries:
        if e["available"] or not e.get("hist"): continue
        k = e.get("key")
        if k in seen: continue
        seen.add(k)
        if buy_target(e["sku"]) is None: continue
        out.append(e)
    out.sort(key=lambda e: e["hist"]["low"] - (buy_target(e["sku"]) or 0))
    return out

def why_phrase(e) -> str:
    """Les raisons secondaires, en clair, sans jargon interne."""
    bits = []
    for t in e["triggers"]:
        if t.startswith("RESTOCK"): bits.append("retour en stock" + t.replace("RESTOCK", "").replace("j", " j"))
        elif t == "NEW_LOW": bits.append("plus bas jamais vu")
        elif t.startswith("PRICE_DROP"): bits.append("baisse " + t.split()[-1])
        elif t == "SEUL_EN_STOCK": bits.append("seul en stock")
    for d in e["descriptors"]:
        if d.startswith("cheapest"): bits.append(d.replace("cheapest of", "le moins cher sur").replace("in stock", "en stock"))
    if e.get("other_offers"): bits.append(f"{e['other_offers']} autre(s) offre(s)")
    return " · ".join(bits)

@dataclass
class Opportunity:
    """Structure de données d'une opportunité. Le rendu HTML en découle — jamais l'inverse.
    C'est ce qui permettra d'insérer le bloc FR Market ou des alertes sans refondre la page :
    on ajoutera des champs ici, les gabarits suivront."""
    kind: str                      # "buy" | "near" | "restock"
    bucket: str                    # rc | y2 | trophy | autre
    sku: dict
    label: str
    shop: str
    url: str
    image: str | None
    price: float | None
    qty: int
    verdict: str                   # STRONG DEAL | DEAL | SIGNAL | WATCH | RESTOCK
    market: str                    # "-27 % vs ask" ou "Marché insuffisant"
    ref_kind: str | None           # sold | ask | None
    ref_ok: bool                   # référence non auto-sourcée -> exploitable pour attendre
    buy_below: float | None
    missing: float | None          # ce qu'il reste à attendre
    hist_low: float | None
    hist_at: str | None
    why: str
    landed: str
    other_offers: int
    # emplacements réservés, non alimentés tant que la couche FR n'existe pas
    evidence: str | None = None
    buy_target_v2: float | None = None   # seuil dérivé du marché actuel, quand il existe
    target_why: str | None = None
    # Préparation multi-devises. Une référence de marché n'a de sens que dans SA zone : on ne
    # compare pas un ask japonais à des ventes eBay US. Les champs existent pour que l'ajout
    # d'un shop non-US soit une question de collecte, pas de refonte du scoring.
    region: str = "US"             # zone du marché auquel l'offre est comparée
    currency: str = "USD"          # devise d'affichage de native_price
    native_price: float | None = None   # prix tel que l'annonce l'affiche
    usd_price: float | None = None      # même prix converti, ou None si aucun taux fiable
    fr_price_eur: float | None = None
    fr_source: str | None = None
    fr_url: str | None = None
    fr_other_offers: int = 0
    fr_checked_at: str | None = None

def opportunity(e, kind, cat, fr_best=None) -> Opportunity:
    s_ = e["sku"]; o = e["o"]
    q = (o[11] if len(o) > 11 and o[11] else 1) or 1
    b = buy_target(s_)
    price = o[3]
    pv = e.get("pv") or {}
    # Le seuil qui compte est celui que le marché actuel justifie ; le seuil manuel n'est plus
    # qu'un contexte. On dérive donc l'objectif de prix de la référence qui a rendu le verdict.
    _ref = pv.get("ref")
    _refv = _ref.get("value") if isinstance(_ref, dict) else _ref
    tgt, tgt_why = (buy_below_v2({"value": _refv, "confidence": pv.get("confidence"),
                                  "basis": pv.get("basis")})
                    if _refv else (None, None))
    ICON = {"STRONG BUY": "🔥 STRONG BUY", "BUY": "🟢 BUY", "ASK DEAL": "🟣 ASK DEAL",
            "FAIR": "⚪ FAIR", "ASK FAIR": "⚪ ASK FAIR", "EXPENSIVE": "🔴 EXPENSIVE",
            "ASK EXPENSIVE": "🔴 ASK EXPENSIVE", "DATA INSUFFICIENT": "❓ DATA INSUFFICIENT"}
    verdict = ICON.get(pv.get("verdict")) or (
        "RESTOCK" if kind == "restock" else "WATCH" if kind == "near" else "SIGNAL")
    hist = e.get("hist")
    return Opportunity(
        kind=kind, bucket=wemby_bucket(s_), sku=s_, label=sku_label(s_), shop=o[1], url=o[5],
        image=(o[10] if len(o) > 10 else None), price=price, qty=q, verdict=verdict,
        region=e.get("region", "US"), currency=e.get("currency", "USD"),
        native_price=price, usd_price=(price if e.get("currency", "USD") == "USD" else None),
        market=(f"{pv['gap']:+.0f} % vs {'ventes réalisées' if pv.get('basis') == 'sold' else 'prix demandés'}"
                if pv.get("gap") is not None else gap_phrase(e)),
        evidence=pv.get("why"), ref_kind=e.get("kind"), ref_ok=ref_is_usable(e),
        buy_below=b, buy_target_v2=tgt, target_why=tgt_why,
        # « Attendre » se calcule sur le seuil dérivé du marché quand il existe. Le seuil manuel
        # ne pilote plus le verdict : il ne doit pas piloter davantage l'objectif de prix.
        missing=((price - tgt) if (tgt is not None and price and price > tgt)
                 else (price - b) if (tgt is None and b is not None and price and price > b)
                 else None),
        hist_low=(hist["low"] if hist else None), hist_at=(hist["at"][:10] if hist else None),
        why=why_phrase(e), landed=landed_phrase(price, q, cat),
        other_offers=e.get("other_offers", 0), **_fr_fields(e, fr_best))

def _fr_fields(e, fr_best):
    """Le bloc FR est une information de CANAL D'ACHAT, jamais une valeur de marché.
    On ne convertit rien : le prix FR reste en euros, le prix US en dollars."""
    b = (fr_best or {}).get(e.get("key"))
    if not b: return {}
    return {"fr_price_eur": b["unit"], "fr_source": b["shop"], "fr_url": b["url"],
            "fr_other_offers": b["others"], "fr_checked_at": b["checked_at"][:10]}

def ref_is_usable(e) -> bool:
    """3 — anti-circularité. Un seuil adossé à une référence relevée chez CE seul shop ne permet
    pas de dire « attends -X $ » : on comparerait le prix du shop à son propre prix. La carte
    reste visible, mais dans Explorer, pas dans Surveiller."""
    if e.get("ref") is None: return False
    if e.get("kind") == "sold": return True
    froms = e["sku"].get("market_ask_from") or []
    if not froms: return False
    return not (len(froms) == 1 and froms[0] == e["o"][1])

def render_card(op: Opportunity) -> str:
    """Gabarit unique. Toute nouvelle information (FR Market, alerte) s'ajoute ici."""
    img = (f"<img class=th src='{op.image}' alt='{(op.label or '')[:80]}' loading=\"lazy\" "
           f"width=56 height=56>") if op.image else ""
    r = [f"<div class=card>{img}<div class=cb>",
         f"<div class=nm>{op.label}</div>",
         f"<div class=pr>{money_or(op.price)} <span class=shop>· {op.shop}</span></div>",
         f"<div><span class='v'>{op.verdict}</span> <span class=gap>{op.market}</span></div>"]
    if op.evidence:
        r.append(f"<div class=small>{op.evidence}</div>")
    if op.buy_below is not None:
        r.append(f"<div class=small>🎯 Seuil manuel ≤ {money_or(op.buy_below)} "
                 "<span class=small>(contexte, ne pilote plus le verdict)</span></div>")
    if op.missing is not None and op.ref_ok:
        tgt = op.buy_target_v2 if op.buy_target_v2 is not None else op.buy_below
        src = (f"objectif {money_or(tgt)} — {op.target_why}" if op.buy_target_v2 is not None
               else f"objectif {money_or(tgt)} — seuil manuel")
        r.append(f"<div class=small><span class=miss>→ attendre {money_or(op.missing)}</span> "
                 f"<span class=small>({src})</span></div>")
    if op.hist_low is not None:
        r.append(f"<div class=small>Plus bas déjà vu : {money_or(op.hist_low)}"
                 + (f" ({op.hist_at})" if op.hist_at else "") + "</div>")
    if op.qty > 1:
        r.append(f"<div class=small>{op.qty} boîtes · {op.landed}</div>")
    if op.why:
        r.append(f"<div class=small>Pourquoi ? {op.why}</div>")
    if op.fr_price_eur is not None:
        # US et FR côte à côte, chacun dans sa devise : aucune conversion silencieuse.
        extra = f" · +{op.fr_other_offers} autre(s) offre(s) FR" if op.fr_other_offers else ""
        link = A(op.fr_url, "voir FR") if op.fr_url else ""
        r.append(f"<div class=small>🇫🇷 €{op.fr_price_eur:.2f} · {op.fr_source or ''}{extra} {link}</div>")
    r.append(f"<div>{A(op.url, 'Voir l’offre', 'cta')}</div></div></div>")
    return "".join(r)

def buy_card(e) -> str:
    o = e["sku"]; l = e["o"]
    verdict = "🟢 STRONG DEAL" if any(t.startswith("STRONG_DEAL") for t in e["triggers"]) else (
              "🟢 DEAL" if any(t.startswith("DEAL") for t in e["triggers"]) else "🔵 SIGNAL")
    b = buy_target(o)
    why = why_phrase(e)
    return (f"<div class=card>{thumb(e, True)}<div class=cb>"
            f"<div class=nm>{sku_label(o)}</div>"
            f"<div class=pr>{money_or(l[3])} <span class=shop>· {l[1]}</span></div>"
            f"<div><span class='v'>{verdict}</span> <span class=gap>{gap_phrase(e)}</span></div>"
            + (f"<div class=small>🎯 Acheter ≤ {money_or(b)}</div>" if b else "")
            + (f"<div class=small>Pourquoi ? {why}</div>" if why else "")
            + f"<div>{A(l[5], 'Voir l’offre', 'cta')}</div></div></div>")

def empty_note(label, watched, best=None):
    txt = f"<p class=empty>Aucune opportunité {label} actuellement."
    if watched:
        txt += f"<br><span class=small>👀 {watched} produit(s) surveillé(s)"
        if best: txt += f" · meilleur candidat : {best}"
        txt += "</span>"
    return txt + "</p>"

def write_html(cat, blocks, restocks, review, seen_at, trust=None, hot=None, entries=None,
               shopcount=None, health=None, fr_best=None):
    trust = trust or {}; hot = hot or []; entries = entries or []
    shopcount = shopcount or []; health = health or {}; fr_best = fr_best or {}
    nb = cat["landed_cost"].get("bundle_boxes", 8)
    h = ["<!doctype html><meta charset='utf-8'><meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>Wemby Hunt</title><style>",
         ":root{--bg:#fff;--fg:#141414;--mut:#6b6b6b;--line:#e6e6e6;--card:#fafafa;--go:#0f7b3d;--warn:#8a5a00}",
         "@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#ededed;--mut:#9a9a9a;--line:#2a2a2a;--card:#191919}}",
         "*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;",
         "max-width:720px;margin:0 auto;padding:12px 12px 48px;color:var(--fg);background:var(--bg);line-height:1.45}",
         "h1{font-size:1.3rem;margin:.1em 0}h2{font-size:1.1rem;margin:1.5em 0 .4em}",
         "h3{font-size:.92rem;margin:1.1em 0 .4em;color:var(--fg)}",
         ".small{color:var(--mut);font-size:.8rem}.empty{color:var(--mut);font-size:.85rem;margin:.4em 0 1em}",
         ".lede{font-size:1.02rem;margin:.3em 0 .2em}",
         "nav{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:9}",
         "nav a{display:inline-block;margin-right:14px;font-size:.88rem;text-decoration:none;color:var(--fg)}",
         ".kpis{display:flex;gap:8px;margin:10px 0 4px}",
         ".kpi{flex:1;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;text-align:center}",
         ".kpi b{display:block;font-size:1.3rem}.kpi span{font-size:.7rem;color:var(--mut);text-transform:uppercase}",
         ".card{display:flex;gap:10px;border:1px solid var(--line);border-radius:12px;padding:10px;",
         "margin:8px 0;background:var(--card)}.cb{flex:1;min-width:0}",
         ".th{border-radius:8px;object-fit:cover;flex:0 0 56px;background:var(--line)}",
         ".nm{font-weight:600;font-size:.95rem}.pr{font-size:1.15rem;font-weight:700;margin:.15em 0}",
         ".shop{font-size:.85rem;font-weight:400;color:var(--mut)}",
         ".v{background:var(--go);color:#fff;font-size:.72rem;font-weight:700;padding:2px 7px;border-radius:99px}",
         ".gap{font-size:.8rem;color:var(--mut);margin-left:4px}",
         ".cta{display:inline-block;margin-top:6px;font-size:.82rem;font-weight:600;",
         "border:1px solid var(--fg);border-radius:8px;padding:4px 10px;text-decoration:none}",
         ".row{border-bottom:1px solid var(--line);padding:7px 0;font-size:.86rem}",
         ".row b{font-weight:600}.miss{color:var(--warn);font-weight:600}",
         "details{margin:.4em 0}summary{cursor:pointer;color:var(--mut);font-size:.85rem;padding:4px 0}",
         "table{width:100%;border-collapse:collapse}td,th{padding:4px 6px;border-bottom:1px solid var(--line);",
         "text-align:left;font-size:.78rem}.oos{color:var(--mut)}.wrap{overflow-x:auto}a{color:inherit}",
         "</style>",
         "<h1>🏀 Wemby Hunt</h1>",
         (f"<p class=small>Dernier passage : {seen_at[:16].replace('T', ' ')} UTC</p>"
          if seen_at else "<p class=small>Rapport hors passage (--report)</p>"),
         "<nav>" + " ".join(f"<a href='#{i}'>{n}</a>" for i, n in
                            [("acheter", "🔥 Acheter"), ("surveiller", "👀 Surveiller"),
                             ("fr", "🇫🇷 FR"), ("explorer", "🔎 Explorer"),
                             ("diag", "⚙️ Diagnostic")]) + "</nav>"]

    # ---------------- regroupements
    near = near_buy_lines(entries)
    restk = restock_lines(entries)
    # 2 : une seule source de vérité. La phrase de synthèse, les compteurs et les cartes
    # dérivent tous des MÊMES listes d'objets — impossible d'annoncer 2 et d'en afficher 3.
    ops_buy = [opportunity(e, "buy", cat, fr_best) for e in hot]
    ops_near = [opportunity(e, "near", cat, fr_best) for _, e in near]
    ops_rest = [opportunity(e, "restock", cat, fr_best) for e in restk]
    nb_buy = len(ops_buy)
    rc = len([op for op in ops_buy if op.bucket == "rc"])
    watch_by = {k: 0 for k, _, _ in WEMBY_SECTIONS}
    for op in ops_near + ops_rest: watch_by[op.bucket] += 1

    # ---------------- C : aujourd'hui, une phrase issue des seules données
    if nb_buy == 0:
        lede = "Aucun achat recommandé aujourd’hui."
        if ops_near: lede += f" {len(ops_near)} produit(s) au-dessus de leur prix cible."
    else:
        lede = f"{nb_buy} opportunité(s) vérifiée(s) aujourd’hui."
        lede += f" {rc} sur Wemby Rookie 23/24." if rc else " Aucune sur Wemby Rookie 23/24."
    h.append(f"<h2>🔥 Aujourd’hui</h2><p class=lede>{lede}</p>")
    h.append("<div class=kpis>"
             f"<div class=kpi><b>{nb_buy}</b><span>à acheter</span></div>"
             f"<div class=kpi><b>{len(ops_near)}</b><span>à surveiller</span></div>"
             f"<div class=kpi><b>{len(ops_rest)}</b><span>restock</span></div></div>")

    # ---------------- D : ACHETER (rendu depuis les objets Opportunity)
    h.append("<h2 id=acheter>🔥 Acheter</h2>")
    for key, label, short in WEMBY_SECTIONS:
        grp = [op for op in ops_buy if op.bucket == key]
        h.append(f"<h3>{label}</h3>")
        if grp:
            h += [render_card(op) for op in grp]
        else:
            cands = [op for op in ops_near if op.bucket == key]
            best = (f"{cands[0].label} — {money_or(cands[0].missing)} au-dessus du seuil"
                    if cands else None)
            h.append(empty_note(short, watch_by[key], best))

    # ---------------- H/I/J : SURVEILLER
    h.append("<h2 id=surveiller>👀 Surveiller</h2>")
    h.append("<h3>🎯 Proche du prix d’achat</h3>")
    if ops_near:
        h += [render_card(op) for op in ops_near[:12]]
    else:
        h.append("<p class=empty>Aucun produit en stock au-dessus de son prix cible "
                 "avec une référence marché exploitable.</p>")
    h.append("<h3>🔔 À guetter au restock</h3>")
    if ops_rest:
        h += [render_card(op) for op in ops_rest[:12]]
        h.append("<p class=small>Un prix historique est une cible de surveillance, "
                 "jamais une valeur de marché.</p>")
    else:
        h.append("<p class=empty>Aucun produit en rupture avec une cible d’achat définie.</p>")

    # ---------------- 🇫🇷 marché FR
    h.append(f"<h2 id=fr>🇫🇷 Marché FR — {len(fr_best)} produit(s) en stock</h2>")
    frs = fr_market_status(health, yaml.safe_load((ROOT/"sources.yaml").read_text(encoding="utf-8"))["shops"])
    if frs: h.append(f"<p class=small>{frs}</p>")
    h.append("<p class=small>Meilleur prix achetable en France. Ce n'est pas une valeur de marché : "
             "ces prix n'alimentent ni market_sold, ni market_ask, ni aucun seuil.</p>")
    if fr_best:
        sk_by_id = {x["id"]: x for x in cat["skus"]}
        h.append("<div class=wrap><table><tr><th>Produit</th><th>Best FR</th><th>Shop</th>"
                 "<th>Autres offres</th></tr>")
        for k, b in sorted(fr_best.items(), key=lambda x: x[1]["unit"]):
            sk = sk_by_id.get(k.split("|")[0])
            lbl = sku_label(sk) if sk else k.split("|")[0]
            oth = " · ".join(f"{sh} €{pr:.2f}" for sh, pr in b["all"][1:]) or "—"
            h.append(f"<tr><td>{A(b['url'], lbl[:46])}</td><td>€{b['unit']:.2f}"
                     + (f" <span class=small>({b['qty']} boîtes, total €{b['price']:.2f})</span>" if b["qty"] > 1 else "")
                     + f"</td><td>{b['shop']}</td><td class=small>{oth}</td></tr>")
        h.append("</table></div>")
    else:
        h.append("<p class=empty>Aucune offre FR en stock sur un produit du catalogue.</p>")

    # ---------------- K/L : EXPLORER
    h.append("<h2 id=explorer>🔎 Explorer le marché</h2>")
    by_sid = {}
    for e in entries: by_sid.setdefault(e["sid"], []).append(e)
    for key, label, _short in WEMBY_SECTIONS:
        grp = [b for b in blocks if wemby_bucket(b[3]) == key]
        if not grp: continue
        h.append(f"<details><summary>{label} — {len(grp)} produit(s)</summary>")
        for b in grp:
            s = b[3]; obs = by_sid.get(s["id"], [])
            ins = [e for e in obs if e["available"] and e["o"][3]]
            prices = sorted(e["o"][3] for e in ins)
            rng = (money_or(prices[0]) if len(prices) == 1
                   else f"{money_or(prices[0])}–{money_or(prices[-1])}") if prices else "—"
            shops = len({e["o"][1] for e in ins})
            sold = s.get("market_sold_us")
            conf = sold_confidence(s)
            ref_txt = (f"sold {money_or(sold)}" + (f" ({conf})" if conf else "")) if sold is not None else (
                      f"ask {money_or(s.get('market_ask_us'))}" if s.get("market_ask_us") and s.get("market_ask_from")
                      else "⚪ marché insuffisant")
            h.append(f"<div class=row><b>{sku_label(s)}</b><br><span class=small>"
                     f"{rng} · {shops} shop(s) en stock · {ref_txt} · "
                     f"🎯 {money_or(buy_target(s), 'pas de seuil')} · {b[1]}</span>"
                     + detail_block(s, obs, cat, nb) + "</div>")
        h.append("</details>")

    # ---------------- N : DIAGNOSTIC
    h.append("<h2 id=diag>⚙️ Diagnostic</h2>")
    anomalies = {k: v for k, v in health.items() if v[0] not in ("HEALTHY", "SKIPPED", "UNKNOWN")}
    h.append(f"<p class=small>{len(anomalies)} anomalie(s) de source · "
             + " · ".join(f"{n} {st}" for st, n in
                          __import__("collections").Counter(v[0] for v in health.values()).most_common()) + "</p>")
    if anomalies:
        h.append("<ul class=small>" + "".join(f"<li>{k} : {v[0]} — {v[1]}</li>" for k, v in sorted(anomalies.items())) + "</ul>")
    stale = [s for s in cat["skus"] if threshold_age(s, seen_at)[1]]
    if stale:
        h.append(f"<details><summary>⏳ Seuils périmés — {len(stale)}</summary><p class=small>"
                 + ", ".join(sku_label(s) for s in stale[:30]) + "</p></details>")
    h.append(f"<details><summary>Compteurs par source — {len(shopcount)}</summary><div class=wrap><table>"
             "<tr><th>Shop</th><th>trust</th><th>bruts</th><th>matchés</th></tr>"
             + "".join(f"<tr><td>{k}</td><td>{tr}</td><td>{raw}</td><td>{mt}</td></tr>"
                       for k, tr, raw, mt in shopcount) + "</table></div></details>")
    if review:
        h.append(f"<details><summary>⚠️ À revoir — {len(review)}</summary><div class=wrap><table>"
                 "<tr><th>Shop</th><th>Titre</th><th>Prix</th><th>Candidats</th></tr>"
                 + "".join(f"<tr><td>{shop}</td><td>{A(url, title[:60])}</td><td>${price:.2f}</td>"
                           f"<td class=small>{cands}</td></tr>"
                           for shop, title, price, av, cands, sc, url in review)
                 + "</table></div></details>")
    frag = ROOT / "discovered" / "candidates.html"
    if frag.exists():
        h.append("<details><summary>🔎 Shops découverts</summary>"
                 + re.sub(r"<h2>.*?</h2>", "", frag.read_text(encoding="utf-8"), count=1, flags=re.S) + "</details>")

    # ---------------- M : rapport complet / audit
    h.append("<h2 id=complet>🗃 Rapport complet / audit</h2>")
    h.append("<p class=small>Vue exhaustive, pour l’audit et le contrôle du matching. "
             "Ce n’est plus la surface de décision.</p>")
    h.append("<details><summary>Tous les SKU, toutes les offres</summary>")
    for b in blocks:
        s = b[3]
        h.append(f"<div class=row><b>{b[2]} {b[1]} · {sku_label(s)}</b>"
                 + detail_block(s, by_sid.get(s["id"], []), cat, nb) + "</div>")
    h.append("</details>")
    (OUT/"index.html").write_text("\n".join(h), encoding="utf-8")


def detail_block(s, obs, cat, nb):
    """L : la richesse n'est pas supprimée, elle passe derrière la décision."""
    if not obs: return "<details><summary>détails</summary><p class=small>Aucune offre observée.</p></details>"
    r = ["<details><summary>détails</summary><div class=wrap><table>",
         "<tr><th>Shop</th><th>Produit</th><th>Prix</th><th>Qté</th><th>Unitaire</th><th>Stock</th><th>Landed €</th></tr>"]
    for e in obs[:20]:
        o = e["o"]; q = (o[11] if len(o) > 11 and o[11] else 1)
        cls = "" if o[4] else " class=oos"
        r.append(f"<tr{cls}><td>{o[1]}</td><td>{A(o[5], (o[2] or '')[:52])}</td>"
                 f"<td>{money_or(o[3])}</td><td>{q}</td><td>{money_or(o[3] / q if q else o[3])}</td>"
                 f"<td>{'IN STOCK' if o[4] else 'sold out'}</td>"
                 f"<td>{landed_phrase(o[3], q, cat)}</td></tr>")
    r.append("</table></div>")
    he = next((e for e in obs if e.get("hist")), None)
    meta = [f"exact_comp : <code>{obs[0].get('key','')}</code>",
            f"ask {money_or(s.get('market_ask_us'))}", f"sold {money_or(s.get('market_sold_us'))}",
            f"confiance {sold_confidence(s) or '—'}",
            f"buy ≤ {money_or(s.get('buy_below_usd'))}", f"watch ≤ {money_or(s.get('watch_below_usd'))}",
            f"landed estimé par boîte dans un panier de {nb}"]
    if he: meta.append(f"historical low {money_or(he['hist']['low'])} le {he['hist']['at'][:10]} "
                       f"({he['hist']['n_shops']} shop(s)) — cible de surveillance, pas une valeur de marché")
    if s.get("note"): meta.append(s["note"])
    r.append("<p class=small>" + " · ".join(meta) + "</p></details>")
    return "".join(r)


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
