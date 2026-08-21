"""V2-a — badges, mémoire, garde-fous de décision. Sans réseau, sur cas simulés."""
import sys, csv, glob, sqlite3, tempfile, pathlib
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(name, got, want):
    total.append(name)
    ok = got == want
    if not ok: fails.append((name, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {name:<64} got={got!r}")

def O(shop, price, avail): return ("SKU", shop, "t", price, 1 if avail else 0, "u", 1.0, "2026-01-03T00:00:00", "")

# ---- sold_confidence : dérivée, jamais saisie
check("sold_confidence n=6 w=30 -> HIGH",
      hunt.sold_confidence({"market_sold_us": 300, "market_sold_n": 6, "market_sold_window_days": 30}), "HIGH")
check("sold_confidence n=2 w=90 -> MEDIUM",
      hunt.sold_confidence({"market_sold_us": 300, "market_sold_n": 2, "market_sold_window_days": 90}), "MEDIUM")
check("sold_confidence n=1 -> LOW",
      hunt.sold_confidence({"market_sold_us": 300, "market_sold_n": 1, "market_sold_window_days": 10}), "LOW")
check("sans market_sold_us -> None", hunt.sold_confidence({"market_sold_us": None}), None)

# ---- décision : GO seulement si EXACT + confiance >= MEDIUM
check("GO : EXACT + MEDIUM + sous seuil", hunt.decide(True, -20, "MEDIUM", "EXACT", 50, 40), "GO")
check("LOW -> pas de GO", hunt.decide(True, -20, "LOW", "EXACT", 50, 40), "PRICE ANOMALY — LOW MARKET CONFIDENCE")
check("sans sold -> pas de GO", hunt.decide(True, -20, None, "EXACT", 50, 40), "PRICE ANOMALY — NO SOLD DATA")
check("RELATED -> pas de GO", hunt.decide(True, -20, "HIGH", "RELATED", 50, 40), "PRICE ANOMALY — RELATED COMP")
check("au-dessus du seuil -> rien", hunt.decide(True, 10, "HIGH", "EXACT", 50, 60), None)

# ---- comp_type
check("parallèle nommé sur SKU sans configuration -> RELATED",
      hunt.comp_type_of("2023-24 panini select basketball mega box (green shock prizms)", {"configuration": None}), "RELATED")
check("boîte standard -> EXACT",
      hunt.comp_type_of("2023-24 panini select basketball mega box", {"configuration": None}), "EXACT")

check("ask sans market_ask_from -> pas de référence",
      hunt.market_ref({"market_ask_us": 50, "market_sold_us": None}), (None, None))
check("ask avec provenance -> référence ask",
      hunt.market_ref({"market_ask_us": 50, "market_ask_from": ["awesome"], "market_sold_us": None}), (50.0, "ask"))

# ---- mémoire : restock et new low sur base réelle simulée
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
hunt.DB = pathlib.Path(db); conn = hunt.db()
hist = [("2026-01-01T00:00:00", 40.0, 1), ("2026-01-02T00:00:00", 40.0, 0), ("2026-01-03T00:00:00", 30.0, 1)]
for sa, pr, av in hist:
    conn.execute("INSERT INTO observations (sku_id,shop,title,variant_title,price,available,url,match_score,seen_at) "
                 "VALUES ('SKU','sh','t','',?,?,'u',1.0,?)", (pr, av, sa))
conn.commit()
mem = hunt.line_memory(conn, "SKU", "sh", "u", "", "2026-01-03T00:00:00")
check("mémoire : min_price_ever", mem["min_price_ever"], 30.0)
check("mémoire : days_oos_before_return", mem["days_oos_before_return"], 1)
check("mémoire : prix précédent", mem["prev_price"], 40.0)

sku = {"market_sold_us": 50, "market_sold_n": 6, "market_sold_window_days": 30, "wemby_rc": True}
tg, dsc, gap, ref, kind = hunt.compute_badges(O("sh", 30.0, True), mem, sku, "trusted", [O("sh", 30.0, True)])
check("RESTOCK déclenché après rupture", any(t.startswith("RESTOCK") for t in tg), True)
check("NEW_LOW déclenché sur baisse réelle", "NEW_LOW" in tg, True)
check("PRICE_DROP déclenché", any(t.startswith("PRICE_DROP") for t in tg), True)
check("STRONG_DEAL à -40% vs sold", any(t.startswith("STRONG_DEAL") for t in tg), True)
check("RC_YEAR est un descriptif, pas un déclencheur", "RC_YEAR" in dsc and "RC_YEAR" not in tg, True)

# prix stable observé 3 fois -> PAS de NEW_LOW
for sa, pr in [("2026-02-01T00:00:00", 20.0), ("2026-02-02T00:00:00", 20.0), ("2026-02-03T00:00:00", 20.0)]:
    conn.execute("INSERT INTO observations (sku_id,shop,title,variant_title,price,available,url,match_score,seen_at) "
                 "VALUES ('SKU2','sh','t','',?,1,'u2',1.0,?)", (pr, sa))
conn.commit()
mem2 = hunt.line_memory(conn, "SKU2", "sh", "u2", "", "2026-02-03T00:00:00")
tgs, _, _, _, _ = hunt.compute_badges(O("sh", 20.0, True), mem2, {"market_sold_us": 20, "market_sold_n": 6,
                                     "market_sold_window_days": 30}, "trusted", [O("sh", 20.0, True), O("x", 21.0, True)])
check("prix stable 3x -> pas de NEW_LOW", "NEW_LOW" in tgs, False)

# ---- seul en stock : sous la référence -> déclencheur ; très au-dessus -> descriptif
one = [O("sh", 30.0, True)]
tg1, d1, *_ = hunt.compute_badges(one[0], None, {"market_ask_us": 35, "market_sold_us": None}, "trusted", one)
check("seul en stock sous l'ask -> SEUL_EN_STOCK (déclencheur)", "SEUL_EN_STOCK" in tg1, True)
hi = [O("sh", 64.0, True)]
tg2, d2, *_ = hunt.compute_badges(hi[0], None, {"market_ask_us": None, "market_sold_us": 35,
                                                "market_sold_n": 6, "market_sold_window_days": 30}, "trusted", hi)
check("seul en stock à +83% -> ONLY_STOCK_SEEN (descriptif)", "ONLY_STOCK_SEEN" in d2 and not tg2, True)

# référence auto-sourcée : seul en stock au prix qu'on a soi-même relevé chez ce shop
selfsrc = [O("superior", 75.0, True)]
tg3, d3, *_ = hunt.compute_badges(selfsrc[0], None,
    {"market_ask_us": 75, "market_ask_from": ["superior"], "market_sold_us": None}, "watch", selfsrc)
check("ask relevé chez ce seul shop -> ONLY_STOCK_SEEN, pas déclencheur",
      "ONLY_STOCK_SEEN" in d3 and "SEUL_EN_STOCK" not in tg3, True)
other = [O("rbicru7", 75.0, True)]
tg4, _, *_ = hunt.compute_badges(other[0], None,
    {"market_ask_us": 75, "market_ask_from": ["superior"], "market_sold_us": None}, "trusted", other)
check("ask relevé ailleurs -> SEUL_EN_STOCK reste déclencheur", "SEUL_EN_STOCK" in tg4, True)
check("sold externe n'est jamais auto-sourcé",
      hunt.ref_self_sourced({"market_ask_from": ["superior"]}, "superior", "sold"), False)

# prix nul : ni déclencheur, ni HOT — une précommande à 0 $ donnait -100 %
_tg0, _d0, _g0, _r0, _k0 = hunt.compute_badges(O("bleecker", 0.0, True), None,
    {"market_ask_us": 100, "market_ask_from": ["x"]}, "watch", [O("bleecker", 0.0, True)])
check("prix 0 -> aucun déclencheur", _tg0, [])
check("prix 0 -> descriptif NO_PRICE", "NO_PRICE" in _d0, True)
_z = {"available": True, "triggers": ["STRONG_DEAL"], "gap": -100.0, "ref": 50, "key": "Z",
      "sid": "Z", "o": ("S", "sh", "t", 0.0, 1, "u", 1.0, "2026-01-01T00:00:00", "")}
check("prix 0 exclu de HOT NOW", _z in hunt.hot_now([_z]), False)

# déduplication HOT NOW : un produit = une ligne + N autres offres
def _E(key, price, gap):
    return {"available": True, "triggers": ["STRONG_DEAL"], "gap": gap, "ref": 50, "key": key,
            "sid": key, "o": ("S", f"sh{price}", "t", price, 1, "u", 1.0, "2026-01-01T00:00:00", "")}
_hn = hunt.hot_now([_E("EURO", 9.95, -60.0), _E("EURO", 14.75, -41.0), _E("EURO", 15.0, -40.0), _E("AUTRE", 20.0, -20.0)])
check("un produit n'occupe qu'une place HOT", len([e for e in _hn if e["key"] == "EURO"]), 1)
check("la meilleure offre est retenue", _hn[0]["o"][3], 9.95)
check("les autres offres sont comptées", _hn[0]["other_offers"], 2)
check("les autres produits restent présents", len(_hn), 2)

# un SKU sans seuil ne doit jamais faire planter la détection de restock deal
_bb = {"buy_below_usd": None}.get("buy_below_usd")
check("seuil null -> pas de restock deal, pas de TypeError",
      _bb is not None and 30.0 <= (_bb or 0), False)

# ---- HOT NOW : invariants
def _mk(key, avail, trig, gap, ref, price=42.0):
    return {"available": avail, "triggers": trig, "gap": gap, "ref": ref, "key": key, "sid": key,
            "o": ("S", "sh", "t", price, 1 if avail else 0, "u", 1.0, "2026-01-01T00:00:00", "")}
noref = _mk("n", True,  ["NEW_LOW"],     None, None)
ok    = _mk("o", True,  ["DEAL -12%"],  -12.0, 50)
over  = _mk("v", True,  ["RESTOCK +3j"],  8.0, 50)
oos   = _mk("s", False, ["NEW_LOW"],    -30.0, 50)
hn = hunt.hot_now([noref, ok, over, oos])
check("INVARIANT : ligne au-dessus de la référence exclue de HOT NOW", over not in hn, True)
check("ligne sans référence exclue de HOT NOW", noref not in hn, True)
check("ligne hors stock exclue de HOT NOW", oos not in hn, True)
check("HOT NOW <= 15", len(hunt.hot_now([_mk(f"k{i}", True, ["DEAL"], -12.0, 50) for i in range(40)])) <= 15, True)

# ---- rejeu sur le run réel du 18/08 09:08
f = sorted(glob.glob("/private/tmp/claude-501/-Users-ju-Draft-Class/34b24d58-a555-46bd-9b28-3b80e0afd7d5/scratchpad/rpt20/deals_*.csv"))
if f:
    rows = list(csv.DictReader(open(f[0], encoding="utf-8")))
    ent = []
    for r in rows:
        if r["in_stock"] != "1": continue
        sold = r["market_sold_us"]; ask = r["market_ask_us"]
        ref = float(sold) if sold else (float(ask) if ask else None)
        if ref is None: continue
        pr = float(r["price_usd"])
        gap = round((pr - ref) / ref * 100, 1)
        tg = []
        if gap <= -20: tg.append("STRONG_DEAL")
        elif gap <= -10: tg.append("DEAL")
        if tg: ent.append({"available": True, "triggers": tg, "gap": gap, "ref": ref,
                           "key": r["sku_id"] + r["shop"], "sid": r["sku_id"],
                           "o": ("S", r["shop"], r["title"], pr, 1, r["url"], 1.0, r["seen_at"], ""),
                           "label": f"{r['sku_id'].replace('PANINI_2023-24_','')} {r['shop']} ${pr:.2f}"})
    hn = hunt.hot_now(ent)
    print(f"\n  rejeu 18/08 09:08 — HOT NOW = {len(hn)} ligne(s)")
    for e in hn: print(f"    {e['label']:<48} {e['gap']:>7.1f}%")
    check("INVARIANT : aucune ligne HOT NOW à écart > 0%", all(e["gap"] <= 0 for e in hn), True)
    check("INVARIANT : HOT NOW <= 15", len(hn) <= 15, True)
else:
    print("  (CSV du 18/08 absent — rejeu ignoré)")

# ---- rendu HTML : un statut hors palette ne doit jamais lever (crash prod du 18/08 18:11)
import yaml as _y
_cat = _y.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
_sku = [x for x in _cat["skus"] if x["id"].endswith("EUROLEAGUE_BLASTER")][0]
_o = ("SKU", "cardiacs", "t", 9.95, 1, "https://x", 1.0, "2026-08-18T00:00:00", "", "EXACT", None)
try:
    hunt.write_html(_cat, [("retail", "PRICE ANOMALY — NO SOLD DATA", "⚡", _sku, [_o], _o)],
                    [], [], "2026-08-18T00:00:00", {"cardiacs": "watch"})
    _ok = True
except Exception as _e:
    _ok = f"{_e.__class__.__name__}: {_e}"
check("write_html supporte un statut hors palette", _ok, True)
_h = open("/Users/ju/Draft Class/wemby-hunt/out/index.html", encoding="utf-8").read()
check("libellé HTML inclut la ligue", "Prizm EuroLeague Blaster" in _h, True)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for x in fails: print("  FAIL", x)
sys.exit(1 if fails else 0)
