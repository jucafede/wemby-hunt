#!/usr/bin/env python3
"""Coût rendu, notation, événements — et les confusions qui coûtent cher.

Le test qui compte le plus est le dernier bloc : pack contre box, box contre case, saison
contre saison, ligue contre ligue. Ce sont les quatre façons dont une comparaison de prix
peut mentir sans que rien n'ait l'air cassé.
"""
import sys, yaml
import hunt, alerts

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

CAT = yaml.safe_load((hunt.ROOT / "catalog.yaml").read_text(encoding="utf-8"))
SKUS = CAT["skus"]
BY = {x["id"]: x for x in SKUS}
FX = float(CAT["fx_usd_eur"])

# ---------------------------------------------------------------- coût rendu
eu = alerts.landed_cost_fr(100.0, "EUR", "EU", FX, shipping_eur=14.99)
check("UE : prix + port, rien d'autre", eu.value_eur, 114.99)
check("et la confiance est haute quand le port est connu", eu.confidence, "HIGH")
eu2 = alerts.landed_cost_fr(100.0, "EUR", "EU", FX)
check("port inconnu -> estimation, confiance moyenne", eu2.confidence, "MEDIUM")
us = alerts.landed_cost_fr(100.0, "USD", "US", FX)
check("États-Unis : la TVA et le transitaire s'ajoutent", us.value_eur > 100 * FX * 1.2)
check("et la confiance reste basse — ce sont des moyennes", us.confidence, "LOW")
check("chaque poste est nommé", sorted(us.components), ["port_us_eur", "produit_eur", "transitaire_eur", "tva_eur"])
check("sans prix, aucun montant inventé", alerts.landed_cost_fr(0, "USD", "US", FX).value_eur, None)
check("et la confiance le dit", alerts.landed_cost_fr(None, "USD", "US", FX).confidence, "UNKNOWN")
# un import US n'est jamais gratuit : le rendu dépasse toujours le prix converti
check("un import coûte plus cher que le prix affiché",
      alerts.landed_cost_fr(50.0, "USD", "US", FX).value_eur > 50 * FX)

# ---------------------------------------------------------------- paliers
check("70 % -> STRONG DEAL", alerts.deal_tier(70, 100, "HIGH")[0], "🔥🔥 STRONG DEAL")
check("80 % -> DEAL", alerts.deal_tier(80, 100, "HIGH")[0], "🔥 DEAL")
check("90 % -> GOOD", alerts.deal_tier(90, 100, "HIGH")[0], "🟢 GOOD")
check("100 % -> MARKET", alerts.deal_tier(100, 100, "HIGH")[0], "🟡 MARKET")
check("115 % -> EXPENSIVE", alerts.deal_tier(115, 100, "HIGH")[0], "🟠 EXPENSIVE")
check("130 % -> PASS", alerts.deal_tier(130, 100, "HIGH")[0], "🔴 PASS")
# LE test de doctrine : sans sold fiable, aucun palier et surtout aucun ratio
check("sold absent -> aucun palier", alerts.deal_tier(50, None, None)[0], "NO_RELIABLE_SOLD_DATA")
check("sold LOW -> aucun palier non plus", alerts.deal_tier(50, 100, "LOW")[0], "NO_RELIABLE_SOLD_DATA")
check("et aucun ratio n'est rendu", alerts.deal_tier(50, 100, "LOW")[1], None)
check("un rendu inconnu ne produit pas de palier", alerts.deal_tier(None, 100, "HIGH")[0], "NO_RELIABLE_SOLD_DATA")

# ---------------------------------------------------------------- score
rc = {"wemby_present": True, "wemby_rc": True, "tier": "hobby",
      "market_ask_from": ["a", "b", "c", "d"], "league": None}
s_rc, _ = alerts.wemby_score(rc, "🔥🔥 STRONG DEAL", 65, "trusted", True)
check("une RC NBA très décotée score haut", s_rc >= 75)
draft = dict(rc, wemby_rc=False, league="Collegiate/Draft")
s_dr, _ = alerts.wemby_score(draft, "🔥🔥 STRONG DEAL", 65, "trusted", True)
check("le même prix sur un produit draft score moins", s_dr < s_rc)
absent = dict(rc, wemby_present=False, league="NBL")
s_ab, why_ab = alerts.wemby_score(absent, "🔥🔥 STRONG DEAL", 50, "trusted", True)
check("un produit sans Wembanyama s'effondre", s_ab <= 20)
check("et la raison est dite", "aucun Wembanyama" in why_ab[0])
s_nosold, why_ns = alerts.wemby_score(rc, "NO_RELIABLE_SOLD_DATA", None, "trusted", True)
check("sans sold fiable, le score est PLAFONNÉ", s_nosold <= 60)
check("et le plafond est expliqué", any("plafonné" in w for w in why_ns))
unk = dict(rc, wemby_present=None)
check("présence non vérifiée -> plafond plus bas encore",
      alerts.wemby_score(unk, "🔥🔥 STRONG DEAL", 65, "trusted", True)[0] <= 45)
check("un vendeur à risque retranche",
      alerts.wemby_score(rc, "🔥 DEAL", 75, "high_risk", True)[0]
      < alerts.wemby_score(rc, "🔥 DEAL", 75, "trusted", True)[0])
check("le score reste dans [0,100]",
      0 <= alerts.wemby_score(rc, "🔴 PASS", 300, "high_risk", False)[0] <= 100)

# ---------------------------------------------------------------- événements
sk = {"season": "2023-24", "set": "Recon", "format": "Hobby"}
ev = lambda **kw: {e["type"] for e in alerts.detect_events(**{
    "sku": sk, "price": 100.0, "in_stock": True, "was_in_stock": None, "prev_price": None,
    "hist_low": None, "tier": "🟡 MARKET", "seller_is_new": False, "product_is_new": False, **kw})}
check("un produit inconnu déclenche NEW_PRODUCT et CATALOG_GAP",
      {"NEW_PRODUCT", "CATALOG_GAP"} <= ev(product_is_new=True))
check("un vendeur inconnu déclenche NEW_SELLER", "NEW_SELLER" in ev(seller_is_new=True))
check("une saison révolue en stock déclenche OLD_STOCK", "OLD_STOCK" in ev())
check("une saison courante ne le déclenche pas",
      "OLD_STOCK" not in ev(sku={"season": "2025-26", "set": "x", "format": "y"}))
check("un retour en stock déclenche RESTOCK", "RESTOCK" in ev(was_in_stock=False))
check("un plus-bas déclenche NEW_LOW", "NEW_LOW" in ev(price=50.0, hist_low=60.0))
check("un prix inchangé ne déclenche pas NEW_LOW", "NEW_LOW" not in ev(price=70.0, hist_low=60.0))
check("une baisse de 20 % déclenche PRICE_DROP", "PRICE_DROP" in ev(price=80.0, prev_price=100.0))
check("une baisse de 5 % ne la déclenche pas", "PRICE_DROP" not in ev(price=95.0, prev_price=100.0))
check("le palier fort déclenche STRONG_DEAL", "STRONG_DEAL" in ev(tier="🔥🔥 STRONG DEAL"))
check("et n'est pas confondu avec DEAL", "DEAL" not in ev(tier="🔥🔥 STRONG DEAL"))
check("les neuf types sont couverts", len(alerts.EVENTS), 9)

# ---------------------------------------------------------------- prix invraisemblables
check("un Cactus Jack à 30 € contre 600 € de marché est signalé",
      alerts.implausible(30, None, 600) is not None)
check("le message dit d'aller vérifier à la main",
      "à la main" in alerts.implausible(30, None, 600))
check("une vraie remise de 40 % n'est PAS signalée", alerts.implausible(60, 100, None), None)
check("sans référence, on ne crie pas au loup", alerts.implausible(30, None, None), None)

# ---------------------------------------------------------------- les confusions qui mentent
_m = lambda t: hunt.match_title(t, SKUS)
q = lambda t: hunt.parse_quantity(hunt.norm(t))
k = lambda sid, t: hunt.exact_comp_key(sid, hunt.norm(t))

# La séparation pack / box ne vit PAS dans exact_comp_key : elle vit dans l'identité du SKU,
# parce que le format fait partie de l'identité. Mon premier test forçait le même sku_id des
# deux côtés et échouait donc à juste titre — il testait une garantie qui n'existe pas là.
_pk = _m("2023-24 Panini Prizm Basketball 4-Card Pack")
_bx = _m("2023-24 Panini Prizm Basketball Blaster Box")
check("un pack et une boîte sont deux identités", _pk.sku_id != _bx.sku_id)
check("le pack tombe bien sur le SKU pack", _pk.sku_id, "PANINI_2023-24_PRIZM_PACK")
check("et donc leurs cloisons diffèrent",
      k(_pk.sku_id, "Panini Prizm Basketball 4-Card Pack")
      != k(_bx.sku_id, "Panini Prizm Basketball Blaster Box"))
check("box vs case : la quantité les sépare",
      q("2023-24 Panini Mosaic Fast Break 20-Box Case"), 20)
check("une boîte seule reste à 1", q("2023-24 Panini Mosaic Fast Break Box"), 1)
check("un lot x6 est un lot x6", q("Panini Select Mega 6-Box Lot"), 6)
check("le « 2 » de H2 n'est toujours pas une quantité", q("Panini Select Basketball H2 Box"), 1)
check("2022-23 et 2023-24 ne se confondent pas",
      _m("2022-23 Panini Prizm Basketball Hobby Box").sku_id
      != _m("2023-24 Panini Prizm Basketball Hobby Box").sku_id)
check("une saison pré-Wemby ne tombe sur aucun SKU 2023-24",
      (_m("2022-23 Panini Prizm Basketball Hobby Box").sku_id or "").startswith("PANINI_2022"), False)
check("NBA et EuroLeague sont deux marchés",
      BY["PANINI_2023-24_PRIZM_HOBBY"].get("league")
      != BY["PANINI_2023-24_PRIZM_EUROLEAGUE_HOBBY"].get("league"))
check("NBA et Draft Picks aussi",
      BY["PANINI_2023-24_PRIZM_DRAFT_PICKS_DRAFT_HOBBY"].get("league"), "Collegiate/Draft")
check("Hobby et International Hobby sont deux identités",
      _m("2023-24 Panini Spectra Basketball Hobby Box").sku_id
      != _m("2023-24 Panini Spectra Basketball International Hobby Box").sku_id)
check("un single n'entre jamais",
      bool(hunt.sealed_product(hunt.norm("2023-24 Panini Prizm Victor Wembanyama #136 RC"))), False)
check("une précommande garde sa cloison",
      "preorder" in k("X", "2023-24 Panini Prizm Basketball Hobby Box Pre-Order"))

# doublons entre vendeurs : le même produit chez deux marchands, une seule identité
check("le même produit chez deux vendeurs porte le même SKU",
      _m("2023-24 Panini Recon Basketball Hobby Box").sku_id,
      _m("2023/24 Panini Recon Basketball Hobby Box").sku_id)
# faux SKU créés par le naming : « Hobby, Box » avec virgule reste le Hobby
check("une virgule de vendeur ne crée pas un produit",
      _m("2023-24 Panini Recon Basketball Hobby, Box").sku_id,
      _m("2023-24 Panini Recon Basketball Hobby Box").sku_id)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
