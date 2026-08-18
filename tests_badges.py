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
check("NEW_LOW déclenché", "NEW_LOW" in tg, True)
check("PRICE_DROP déclenché", any(t.startswith("PRICE_DROP") for t in tg), True)
check("STRONG_DEAL à -40% vs sold", any(t.startswith("STRONG_DEAL") for t in tg), True)
check("RC_YEAR est un descriptif, pas un déclencheur", "RC_YEAR" in dsc and "RC_YEAR" not in tg, True)

# ---- seul en stock : sous la référence -> déclencheur ; très au-dessus -> descriptif
one = [O("sh", 30.0, True)]
tg1, d1, *_ = hunt.compute_badges(one[0], None, {"market_ask_us": 35, "market_sold_us": None}, "trusted", one)
check("seul en stock sous l'ask -> SEUL_EN_STOCK (déclencheur)", "SEUL_EN_STOCK" in tg1, True)
hi = [O("sh", 64.0, True)]
tg2, d2, *_ = hunt.compute_badges(hi[0], None, {"market_ask_us": None, "market_sold_us": 35,
                                                "market_sold_n": 6, "market_sold_window_days": 30}, "trusted", hi)
check("seul en stock à +83% -> ONLY_STOCK_SEEN (descriptif)", "ONLY_STOCK_SEEN" in d2 and not tg2, True)

# ---- HOT NOW : invariants
noref = {"available": True, "triggers": ["NEW_LOW"], "gap": None, "ref": None}
ok    = {"available": True, "triggers": ["DEAL -12%"], "gap": -12.0, "ref": 50}
over  = {"available": True, "triggers": ["RESTOCK +3j"], "gap": 8.0, "ref": 50}
oos   = {"available": False, "triggers": ["NEW_LOW"], "gap": -30.0, "ref": 50}
hn = hunt.hot_now([noref, ok, over, oos])
check("ligne sans référence exclue de HOT NOW", noref not in hn, True)
check("ligne hors stock exclue de HOT NOW", oos not in hn, True)
check("HOT NOW <= 15", len(hunt.hot_now([dict(ok) for _ in range(40)])) <= 15, True)

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
                           "label": f"{r['sku_id'].replace('PANINI_2023-24_','')} {r['shop']} ${pr:.2f}"})
    hn = hunt.hot_now(ent)
    print(f"\n  rejeu 18/08 09:08 — HOT NOW = {len(hn)} ligne(s)")
    for e in hn: print(f"    {e['label']:<48} {e['gap']:>7.1f}%")
    check("INVARIANT : aucune ligne HOT NOW à écart > 0%", all(e["gap"] <= 0 for e in hn), True)
    check("INVARIANT : HOT NOW <= 15", len(hn) <= 15, True)
else:
    print("  (CSV du 18/08 absent — rejeu ignoré)")

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for x in fails: print("  FAIL", x)
sys.exit(1 if fails else 0)
