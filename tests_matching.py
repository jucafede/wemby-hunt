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
 ("2023-24 Panini Phoenix Basketball Mega Box","PHOENIX_MEGA"),
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
 # Topps 2025-26 : Chrome, Chrome Update, Hoops, Signature Class
 ("2025-26 Topps Chrome Basketball Hobby Box","TOPPS_2025-26_CHROME_HOBBY"),
 ("2025-26 Topps Chrome Update Basketball Hobby Box","TOPPS_2025-26_CHROME_UPDATE_HOBBY"),
 ("2025-26 Topps Chrome Update Series Basketball Mega Box","TOPPS_2025-26_CHROME_UPDATE_MEGA"),
 ("2025-26 Topps Chrome Update Series Basketball Blaster Box","TOPPS_2025-26_CHROME_UPDATE_BLASTER"),
 ("2025/26 Topps Chrome Basketball - First Day Issue Hobby Box","TOPPS_2025-26_CHROME_FIRST_DAY_ISSUE"),
 ("2025-26 Topps Chrome Basketball Hobby Jumbo Box","TOPPS_2025-26_CHROME_HOBBY_JUMBO"),
 ("2025-26 Topps NBA Hoops Basketball Blaster Box","TOPPS_2025-26_HOOPS_BLASTER"),
 ("2025-26 Topps Signature Class Basketball Hobby Box","TOPPS_2025-26_SIGNATURE_CLASS_HOBBY"),
 # EuroLeague 2025-26 : identités propres, jamais confondues avec la NBA
 ("2025-26 Panini Contenders EuroLeague Basketball Mega Box","PANINI_2025-26_EUROLEAGUE_CONTENDERS_MEGA"),
 ("2025-26 Panini Select EuroLeague Basketball FOTL Hobby Box","PANINI_2025-26_EUROLEAGUE_SELECT_FOTL"),
 ("2025-26 Panini Origins EuroLeague Basketball H2 Box","PANINI_2025-26_EUROLEAGUE_ORIGINS_H2"),
 ("2025-26 Panini Select EuroLeague Basketball Mega Box","PANINI_2025-26_EUROLEAGUE_SELECT_MEGA"),
 # Cosmic Chrome et Cactus Jack : identités propres, la saison tranche
 ("2025-26 Topps Cosmic Chrome Basketball Hobby Box","TOPPS_2025-26_COSMIC_CHROME_HOBBY"),
 ("2023-24 Topps Cosmic Chrome Basketball Hobby Box","TOPPS_2023-24_COSMIC_CHROME_HOBBY"),
 ("2025/26 Topps Chrome Cactus Jack Basketball Hobby Box","TOPPS_2025-26_CHROME_CACTUS_JACK_HOBBY"),
 ("2023-24 Panini Select Basketball Mega 20-Box Case (Green Shock Prizm)","SELECT_MEGA_CASE"),
 ("2023-24 Panini Mosaic Fast Break Basketball Hobby 20-Box Case","MOSAIC_FAST_BREAK_CASE"),
 ("2023-24 Panini Mosaic Basketball Fast Brk Box","MOSAIC_FAST_BREAK"),
 ("2023-24 Panini Select BasketballMega Box (Red/ Purple Cracked Ice)","SELECT_MEGA"),
]
NEG = [
 # sport indéterminé : sans preuve de basket, jamais de rattachement décisionnel
 ("2025-26 Topps Chrome Bundesliga Value Blaster Box","Bundesliga = football, pas basket"),
 ("2023-24 Panini Select Fifa Blaster Box","FIFA = football, pas basket"),
 ("2025-26 Topps Chrome UEFA Champions League Blaster Box","UEFA = football"),
 ("2023-24 Phoenix Debut Edition International box","aucune preuve de basket -> REVIEW, pas un match"),
 ("2023-24 Panini Phoenix Mega Box","sans 'Basketball' : REVIEW, coût assumé du durcissement"),
 # H — configurations distinctes
 ("2023-24 Panini Prizm Basketball China Hobby Box","China Hobby n'est pas le Hobby standard"),
 ("2023-24 Panini Prizm Basketball Hanger Pack","Hanger Pack n'est pas Hanger Box"),
 # G — sealed gate (P0) : aucun single ne peut alimenter la couche décisionnelle
 ("2025-26 Cooper Flagg Bowman Hobby Stars Rookie RC HS-3","single Cooper Flagg : pas une Bowman Hobby Box"),
 ("Trayce Jackson-Davis 2023-24 Panini Mosaic #PM-TJD Pictographs Mosaic Choice","single : pas une Mosaic Choice Box"),
 ("CJ Stroud 2023 Panini Prizm Green Ice Prizm RC #339 PSA 10","single grade : jamais scelle"),
 ("2023-24 Topps Chrome NBL Australia Basketball Hobby Box","Topps Chrome NBL exclu"),
 ("2023-24 Overtime Elite Topps Chrome Basketball Hobby Box","OTE exclu"),
 ("2023-24 Bowman University Basketball Hobby Box","Bowman University exclu"),
 ("2025-26 Bowman University Chrome Basketball Mega Box","Bowman U Chrome exclu"),
 ("2025 Bowman Baseball Mega Box","Bowman Baseball : mauvais sport"),
 ("2025-26 Bowman U NOW Basketball March Madness Hobby Box","Bowman U exclu"),
 ("2025-26 Bowman University Best Basketball Hobby Box","Bowman Best exclu"),
 ("2025-26 Bowman Chrome Basketball 1st Edition Hobby Box","Bowman Chrome 1st Edition exclu"),
 ("2025-26 Bowman Basketball Sapphire Hobby Box","Bowman Sapphire n'est pas le Bowman Hobby standard"),
 ("2025-26 Topps Signature Class Basketball Sapphire Hobby Box","Sapphire generalise a toutes les familles Topps"),
 ("2025-26 Topps NBA Hoops Basketball Monster Box","Monster generalise a toutes les familles Topps"),
 ("2025-26 Topps Chrome Basketball Sapphire Edition Box","Sapphire sans format explicite -> REVIEW"),
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
    good = m.sku_id == (exp if exp.startswith(("TOPPS", "PANINI_")) else P + exp)
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

# sealed_product : verdicts structurels, sans blacklist de joueurs
for _t, _w in [("2025-26 Cooper Flagg Bowman Hobby Stars Rookie RC HS-3", False),
               ("Trayce Jackson-Davis 2023-24 Panini Mosaic #PM-TJD Pictographs Mosaic Choice", False),
               ("2025-26 Bowman Basketball Hobby Box", True),
               ("2023-24 Topps Chrome Basketball Value Blaster Box", True),
               ("2023-24 Panini Select Basketball Mega 20-Box Case (Green Shock Prizm)", True)]:
    _g = hunt.sealed_product(hunt.norm(_t))
    if _g is not _w: fails.append(("SEALED", _t, _w, _g))
    print(f"{'PASS' if _g is _w else 'FAIL'} sealed={str(_g):<5} {_t[:56]}")
# H/I — quantité et cloison de comparabilité
_skmap = {s["id"]: s for s in skus}
for _t, _sid, _wq in [("2023-24 Panini Mosaic Basketball 6-Box Lot", None, 6),
                      ("2023-24 Panini Select Basketball Mega 20-Box Case (Green Shock Prizm)", "PANINI_2023-24_SELECT_MEGA_CASE", 20),
                      ("2023-24 Panini Phoenix Basketball Blaster Box", None, 1),
                      ("2025-26 Bowman Basketball Sealed Hobby Case 12 Boxes", "TOPPS_2025-26_BOWMAN_HOBBY_CASE", 12)]:
    _q = hunt.parse_quantity(hunt.norm(_t), _skmap.get(_sid))
    if _q != _wq: fails.append(("QTY", _t, _wq, _q))
    print(f"{'PASS' if _q == _wq else 'FAIL'} qty={_q:<3} attendu {_wq:<3} {_t[:50]}")
_k1 = hunt.exact_comp_key("X", hunt.norm("2023-24 Panini Select Basketball Mega Box"))
_k6 = hunt.exact_comp_key("X", hunt.norm("2023-24 Panini Select Basketball Mega 6-Box Lot"))
_ks = hunt.exact_comp_key("X", hunt.norm("2025-26 Topps Chrome Basketball Sapphire Edition Hobby Box"))
for _n, _c in [("lot de 6 et boite unique ne partagent pas la cloison", _k1 != _k6),
               ("Sapphire et standard ne partagent pas la cloison", _k1 != _ks)]:
    if not _c: fails.append(("KEY", _n))
    print(f"{'PASS' if _c else 'FAIL'} {_n}")
# ---------------------------------------------------------------------------
# Les trois faux positifs remontés par le run de production du 23/08
# ---------------------------------------------------------------------------
_FP = []
def _fp(name, cond):
    _FP.append(name)
    if not cond: fails.append(("FP", name))
    print(f"{'PASS' if cond else 'FAIL'} {name}")

# 1. « Hobby, Blaster Box » : un blaster à 38 $ rattaché au SKU Hobby dont la médiane
#    demandée est de 422 $, soit un ASK DEAL affiché à -91 %.
_t1 = hunt.norm("2024-25 Panini Select Basketball Hobby, Blaster Box (Green & Red Mojo)")
_fp("une virgule ne transforme pas un blaster en boîte hobby",
    hunt.parse_format(_t1) == "Hobby Blaster")
_fp("« Hobby Mega Box » reste un hobby mega",
    hunt.parse_format(hunt.norm("2023-24 Panini Prizm Basketball Hobby Mega Box")) == "Hobby Mega")
_fp("une vraie boîte hobby reste une boîte hobby",
    hunt.parse_format(hunt.norm("2024-25 Panini Select Basketball Hobby Box")) == "Hobby")
_fp("le garde-fou refuse « Hobby » dès qu'un format retail est nommé",
    not hunt.format_guard_ok("Hobby", hunt.norm("Prizm Basketball Hobby Box Blaster")))
_fp("il ne gêne pas une boîte hobby ordinaire",
    hunt.format_guard_ok("Hobby", hunt.norm("2025-26 Topps Chrome Basketball Hobby Box")))

# 2. Topps Chrome Black, gamme premium, confondue avec Chrome Hobby : médiane demandée
#    gonflée à 960 $ sur 11 vendeurs, et une présale à 700 $ présentée comme un deal.
_kb = hunt.exact_comp_key("TOPPS_2025-26_CHROME_HOBBY",
                          hunt.norm("2025-26 Topps Chrome Black Basketball Hobby Box"))
_ks2 = hunt.exact_comp_key("TOPPS_2025-26_CHROME_HOBBY",
                           hunt.norm("2025-26 Topps Chrome Basketball Hobby Box"))
_fp("Chrome Black ne partage pas la cloison du Chrome standard", _kb != _ks2)
_fp("le Chrome standard garde bien la cloison standard", _ks2.endswith("|std|x1"))
_fp("« Black Friday » ne crée pas une édition", "black" not in
    hunt.exact_comp_key("S", hunt.norm("Topps Chrome Hobby Box Black Friday Sale")))

# 3. Une précommande d'avril 2026 comparée à des boîtes disponibles aujourd'hui.
for _t in ("2025-26 Topps Bowman Basketball Blaster Box Releases 4/22/26",
           "2025-26 Topps Chrome Black Basketball Hobby Box (Presale)",
           "2026 Topps Basketball Hobby Box Pre-Order"):
    _fp(f"précommande cloisonnée : {_t[:44]}",
        "preorder" in hunt.exact_comp_key("S", hunt.norm(_t)))
_fp("une boîte disponible n'est pas marquée précommande",
    "preorder" not in hunt.exact_comp_key("S", hunt.norm("2025-26 Bowman Basketball 6-pack Mega Box")))
# Le titre peut mentir par omission : sportscardjunction titre « 2025-26 Bowman Basketball
# Blaster Box » et range le produit sous /products/pre-order-...-releases-4-22-26.
_tb = hunt.norm("2025-26 Bowman Basketball Blaster Box")
_fp("le slug d'URL trahit la précommande que le titre tait",
    hunt.exact_comp_key("S", _tb, None,
        "https://sportscardjunction.com/products/pre-order-2025-26-bowman-basketball-blaster-box-releases-4-22-26")
    == "S|preorder|x1")
_fp("la même boîte réellement disponible garde la cloison standard",
    hunt.exact_comp_key("S", _tb, None,
        "https://ehcards.com/products/2025-26-bowman-basketball-blaster-box") == "S|std|x1")
_fp("précommande et stock ne se comparent jamais",
    hunt.exact_comp_key("S", _tb, None, "https://x.test/products/pre-order-bowman")
    != hunt.exact_comp_key("S", _tb, None, "https://x.test/products/bowman"))

# ---------------------------------------------------------------------------
# Clôture de l'audit Mosaic du 30/08
# ---------------------------------------------------------------------------
_MO = []
def _mo(name, got, exp=True):
    _MO.append(name); ok = (got == exp)
    if not ok: fails.append(("MOSAIC", name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

import yaml as _yaml
_SK = _yaml.safe_load(open("catalog.yaml", encoding="utf-8"))["skus"]
_m = lambda t: hunt.match_title(t, _SK)

# 1. « Fst BRK » : troisième graphie d'un même produit, qui plafonnait à 0,77 en REVIEW.
_r = _m("2023-24 Panini Mosaic Basketball Fst BRK Box")
_mo("« Fst BRK » est rattaché au Fast Break", _r.sku_id, "PANINI_2023-24_MOSAIC_FAST_BREAK")
_mo("et ne plafonne plus en REVIEW", _r.score >= 0.95)
for _t in ("2023-24 Panini Mosaic Basketball Fast Break Box",
           "2023-24 Panini Mosaic Basketball Fast Brk Box",
           "2023-24 Panini Mosaic Basketball FST-BRK Box"):
    _mo(f"graphie reconnue : {_t[-18:]}", _m(_t).sku_id, "PANINI_2023-24_MOSAIC_FAST_BREAK")

# 2. Hobby Blaster : identité propre, jamais confondue avec Hobby ni avec Blaster.
for _t in ("2023-24 Panini Mosaic Basketball Hobby 6-Pack Blaster Box",
           "2023-24 Panini Mosaic Basketball Hobby Blaster Box (Green Prizm)",
           "2023/24 Panini Mosaic Basketball 6-Pack Hobby Blaster Box"):
    _mo(f"Hobby Blaster 23-24 : {_t[-26:]}", _m(_t).sku_id, "PANINI_2023-24_MOSAIC_HOBBY_BLASTER")
for _t in ("2024-25 Panini Mosaic Basketball Hobby 6-Pack Blaster Box",
           "2024-25 Panini Mosaic Basketball Hobby Blaster Box",
           "2024/25 Panini Mosaic Basketball 6-Pack Hobby Blaster Box"):
    _mo(f"Hobby Blaster 24-25 : {_t[-26:]}", _m(_t).sku_id, "PANINI_2024-25_MOSAIC_HOBBY_BLASTER")
_mo("un Hobby Blaster n'est jamais un Hobby",
    _m("2023-24 Panini Mosaic Basketball Hobby 6-Pack Blaster Box").sku_id != "PANINI_2023-24_MOSAIC_HOBBY")
_mo("ni un Blaster",
    _m("2023-24 Panini Mosaic Basketball Hobby 6-Pack Blaster Box").sku_id != "PANINI_2023-24_MOSAIC_BLASTER")

# non-régression : les trois identités voisines ne bougent pas
_mo("le Blaster reste le Blaster",
    _m("2023-24 Panini Mosaic Basketball Blaster Box").sku_id, "PANINI_2023-24_MOSAIC_BLASTER")
_mo("un 6-Pack Blaster sans « hobby » reste le Blaster",
    _m("2023/24 Panini Mosaic Basketball 6-Pack Blaster Box").sku_id, "PANINI_2023-24_MOSAIC_BLASTER")
_mo("le Hobby reste le Hobby",
    _m("2023-24 Panini Mosaic Basketball Hobby Box").sku_id, "PANINI_2023-24_MOSAIC_HOBBY")
_mo("l'Optic Hobby Blaster n'est pas perturbé",
    _m("2023-24 Donruss Optic Basketball 6-Pack Hobby Blaster Box").sku_id,
    "PANINI_2023-24_OPTIC_HOBBY_BLASTER")
_mo("le Select « Hobby, Blaster Box » reste non rattaché",
    _m("2024-25 Panini Select Basketball Hobby, Blaster Box (Green & Red Mojo)").sku_id, None)

# 3. Le sold Mosaic Blaster du 30/08 : n=3 sur 120 j -> LOW, donc jamais sold-backed.
_bl = next(x for x in _SK if x["id"] == "PANINI_2023-24_MOSAIC_BLASTER")
_mo("le sold Mosaic Blaster est en base", _bl.get("market_sold_us"), 38)
_mo("sa confiance se DÉRIVE à LOW", hunt.sold_confidence(_bl), "LOW")
_mo("un sold LOW ne peut pas rendre un verdict adossé aux ventes",
    hunt.price_verdict(30.0, {"value": 38, "confidence": "LOW", "basis": "exact_sold"}, None)["basis"] != "sold")
# Le signalement a fait son travail : le seuil a été tranché à la main le 30/08 (40 -> 32,
# soit 15 % sous le sold de 38). Ce qu'on vérifie désormais, c'est le RÉSULTAT de la règle.
_mo("le seuil d'achat est repassé sous les ventes réalisées",
    _bl["buy_below_usd"] < _bl["market_sold_us"])
# 38 x 0,85 = 32,30, arrondi à 32,00 : un seuil d'achat se retient de tête. On vérifie donc
# la règle (~15 % sous les ventes, la marge exigée en confiance faible), pas la décimale.
_mo("il vaut environ 15 % sous le sold, la marge exigée en confiance faible",
    abs(_bl["buy_below_usd"] / _bl["market_sold_us"] - 0.85) < 0.02)
_mo("et la revue est refermée", _bl.get("thresholds_review_needed"), False)
_mo("le Mega reste sans sold exploitable",
    next(x for x in _SK if x["id"] == "PANINI_2023-24_MOSAIC_MEGA").get("market_sold_us"), None)

# ---------------------------------------------------------------------------
# Le « 2 » de H2 n'est pas une quantité
# ---------------------------------------------------------------------------
_H2 = []
def _h2(t, exp):
    _H2.append(t); got = hunt.parse_quantity(hunt.norm(t))
    if got != exp: fails.append(("H2", t, got, exp))
    print(f"{'PASS' if got == exp else 'FAIL'} quantité x{exp} : {t}")

# un chiffre collé à une lettre appartient au nom du produit, pas au conditionnement
_h2("2023-24 Panini Select Basketball H2 Box", 1)
_h2("2023-24 Panini Select Basketball H2 Hobby Hybrid Box", 1)
_h2("2025-26 Panini Origins EuroLeague Basketball H2 Box", 1)
# ... et un chiffre isolé reste une quantité
_h2("2023-24 Panini Select Basketball 2-Box Lot", 2)
_h2("2023-24 Panini Mosaic Fast Break 20-Box Case", 20)
_h2("2025-26 Bowman Basketball Hobby 12-Box Case", 12)
# le cas croisé : les deux dans le même titre, seul le second compte
_h2("2023-24 Panini Select H2 2-Box Lot", 2)

# et la conséquence : deux graphies du même produit retombent dans la MÊME cloison
_k_a = hunt.exact_comp_key("SEL_H2", hunt.norm("2023-24 Panini Select Basketball H2 Box"))
_k_b = hunt.exact_comp_key("SEL_H2", hunt.norm("2023-24 Panini Select Basketball H2 Hobby Hybrid Box"))
_H2.append("cloison")
if _k_a != _k_b: fails.append(("H2", "cloison", _k_a, _k_b))
print(f"{'PASS' if _k_a == _k_b else 'FAIL'} « H2 Box » et « H2 Hobby Hybrid Box » partagent la cloison")
_H2.append("lot distinct")
_k_lot = hunt.exact_comp_key("SEL_H2", hunt.norm("2023-24 Panini Select H2 2-Box Lot"))
if _k_lot == _k_a: fails.append(("H2", "lot distinct", _k_lot, "≠ " + _k_a))
print(f"{'PASS' if _k_lot != _k_a else 'FAIL'} un vrai lot de deux garde sa cloison à part")

print(f"TOTAL AVEC SEALED : {len(POS)+len(P2)+len(NEG)+11+len(_FP)+len(_MO)+len(_H2)} tests, {len(fails)} FAIL")
sys.exit(1 if fails else 0)
