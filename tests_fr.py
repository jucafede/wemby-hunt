"""Marché FR — Best FR, cloisonnement US/FR, et non-régression du moteur US.
Un vendeur FR est un CANAL D'ACHAT. Ses prix ne deviennent jamais une valeur de marché."""
import sys, yaml, pathlib
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<62} got={got!r}")

cat = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
S = {x["id"]: x for x in cat["skus"]}

def E(key, shop, price, avail=True, region="FR", qty=1, cur="EUR"):
    o = ("SKU", shop, "titre", price, 1 if avail else 0, f"https://{shop}.test/products/x", 1.0,
         "2026-08-22T00:00:00", "", "EXACT", None, qty, round(price / qty, 2), key, region, cur)
    return {"o": o, "key": key, "sid": "SKU", "sku": S["PANINI_2023-24_MOSAIC_BLASTER"],
            "available": avail, "triggers": [], "descriptors": [], "gap": None, "ref": None,
            "kind": None, "mem": None, "comp": "EXACT", "hist": None, "region": region, "currency": cur}

# ---- 1/2/3/4/5 : Best FR
K = "PANINI_2023-24_MOSAIC_BLASTER|std|x1"
b = hunt.best_fr([E(K, "tanteo", 57.90), E(K, "qscards", 62.00), E(K, "shopuscards", 49.99)])
check("1 · Best FR retient l'offre comparable la moins chère", b[K]["shop"], "shopuscards")
check("5 · ShopUScards peut battre les deux autres", b[K]["price"], 49.99)
check("9 · les autres offres FR sont comptées", b[K]["others"], 2)
b2 = hunt.best_fr([E(K, "tanteo", 57.90), E(K, "qscards", 42.00)])
check("4 · QS Cards peut battre Tanteo", b2[K]["shop"], "qscards")
b3 = hunt.best_fr([E(K, "tanteo", 39.90), E(K, "qscards", 42.00)])
check("3 · Tanteo peut battre QS Cards", b3[K]["shop"], "tanteo")
b4 = hunt.best_fr([E(K, "tanteo", 10.00, avail=False), E(K, "qscards", 42.00)])
check("2 · une offre en rupture ne gagne jamais Best FR", b4[K]["shop"], "qscards")
check("Best FR ignore un prix nul", hunt.best_fr([E(K, "tanteo", 0.0)]), {})
check("une observation US n'entre pas dans Best FR",
      hunt.best_fr([E(K, "ehcards", 19.99, region="US")]), {})

# ---- 12/14/15/24 : la cloison de comparabilité départage
KX6 = "PANINI_2023-24_MOSAIC_BLASTER|std|x6"
bl = hunt.best_fr([E(K, "tanteo", 57.90), E(KX6, "qscards", 240.00, qty=6)])
check("14 · un lot x6 ne concourt pas contre une boîte x1", sorted(bl), sorted([K, KX6]))
check("14 · l'unitaire du lot est conservé", bl[KX6]["unit"], 40.0)
check("14 · le total du lot est conservé", bl[KX6]["price"], 240.0)

# ---- 7/11/13 : Hobby Pack ≠ Hobby Box, cas réel ShopUScards
skus = cat["skus"]
pack = hunt.match_title("2023/24 Panini Prizm Turkish Airlines EuroLeague Basketball Hobby Pack", skus)
box = hunt.match_title("2023/24 Panini Prizm Turkish Airlines EuroLeague Basketball Hobby Box", skus)
check("7 · Hobby Box EuroLeague correctement matchée",
      box.sku_id, "PANINI_2023-24_PRIZM_EUROLEAGUE_HOBBY")
check("7 · Hobby Pack n'est PAS la Hobby Box", pack.sku_id != box.sku_id)
check("11 · le Pack ne devient pas une boîte", pack.fmt, "Pack")
check("13 · Mega n'est pas Blaster",
      hunt.match_title("2023-24 Panini Mosaic Basketball Mega Box", skus).sku_id
      != hunt.match_title("2023-24 Panini Mosaic Basketball Blaster Box", skus).sku_id)
check("12 · Case n'est pas Box",
      hunt.match_title("2023-24 Panini Mosaic Basketball 20-Box Case", skus).sku_id, None)

# ---- titres FR réels : le matcher les traite comme les autres
fr_real = hunt.match_title("2024-25 Panini Prizm Cartes Basketball NBA Blaster Box", skus)
check("titre FR réel (Tanteo) correctement matché", fr_real.sku_id, "PANINI_2024-25_PRIZM_BLASTER")
check("un titre FR hors basket est rejeté",
      hunt.match_title("2025-26 Panini Select Ligue 1 Football Blaster Box", skus).sku_id, None)

# ---- 8/9/10 : un prix FR ne contamine rien
# Le SKU témoin doit être vendu chez Tanteo ET dépourvu de sold US. Le Mosaic Blaster 23-24
# jouait ce rôle jusqu'à ce qu'il reçoive un vrai sold le 30/08 : la garde ci-dessous fait
# échouer le test si le témoin cesse d'être valide, plutôt que de le laisser mentir.
# Témoin : un SKU qui porte un prix EUROPÉEN et RIEN d'américain. C'est le seul cas où
# l'assertion prouve quelque chose — sur un SKU sans données du tout, elle est triviale.
mos = S["PANINI_2023-24_PREMIUM_STOCK_MEGA"]
check("le témoin porte bien un prix européen", bool(mos.get("eu_reference_eur")), True)
check("et rien du côté américain", (mos.get("market_sold_us"), mos.get("market_ask_us")), (None, None))
check("8 · un prix FR ne crée pas de market_sold_us", mos.get("market_sold_us"), None)
check("9 · un prix FR ne crée pas de sold_confidence", hunt.sold_confidence(mos), None)
check("10 · un prix FR seul ne produit aucun GO",
      hunt.decide(True, -50, None, "EXACT", 40.0, 20.0, mos), "PRICE ANOMALY — NO SOLD DATA")
check("un prix FR n'est jamais une référence marché", hunt.market_ref(mos), (None, None))
# et réciproquement : un vrai sold US, lui, EST une référence — sinon la garde ne prouve rien
check("un sold US renseigné est bien une référence",
      hunt.market_ref(S["PANINI_2023-24_MOSAIC_BLASTER"]), (38.0, "sold"))

# ---- 6/7 : santé du marché FR
srcs = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/sources.yaml", encoding="utf-8"))["shops"]
check("6 · une source FR morte n'efface pas le marché FR",
      "PARTIAL" in (hunt.fr_market_status({"tanteo": ("DEAD", "x"), "qscards": ("HEALTHY", "y")}, srcs) or ""))
# « Complet » veut dire : TOUTES les sources FR crawlées sont saines. Le fixture se construit
# donc depuis sources.yaml — sinon l'ajout d'une source FR ferait échouer un test qui n'a rien
# à dire sur elle.
_crawlable_fr = {x["key"]: ("HEALTHY", "x") for x in srcs
                 if x.get("market_region") == "FR" and x["type"] != "eu_reference"}
check("7 · toutes saines -> marché FR complet",
      "COMPLET" in (hunt.fr_market_status(_crawlable_fr, srcs) or ""))
check("7c · une référence de prix non crawlée ne compte pas dans la santé du marché FR",
      "COMPLET" in (hunt.fr_market_status(_crawlable_fr, srcs) or "")
      and "ludotrotter" not in (hunt.fr_market_status(_crawlable_fr, srcs) or ""))
check("7b · une source en panne retire le « complet »",
      "COMPLET" not in (hunt.fr_market_status(
          {**_crawlable_fr, sorted(_crawlable_fr)[0]: ("DEAD", "x")}, srcs) or ""))

# ---- 18 : aucune régression sur le moteur US
check("18 · une observation FR est exclue de HOT NOW",
      hunt.hot_now([{**E(K, "tanteo", 20.0), "triggers": ["DEAL"], "gap": -30.0, "ref": 40.0}]), [])
# Même raison qu'au cockpit : la liste FR s'allonge à chaque session de prospection. On teste
# la propriété — toute source FR se déclare en euros — pas le décompte.
_fr = sorted(x["key"] for x in srcs if x.get("market_region") == "FR")
check("au moins deux sources FR sont enregistrées", len(_fr) >= 2)
check("les deux boutiques FR crawlées en font partie", {"qscards", "tanteo"} <= set(_fr))
check("aucune source FR n'est déclarée en dollars",
      [x["key"] for x in srcs if x.get("market_region") == "FR" and x.get("currency") != "EUR"], [])
check("elles conservent leur devise native",
      {x["currency"] for x in srcs if x.get("market_region") == "FR"}, {"EUR"})

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
