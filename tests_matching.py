import sys, copy, yaml
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

cat = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
skus = copy.deepcopy(cat["skus"])
have = {s["id"] for s in skus}

def add(sid, st, fmt, cfg=None):
    i = "PANINI_2023-24_" + sid
    if i in have: return
    d = {"id": i, "season": "2023-24", "manufacturer": "Panini", "set": st, "format": fmt,
         "configuration": cfg, "tier": "retail", "buy_below_usd": 1, "watch_below_usd": 1}
    if st == "Donruss Optic": d["aliases"] = ["Optic"]
    skus.append(d); have.add(i)

for sid, st, fmt in [
    ("PRIZM_MEGA","Prizm","Mega"),("PRIZM_FAST_BREAK","Prizm","Fast Break"),("PRIZM_CHOICE","Prizm","Choice"),
    ("PRIZM_INTERNATIONAL","Prizm","International"),("PRIZM_RETAIL_BOX","Prizm","Retail Box"),
    ("OPTIC_HOBBY_BLASTER","Donruss Optic","Hobby Blaster"),("OPTIC_HOBBY_MEGA","Donruss Optic","Hobby Mega"),
    ("OPTIC_FAST_BREAK","Donruss Optic","Fast Break"),("OPTIC_CHOICE","Donruss Optic","Choice"),
    ("OPTIC_HANGER","Donruss Optic","Hanger"),("OPTIC_FOTL","Donruss Optic","FOTL"),
    ("SELECT_H2","Select","H2"),("SELECT_HANGER","Select","Hanger"),
    ("SELECT_INTERNATIONAL","Select","International"),("SELECT_HOBBY_MEGA","Select","Hobby Mega"),
    ("MOSAIC_HOBBY","Mosaic","Hobby"),("MOSAIC_FAST_BREAK","Mosaic","Fast Break"),
    ("MOSAIC_CHOICE","Mosaic","Choice"),("MOSAIC_INTERNATIONAL","Mosaic","International"),
    ("MOSAIC_FOTL","Mosaic","FOTL"),
    ("PHOENIX_MEGA","Phoenix","Mega"),("PHOENIX_INTERNATIONAL","Phoenix","International"),
    ("PHOENIX_FOTL","Phoenix","FOTL"),
    ("PREMIUM_STOCK_HOBBY","Premium Stock","Hobby"),("CONTENDERS_BLASTER","Contenders","Blaster"),
    ("REVOLUTION_CNY","Revolution","Chinese New Year"),
    ("COURT_KINGS_INTERNATIONAL","Court Kings","International"),
    ("HOOPS_BLASTER","Hoops","Blaster"),("HOOPS_MEGA","Hoops","Mega"),
]:
    add(sid, st, fmt)
add("MOSAIC_MEGA_TARGET", "Mosaic", "Mega", "Target Reactive Yellow/Green")

P = "PANINI_2023-24_"
POS = [
 ("2023/24 Panini Prizm Basketball Mega Box (Pink Ice Prizms!)","PRIZM_MEGA"),
 ("2023-24 Panini Prizm Basketball Fast Break Box","PRIZM_FAST_BREAK"),
 ("2023-24 Panini Prizm Basketball Choice Hobby Box","PRIZM_CHOICE"),
 ("2023-24 Panini Prizm Basketball International Hobby Box","PRIZM_INTERNATIONAL"),
 ("2023/24 Panini Prizm Basketball 24-Pack Retail Box","PRIZM_RETAIL_BOX"),
 ("2023/24 Panini Donruss Optic Basketball 6-Pack Hobby Blaster Box","OPTIC_HOBBY_BLASTER"),
 ("2023-24 Panini Donruss Optic Basketball Mega Hobby Box (Hyper Green Prizms)","OPTIC_HOBBY_MEGA"),
 ("2023-24 Panini Donruss Optic Basketball Fast Break Box","OPTIC_FAST_BREAK"),
 ("2023-24 Panini Donruss Optic Basketball Choice Box","OPTIC_CHOICE"),
 ("2023-24 Panini Donruss Optic Basketball Hanger Box (Velocity Parallels)","OPTIC_HANGER"),
 ("2023-24 Panini Select Basketball H2 Hobby Hybrid Box","SELECT_H2"),
 ("2023-24 Panini Select Basketball, Hanger Box","SELECT_HANGER"),
 ("2023-24 Panini Select Basketball International Hobby Box","SELECT_INTERNATIONAL"),
 ("2023-24 Panini Select Basketball Hobby Mega Box","SELECT_HOBBY_MEGA"),
 ("2023-24 Panini Mosaic Basketball Hobby Box","MOSAIC_HOBBY"),
 ("2023-24 Panini Mosaic Fast Break Basketball Hobby Box","MOSAIC_FAST_BREAK"),
 ("2023-24 Panini Mosaic Basketball Choice Box","MOSAIC_CHOICE"),
 ("2023-24 Panini Mosaic Basketball International Hobby Box","MOSAIC_INTERNATIONAL"),
 ("2023-24 Panini Phoenix Mega Box","PHOENIX_MEGA"),
 ("2023/24 Panini Phoenix Basketball International Hobby Box","PHOENIX_INTERNATIONAL"),
 ("2023/24 Panini Premium Stock Basketball Hobby Box","PREMIUM_STOCK_HOBBY"),
 ("2023-24 Panini Contenders Basketball Blaster Box","CONTENDERS_BLASTER"),
 ("2023/24 Panini Phoenix Basketball 6-pack Blaster Box","PHOENIX_BLASTER"),
 # les 4 nouveaux exigés
 ("2023-24 Panini Mosaic Basketball Target Mega Box (Reactive Yellow/Green)","MOSAIC_MEGA_TARGET"),
 ("2023-24 Panini Mosaic Basketball Mega Box (Reactive Blue Pink)","MOSAIC_MEGA"),
 ("2023-24 Panini Donruss Optic Basketball 1st Off The Line FOTL Hobby Box","OPTIC_FOTL"),
 ("2023-24 Panini Donruss Optic Basketball 1st Off the Line Hobby Box","OPTIC_FOTL"),
 ("2023/24 Panini Mosaic Basketball First Off The Line Hobby Box","MOSAIC_FOTL"),
 # non-régression sur les SKU existants
 ("2023-24 Panini Prizm Basketball Hanger Box (Orange Ice Prizm)","PRIZM_HANGER"),
 ("2023-24 Panini Contenders Basketball Hobby Box","CONTENDERS_HOBBY"),
 ("2023-24 Panini NBA Hoops Basketball 6-Pack Blaster Box","HOOPS_BLASTER"),
 # G — EuroLeague : identité produit distincte, pas un Prizm NBA moins cher
 ("2023-24 Panini Prizm Turkish Airlines EuroLeague Basketball Blaster Box","PRIZM_EUROLEAGUE_BLASTER"),
 ("2023-24 Panini Prizm Turkish Airlines EuroLeague Basketball Hobby Box","PRIZM_EUROLEAGUE_HOBBY"),
 ("2023-24 Panini Prizm Turkish Airlines Euroleague Basketball Blaster Box","PRIZM_EUROLEAGUE_BLASTER"),
]
P2 = [
 # F — Topps 2023-24, licensed nbpa
 ("2023-24 Topps Chrome Basketball Value Blaster Box","TOPPS_2023-24_CHROME_VALUE_BLASTER"),
 ("2023-24 Topps Chrome Basketball Hobby Box","TOPPS_2023-24_CHROME_HOBBY"),
 ("2023-24 Topps Chrome Basketball Sapphire Edition Hobby Box","TOPPS_2023-24_CHROME_SAPPHIRE"),
 ("2023-24 Topps Cosmic Chrome Basketball Hobby Box","TOPPS_2023-24_COSMIC_CHROME_HOBBY"),
 # Bowman 2025-26 : famille propre, jamais du Topps Chrome
 ("2025-26 Bowman Basketball Hobby Jumbo Box","TOPPS_2025-26_BOWMAN_HOBBY_JUMBO"),
 ("2025-26 Bowman Basketball Value Blaster Box","TOPPS_2025-26_BOWMAN_VALUE_BLASTER"),
 ("2025/26 Bowman Basketball Hobby Box","TOPPS_2025-26_BOWMAN_HOBBY"),
 ("2025/26 Bowman Basketball Breaker Delight Box","TOPPS_2025-26_BOWMAN_BREAKERS_DELIGHT"),
 ("2025/26 Bowman Basketball 6-pack Mega Box","TOPPS_2025-26_BOWMAN_MEGA"),
 ("2023-24 Panini Select Basketball Mega 20-Box Case (Green Shock Prizm)","SELECT_MEGA_CASE"),
 ("2023-24 Panini Mosaic Fast Break Basketball Hobby 20-Box Case","MOSAIC_FAST_BREAK_CASE"),
 ("2023-24 Panini Mosaic Basketball Fast Brk Box","MOSAIC_FAST_BREAK"),
 ("2023-24 Panini Select BasketballMega Box (Red/ Purple Cracked Ice)","SELECT_MEGA"),
]
NEG = [
 ("2023-24 Topps Chrome NBL Australia Basketball Hobby Box","Topps Chrome NBL exclu"),
 ("2023-24 Overtime Elite Topps Chrome Basketball Hobby Box","OTE exclu"),
 ("2023-24 Bowman University Basketball Hobby Box","Bowman University exclu"),
 ("2025-26 Bowman University Chrome Basketball Mega Box","Bowman U Chrome exclu"),
 ("2025 Bowman Baseball Mega Box","Bowman Baseball : mauvais sport"),
 ("2025-26 Bowman U NOW Basketball March Madness Hobby Box","Bowman U exclu"),
 ("2025-26 Bowman University Best Basketball Hobby Box","Bowman Best exclu"),
 ("2025-26 Bowman Chrome Basketball 1st Edition Hobby Box","Bowman Chrome 1st Edition exclu"),
 ("2023-24 Topps Chrome G-League Basketball Hobby Box","G-League exclu"),
 ("2023-24 Panini Prizm EuroLeague Soccer Blaster Box","EuroLeague mais pas basket -> aucun SKU"),
 ("2023/24 Panini Contenders Optic Basketball Hobby, Box","Contenders Optic ≠ Optic ni Contenders"),
 ("2023/24 Panini Prizm Deca Basketball Hobby Box","Deca ≠ Prizm"),
 ("2023-24 Panini Prizm Monopoly 6-Pack Basketball Blaster Box","Monopoly ≠ Prizm"),
 ("2023-24 Panini Contenders Basketball Hobby, Pack","Pack ≠ Box (le 4e nouveau)"),
 ("2023-24 Panini Prizm Basketball 4-Card Pack","Pack ≠ Box"),
 ("2023-24 Panini Contenders Basketball Value Pack","Value Pack ≠ Box"),
 ("2023-24 Panini Mosaic Basketball 20-Box Case","Case générique : ni Mega ni Fast Break → REVIEW"),
 ("2026 Panini Contenders Professional Fighters League PFL Hobby Box","PFL ≠ basket (doit être REJECT, plus REVIEW)"),
 ("2026 Panini Contenders PFL Hobby Box","PFL seul ≠ basket"),
 ("Karl-Anthony Towns 2023-24 Panini Court Kings Art Nouveau Swatch #AN-KAT","single ≠ sealed"),
 ("2023 Panini Phoenix Football Blaster Box","football ≠ basket"),
 ("2024-25 Panini Phoenix Basketball Blaster Box","mauvaise saison"),
 ("2019 Donruss Optic Blaster Box","mauvaise saison"),
 ("2023-24 Panini Select Basketball Tin","Tin ≠ Blaster/Mega"),
 ("2023-24 Panini Mosaic Basketball Fat Pack","Fat Pack ≠ Box"),
 ("2023-24 Panini Prizm Basketball Cello Multi-Pack","Cello ≠ Box"),
 ("2023 Panini Donruss FootBall Blaster Box","FootBall CamelCase ≠ basket"),
]
fails = []
print("--- POSITIFS ---")
for t, exp in POS + [(a, b) for a, b in P2]:
    m = hunt.match_title(t, skus)
    good = m.sku_id == (exp if exp.startswith("TOPPS") else P + exp)
    if not good: fails.append(("POS", t, exp, m.sku_id))
    print(f"{'PASS' if good else 'FAIL'} {m.score:4.2f} {str(m.sku_id).replace(P,''):<30} attendu={exp:<30} fmt={m.fmt}")
print("\n--- NEGATIFS (aucun ne doit produire un MATCH) ---")
for t, why in NEG:
    m = hunt.match_title(t, skus)
    good = m.sku_id is None
    if not good: fails.append(("NEG", t, "aucun match", m.sku_id))
    v = "REJECT" if m.score == 0 else ("REVIEW %.2f" % m.score if m.sku_id is None else "MATCH:" + str(m.sku_id).replace(P,""))
    print(f"{'PASS' if good else 'FAIL'} {v:<26} {why}")
print(f"\nTOTAL : {len(POS)+len(P2)+len(NEG)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
