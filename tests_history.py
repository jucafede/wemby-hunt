"""M — l'historique est un fait, jamais une valeur de marché. Cloisonné par exact_comp_key."""
import sys, tempfile, pathlib
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<62} got={got!r}")

hunt.DB = pathlib.Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
c = hunt.db()
def obs(key, price, sealed=1, shop="sh", sa="2026-01-01T00:00:00", qty=1):
    c.execute("INSERT INTO observations (sku_id,shop,title,variant_title,price,available,url,"
              "match_score,seen_at,exact_comp_key,sealed,quantity,unit_price) "
              "VALUES ('SKU',?,'t','',?,0,?,1.0,?,?,?,?,?)",
              (shop, price, f"u{price}{shop}{sa}", sa, key, sealed, qty, price / qty))

K1 = "SKU|std|x1"; K6 = "SKU|std|x6"; KS = "SKU|sapphire|x1"
obs(K1, 40.0); obs(K1, 30.0, shop="b"); obs(K6, 300.0, qty=6); obs(KS, 900.0)
obs(K1, 5.0, sealed=0, shop="single")      # un single au même comp key
c.commit()

h1 = hunt.historical_low(c, K1)
check("historical low ignore le single à 5 $", h1["low"], 30.0)
check("historical low : date conservée", h1["at"][:10], "2026-01-01")
check("historical low : nombre de shops", h1["n_shops"], 2)

h6 = hunt.historical_low(c, K6)
check("un lot x6 ne contamine pas x1 (unitaire 50 vs 30)", h6["low"], 50.0)
check("x1 et x6 sont deux historiques distincts", h1["low"] != h6["low"])
hs = hunt.historical_low(c, KS)
check("Sapphire a son propre historique", hs["low"], 900.0)
check("cloison inconnue -> pas d'historique", hunt.historical_low(c, "SKU|std|x99"), None)

# un ancien prix OOS ne peut pas produire GO : la décision n'utilise que sold + comp
check("ancien OOS ne fabrique aucun GO (pas de sold)",
      hunt.decide(True, -60, None, "EXACT", 50, 30.0), "PRICE ANOMALY — NO SOLD DATA")
check("historique ne devient jamais une référence marché",
      hunt.market_ref({"market_ask_us": None, "market_sold_us": None}), (None, None))

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
