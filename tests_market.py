"""Current Market — la valeur d'aujourd'hui, distincte du plus-bas historique."""
import sys, tempfile, pathlib, yaml
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<60} got={got!r}")

NOW = "2026-08-23T00:00:00"
hunt.DB = pathlib.Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
c = hunt.db()
def obs(key, price, days, shop="sh", region="US", sealed=1, avail=1):
    from datetime import datetime, timedelta
    sa = (datetime.fromisoformat(NOW) - timedelta(days=days)).isoformat()
    c.execute("INSERT INTO observations (sku_id,shop,title,variant_title,price,available,url,"
              "match_score,seen_at,exact_comp_key,sealed,quantity,unit_price,market_region) "
              "VALUES ('S',?,'t','',?,?,?,1.0,?,?,?,1,?,?)",
              (shop, price, avail, f"u{price}{shop}{days}", sa, key, sealed, price, region))

# TEST A — marché montant : le vieux plus-bas ne pilote plus
K = "A|std|x1"
obs(K, 25.0, 500, "vieux")
for i, p in enumerate([99, 101, 103, 105, 108]): obs(K, p, 5 + i, f"s{i}")
c.commit()
cm = hunt.current_market(c, {}, K, NOW)
check("A · le marché actuel se cale sur le cluster récent, pas sur le 25 $",
      95 <= (cm["value"] or 0) <= 110)
check("A · le 25 $ vieux de 500 j est hors fenêtre", 25.0 not in [cm["value"]])
hl = hunt.historical_low(c, K)
check("A · le plus-bas historique est CONSERVÉ", hl["low"], 25.0)
check("A · et il est marqué STALE", hunt.freshness(500), "STALE")
check("A · une offre à 75 $ est sous le marché actuel", 75.0 < cm["value"])

# TEST F — outlier dans la fenêtre récente
K2 = "F|std|x1"
for i, p in enumerate([25, 99, 101, 103, 105]): obs(K2, p, 3 + i, f"f{i}")
c.commit()
cm2 = hunt.current_market(c, {}, K2, NOW)
check("F · l'aberration à 25 $ est écartée", 25.0 in cm2["outliers"])
check("F · la cote reste sur le cluster", 95 <= cm2["value"] <= 110)

# une observation du JOUR MÊME doit compter (age 0 est falsy en Python)
K0 = "TODAY|std|x1"; obs(K0, 75.0, 0, "hiddengems"); c.commit()
cm0 = hunt.current_market(c, {}, K0, NOW)
check("une observation du jour même n'est pas traitée comme vieille", cm0["value"], 75.0)
check("son âge est bien 0", cm0["age_days"], 0)

# TEST E — échantillon faible
K3 = "E|std|x1"; obs(K3, 100.0, 2, "solo"); c.commit()
check("E · une seule boutique -> confiance faible", hunt.current_market(c, {}, K3, NOW)["confidence"], "LOW")

# TEST J — aucune donnée exploitable
check("J · rien d'exploitable -> valeur UNKNOWN", hunt.current_market(c, {}, "VIDE|std|x1", NOW)["value"], None)

# TEST H/I — fraîcheur
K4 = "H|std|x1"; obs(K4, 100.0, 400, "vieux"); c.commit()
check("H · une donnée trop vieille ne fait pas un marché", hunt.current_market(c, {}, K4, NOW)["value"], None)
check("I · une donnée récente est FRESH", hunt.freshness(5), "FRESH")
check("fraîcheur intermédiaire", hunt.freshness(60), "AGING")

# TEST K — cloisonnement régional
K5 = "K|std|x1"
for i, p in enumerate([100, 102, 104]): obs(K5, p, 2 + i, f"us{i}", region="US")
for i, p in enumerate([40, 41, 42]): obs(K5, p, 2 + i, f"fr{i}", region="FR")
c.commit()
us = hunt.current_market(c, {}, K5, NOW, region="US")
check("K · une observation FR ne modifie pas le marché US", 99 <= us["value"] <= 105)
check("K · le marché FR se calcule séparément",
      39 <= hunt.current_market(c, {}, K5, NOW, region="FR")["value"] <= 43)

# TEST G — quantité : la cloison sépare déjà x1 et xN
K6 = "G|std|x6"; obs(K6, 600.0, 2, "lot"); c.commit()
check("G · un lot x6 n'entre pas dans le marché x1",
      hunt.current_market(c, {}, "G|std|x1", NOW)["value"], None)

# sold exact prioritaire sur les asks
sold_sku = {"market_sold_us": 106.0, "market_sold_n": 8, "market_sold_window_days": 30,
            "market_sold_checked_at": "2026-08-20"}
cmS = hunt.current_market(c, sold_sku, K, NOW)
check("SOLD > ASK : un sold fiable prime", cmS["basis"], "exact_sold")
check("SOLD : n=8 sur 30 j -> confiance HIGH", cmS["confidence"], "HIGH")
check("un sold LOW ne prime pas sur les asks",
      hunt.current_market(c, {"market_sold_us": 1.0, "market_sold_n": 1,
                              "market_sold_window_days": 400}, K, NOW)["basis"], "observed_ask")

# TEST M/N — la fiche réelle Hidden Gems
skus = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))["skus"]
m = hunt.match_title("2023-24 Topps Chrome NBA Basketball Value Box SEALED", skus)
check("M · la fiche Hidden Gems matche enfin la bonne SKU",
      m.sku_id, "TOPPS_2023-24_CHROME_VALUE_BLASTER")
check("M · SEALED est un état, pas une édition", hunt.sealed_product(
      hunt.norm("2023-24 Topps Chrome NBA Basketball Value Box SEALED")), True)
for t, why in [("2023-24 Topps Chrome Basketball Hobby Box", "Hobby"),
               ("2023-24 Topps Chrome Basketball BLASTER PACK", "pack"),
               ("2023-24 Topps Chrome Basketball Blaster 40-Box Case", "case"),
               ("2023-24 Topps Chrome UEFA Women's Champions League Value Box", "soccer")]:
    got = hunt.match_title(t, skus).sku_id
    check(f"N · Value Box ≠ {why}", got != "TOPPS_2023-24_CHROME_VALUE_BLASTER")

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
