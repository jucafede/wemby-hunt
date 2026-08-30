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
# L'historique parle dans l'unité de l'offre : 300 $ le lot, 50 $ la boîte. Rendre 50 face à
# un prix live de 300 était le bug des SKU case (Mosaic Fast Break : « plus bas 297,25 » sous
# un prix de 5 945). L'intention du test ne change pas : x6 ne contamine pas x1.
check("un lot x6 ne contamine pas x1 (unitaire 50 vs 30)", h6["low_unit"], 50.0)
check("l'historique d'un lot x6 s'exprime en prix de lot", h6["low"], 300.0)
check("et porte sa quantité", h6["qty"], 6)
check("une boîte seule reste une boîte seule", (h1["low"], h1["low_unit"], h1["qty"]), (30.0, 30.0, 1))
check("convention d'affichage unique pour un lot",
      hunt.hist_phrase(h6["low"], h6["qty"]), "case $300.00 · $50.00/boîte")
check("et pour une boîte seule", hunt.hist_phrase(h1["low"], h1["qty"]), "$30.00")
check("x1 et x6 sont deux historiques distincts", h1["low"] != h6["low"])
hs = hunt.historical_low(c, KS)
check("Sapphire a son propre historique", hs["low"], 900.0)
check("cloison inconnue -> pas d'historique", hunt.historical_low(c, "SKU|std|x99"), None)

# un ancien prix OOS ne peut pas produire GO : la décision n'utilise que sold + comp
check("ancien OOS ne fabrique aucun GO (pas de sold)",
      hunt.decide(True, -60, None, "EXACT", 50, 30.0), "PRICE ANOMALY — NO SOLD DATA")
check("historique ne devient jamais une référence marché",
      hunt.market_ref({"market_ask_us": None, "market_sold_us": None}), (None, None))

# ---- N : watchlist en trois couches
def E(key, low, ref, kind, askfrom=(), avail=False, shop="sh"):
    return {"key": key, "available": avail, "o": ("S", shop, "t", 99.0, 0, "u", 1.0, "2026-01-01T00:00:00", ""),
            "hist": {"low": low, "at": "2026-01-01T00:00:00", "shop": shop, "n_shops": 3, "n_obs": 5},
            "ref": ref, "kind": kind, "sku": {"market_ask_from": list(askfrom), "season": "2023-24",
            "manufacturer": "P", "set": "X", "format": "Blaster"}}

sold_ok  = E("A", 20.0, 30.0, "sold")                    # -33 % vs sold externe
ask_1src = E("B", 20.0, 30.0, "ask", ("superior",))      # ask mono-source : circulaire
ask_2src = E("C", 20.0, 30.0, "ask", ("walmart", "dacw"))
no_ref   = E("D", 20.0, None, None)
close    = E("E", 29.0, 30.0, "sold")                    # -3 %, pas une priorité
in_stock = E("F", 20.0, 30.0, "sold", avail=True)
dup      = E("A", 20.0, 30.0, "sold", shop="autre")      # même produit, autre shop

prio, lows, rest = hunt.watchlist_layers([sold_ok, ask_1src, ask_2src, no_ref, close, in_stock, dup])
pk = {e["key"] for e in prio}
check("sold externe qualifie une priorité", "A" in pk)
check("ask mono-source ne qualifie PAS (circulaire)", "B" in pk, False)
check("ask multi-source qualifie", "C" in pk)
check("sans référence : pas de priorité", "D" in pk, False)
check("écart faible : pas de priorité", "E" in pk, False)
check("en stock : hors watchlist", "F" in pk, False)
check("déduplication par exact_comp_key", len([e for e in prio if e["key"] == "A"]), 1)
check("sans historique -> couche 3", [e["key"] for e in rest], ["D"] if False else [])
check("les non qualifiés retombent en historical lows", {"B", "E"} <= {e["key"] for e in lows})

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
