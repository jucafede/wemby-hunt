#!/usr/bin/env python3
"""Les garde-fous du 07/09 — ceux qui empêchent le tableau de recommander sans preuve.

Ils sont nés d'un constat : sur 258 boîtes Wemby en stock, ZÉRO n'avait de vente réalisée en
base, et pourtant toutes portaient un palier « affaire ». Un produit sans Wembanyama avait même
obtenu un match parfait et se présentait comme la meilleure occasion du catalogue.

Chaque test ici correspond à une règle énoncée, et chacune doit échouer bruyamment si on la
retire.
"""
import sys
import yaml
import hunt
import alerts

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

SKUS = yaml.safe_load((hunt.ROOT / "catalog.yaml").read_text(encoding="utf-8"))["skus"]

# ---------------------------------------------- 1. identité : refus ou ambiguïté -> UNKNOWN
# Le cas réel : rattaché à Topps Chrome Hobby avec un score de 1,0, puis affiché à 42 % de sa
# référence de vente. McDonald's All-American est un match de lycéens américains ; Wembanyama
# est français et n'y a jamais joué. Le prix était bas parce que ce n'était pas le produit.
mcdo = "2023/24 Topps Chrome McDonald's All-American Basketball Hobby Box"
check("un produit d'une AUTRE gamme n'est plus rattaché", hunt.match_title(mcdo, SKUS).sku_id, None)
check("et son score tombe à zéro", hunt.match_title(mcdo, SKUS).score, 0.0)
# la gamme de base, elle, matche toujours : le garde-fou ne doit pas coûter de vrais produits
check("la gamme de base reste rattachée",
      hunt.match_title("2023-24 Topps Chrome Basketball Hobby Box", SKUS).sku_id,
      "TOPPS_2023-24_CHROME_HOBBY")
check("une variante qui a son propre SKU aussi",
      hunt.match_title("2023-24 Topps Chrome Basketball Sapphire Edition Hobby Box", SKUS).sku_id,
      "TOPPS_2023-24_CHROME_SAPPHIRE")
check("Chrome Black garde son identité",
      hunt.match_title("2025-26 Topps Chrome Black Basketball Hobby Box", SKUS).sku_id,
      "TOPPS_2025-26_CHROME_BLACK_HOBBY")
check("Prizm n'est pas affecté",
      hunt.match_title("2023-24 Panini Prizm Basketball Hobby Box", SKUS).sku_id,
      "PANINI_2023-24_PRIZM_HOBBY")
check("le nom de gamme se compare à l'identifiant ET au set",
      hunt.foreign_set("topps chrome sapphire", hunt.sku_haystack(
          {"id": "TOPPS_2023-24_CHROME_SAPPHIRE", "set": "Topps Chrome"})), None)

# ---------------------------------------------- 2. aucun intérêt Wemby sans présence confirmée
base = {"wemby_rc": True, "tier": "hobby", "market_ask_from": ["a", "b", "c", "d"], "league": None}
check("présence confirmée -> score possible",
      alerts.wemby_score(dict(base, wemby_present=True), "🔥🔥 STRONG DEAL", 65, "trusted", True)[0] > 0)
check("présence NON VÉRIFIÉE -> score nul",
      alerts.wemby_score(dict(base, wemby_present=None), "🔥🔥 STRONG DEAL", 65, "trusted", True)[0], 0)
check("présence absente -> score nul",
      alerts.wemby_score(dict(base, wemby_present=False), "🔥🔥 STRONG DEAL", 65, "trusted", True)[0], 0)
check("et la raison distingue « absent » de « non vérifié »",
      "JAMAIS VÉRIFIÉE" in alerts.wemby_score(dict(base, wemby_present=None),
                                              "🔥🔥 STRONG DEAL", 65, "trusted", True)[1][0])

# ---------------------------------------------- 3. aucun BUY sans ventes réalisées
sold_ok = {"basis": "exact_sold", "confidence": "HIGH", "value": 100.0,
           "sample_size": 7, "window_days": 30}
ask_ok = {"value": 100.0, "confidence": "HIGH", "shops": 5}
check("une remise adossée aux VENTES donne un verdict d'achat",
      hunt.price_verdict(70.0, sold_ok, None)["verdict"], "STRONG BUY")
check("la même remise adossée aux ASKS n'en donne aucun",
      hunt.price_verdict(70.0, None, ask_ok)["verdict"], "INSUFFICIENT DATA")
check("et elle est étiquetée ASK REFERENCE ONLY",
      "ASK REFERENCE ONLY" in hunt.price_verdict(70.0, None, ask_ok)["why"])
check("la nature de la preuve est nommée",
      hunt.price_verdict(70.0, None, ask_ok)["basis"], "ask_only")
check("l'écart est conservé pour SIGNALER l'anomalie",
      hunt.price_verdict(70.0, None, ask_ok)["ask_gap"], -30.0)
check("un sold peu fiable ne donne pas de verdict d'achat non plus",
      hunt.price_verdict(70.0, dict(sold_ok, confidence="LOW"), None)["verdict"], "INSUFFICIENT DATA")
check("aucun palier ASK ne subsiste dans le classement",
      any(k.startswith("ASK") for k in hunt.VERDICT_RANK), False)

# ---------------------------------------------- 4. deux asks ne font jamais un marché
check("le seuil de vendeurs est explicite", hunt.ASK_REF_MIN_SHOPS, 3)
deux = {"value": 100.0, "confidence": "HIGH", "shops": 2}
pv2 = hunt.price_verdict(70.0, None, deux)
check("2 vendeurs ne produisent AUCUNE référence", pv2["ref"], None)
check("ni écart", pv2["gap"], None)
check("et la page dit pourquoi", "trop peu pour une référence" in pv2["why"])
check("3 vendeurs suffisent", hunt.price_verdict(70.0, None, dict(deux, shops=3))["ref"], 100.0)
# la phrase ne doit jamais appeler « ventes » un objectif calculé sur des asks
check("un objectif calculé sur des asks nomme les prix demandés",
      "prix demandés" in hunt.buy_below_v2({"value": 100.0, "confidence": "HIGH",
                                            "basis": "ask_only"})[1])
check("et ne parle jamais de ventes",
      "ventes" not in hunt.buy_below_v2({"value": 100.0, "confidence": "HIGH",
                                         "basis": "ask_only"})[1])

# ---------------------------------------------- 5. un vendeur au stock non prouvable ne décide pas
src = yaml.safe_load((hunt.ROOT / "sources.yaml").read_text(encoding="utf-8"))
hunt.load_stock_unreliable(src)
check("kutogo est reconnu comme non prouvable", hunt.stock_provable("kutogo"), False)
check("une boutique ordinaire l'est", hunt.stock_provable("rbicru7"))
check("le registre vient de sources.yaml", "kutogo" in hunt.STOCK_UNRELIABLE)

# ---------------------------------------------- 6. risque vendeur : Kutogo, 07/09
# Vérification manuelle : l'adresse revendiquée (Pueblo West, Colorado) montre en Street View
# de septembre 2023 un bâtiment industriel sans enseigne ; les photos récentes du card shop
# sont publiées par le propriétaire lui-même. Flickr et Instagram ne contiennent que ses
# propres visuels. Aucune source INDÉPENDANTE ne confirme l'établissement. Ce n'est pas une
# preuve de fraude — c'est une absence de preuve d'activité, et cela suffit à retirer à ce
# vendeur le droit de conclure un achat.
check("kutogo est déclaré à risque élevé", hunt.high_risk("kutogo"))
check("et non vérifié", hunt.unverified("kutogo"))
check("l'étiquette affichée est explicite",
      hunt.seller_flag("kutogo"), "HIGH-RISK / UNVERIFIED SELLER")
check("une boutique ordinaire ne porte aucune étiquette", hunt.seller_flag("rbicru7"), None)

_sold = {"verdict": "STRONG BUY", "basis": "sold", "gap": -36.2, "ref": 525.0,
         "confidence": "MEDIUM", "why": "3 ventes réalisées sur 90 j"}
check("un STRONG BUY chez kutogo est annulé",
      hunt.cap_verdict(_sold, "kutogo")["verdict"], "VERIFY BEFORE BUYING")
check("un BUY aussi",
      hunt.cap_verdict(dict(_sold, verdict="BUY"), "kutogo")["verdict"], "VERIFY BEFORE BUYING")
check("le verdict d'origine est conservé, pas effacé",
      hunt.cap_verdict(_sold, "kutogo")["capped_from"], "STRONG BUY")
check("l'écart de marché reste calculé — c'est un signal utile",
      hunt.cap_verdict(_sold, "kutogo")["gap"], -36.2)
check("et la raison dit ce qui bloque",
      "le prix ne vaut que si la commande arrive" in hunt.cap_verdict(_sold, "kutogo")["why"])
check("le même verdict ailleurs n'est pas touché",
      hunt.cap_verdict(_sold, "rbicru7")["verdict"], "STRONG BUY")
check("un EXPENSIVE n'a pas besoin d'être plafonné",
      hunt.cap_verdict(dict(_sold, verdict="EXPENSIVE"), "kutogo")["verdict"], "EXPENSIVE")
check("VERIFY BEFORE BUYING n'ouvre jamais BUY NOW",
      hunt.VERDICT_RANK["VERIFY BEFORE BUYING"], hunt.VERDICT_RANK["INSUFFICIENT DATA"])
# le stock déclaré par WooCommerce ne suffit jamais à confirmer chez ce vendeur
check("le stock de kutogo n'est pas prouvable", hunt.stock_provable("kutogo"), False)

# ---------------------------------------------- 7. la porte dérobée des déclencheurs, 10/09
# En production, BUY NOW affichait quinze cartes portant TOUTES « INSUFFICIENT DATA », sous un
# bandeau annonçant « 15 achats adossés à des ventes réalisées ». Elles entraient par leurs
# seuls déclencheurs historiques — restock, plus-bas déjà vu — hérités d'avant la règle.
def _e(sid, prix, pv, triggers=(), gap=None, ref=None, shop="sh"):
    o = ("S", shop, "titre", prix, 1, f"https://x.test/{sid}", 1.0, "2026-09-10T00:00:00",
         "", "EXACT", None, 1, prix, f"{sid}|std|x1", "US", "USD")
    return {"o": o, "key": f"{sid}|std|x1", "sid": sid, "sku": {}, "available": True,
            "triggers": list(triggers), "descriptors": [], "gap": gap, "ref": ref,
            "kind": None, "mem": None, "comp": "EXACT", "hist": None, "region": "US", "pv": pv}

_insuff = {"verdict": "INSUFFICIENT DATA", "basis": None, "gap": None, "ref": None,
           "confidence": "LOW", "why": "aucune vente"}
_avec_decl = _e("X", 4.99, _insuff, triggers=["NEW_LOW"], gap=-40.0, ref=8.25)
check("un plus-bas historique SANS vente n'ouvre plus BUY NOW", hunt.hot_now([_avec_decl]), [])
# RÈGLE RESSERRÉE LE 15/09 : il ne descend pas non plus en anomalie. Son écart se mesure
# contre son propre passé, pas contre d'autres vendeurs, et la section promet une comparaison
# entre vendeurs. Sa place est dans « Surveiller », où un plus-bas historique est à sa place.
check("un plus-bas historique seul n'est pas une anomalie de prix entre vendeurs",
      hunt.price_anomalies([_avec_decl]), [])
check("une vente réalisée ouvre toujours BUY NOW",
      len(hunt.hot_now([_e("Y", 50.0, {"verdict": "BUY", "basis": "sold", "gap": -20.0,
                                       "ref": 62.0, "confidence": "HIGH", "why": "7 ventes"})])), 1)

# ---------------------------------------------- 8. les anomalies doivent être RARES, 15/09
# En production, la section affichait vingt lignes dont DOUZE sachets — un « Pack » à 0,75 $
# comparé à une médiane de 8,25 $ sur trois vendeurs. Le format « Pack » couvre le sachet de
# quatre cartes ET le fat pack de quinze : l'écart ne compare pas deux fois le même objet.
# Cinq autres lignes annonçaient un écart « vs les autres vendeurs » avec une colonne Réf. vide.
_CAT = {"skus": [{"id": "BOX", "format": "Hobby", "wemby_rc": False},
                 {"id": "PACK", "format": "Pack", "wemby_rc": False},
                 {"id": "RC", "format": "Blaster", "wemby_rc": True}]}
def _ao(sid, prix, gap, shops, shop="sh"):
    pv = {"verdict": "INSUFFICIENT DATA", "basis": "ask_only", "gap": None, "ref": 1.0,
          "confidence": "HIGH", "why": "x", "ask_gap": gap, "ask_shops": shops}
    return _e(sid, prix, pv, shop=shop)

check("un sachet n'entre jamais, si bas soit-il",
      hunt.price_anomalies([_ao("PACK", 0.75, -93, 5)], cat=_CAT), [])
check("un article sous 20 $ non plus",
      hunt.price_anomalies([_ao("BOX", 12.0, -60, 5)], cat=_CAT), [])
check("trois vendeurs ne suffisent pas à fonder une anomalie",
      hunt.price_anomalies([_ao("BOX", 300.0, -60, 3)], cat=_CAT), [])
check("un écart de -15 % n'est plus une anomalie",
      hunt.price_anomalies([_ao("BOX", 300.0, -15, 6)], cat=_CAT), [])
check("une vraie anomalie passe", len(hunt.price_anomalies([_ao("BOX", 300.0, -40, 6)], cat=_CAT)), 1)
check("et son motif nomme le nombre de vendeurs",
      "6 autres vendeurs" in hunt.price_anomalies([_ao("BOX", 300.0, -40, 6)], cat=_CAT)[0][1])
# une ligne sans vendeurs comparables ne peut pas figurer sous un titre qui promet une comparaison
_sans = _e("BOX", 300.0, {"verdict": "INSUFFICIENT DATA", "basis": None, "gap": None,
                          "ref": None, "confidence": "LOW", "why": "x"},
           triggers=["NEW_LOW"], gap=-50.0, ref=600.0)
check("une ligne sans vendeurs comparables n'y figure plus",
      hunt.price_anomalies([_sans], cat=_CAT), [])
# l'exception qui prime sur toutes les règles
hunt.STOCK_UNRELIABLE = {"kutogo"}
hunt.SELLER_RISK = {"kutogo": "HIGH"}
_cap = _e("PACK", 5.0, {"verdict": "VERIFY BEFORE BUYING", "capped_from": "STRONG BUY",
                        "basis": "sold", "gap": -40.0, "ref": 10.0, "confidence": "HIGH",
                        "why": "x"}, shop="kutogo")
check("un achat annulé par le risque vendeur entre TOUJOURS, même sur un sachet",
      len(hunt.price_anomalies([_cap], cat=_CAT)), 1)
# la chasse d'abord : une RC Wemby passe devant
_rc = _ao("RC", 300.0, -30, 6)
_autre = _ao("BOX", 300.0, -50, 6)
check("une RC Wemby est classée avant un écart plus large",
      hunt.price_anomalies([_autre, _rc], cat=_CAT)[0][2]["sid"], "RC")
hunt.STOCK_UNRELIABLE, hunt.SELLER_RISK = set(), {}
check("la liste est plafonnée", len(hunt.price_anomalies(
      [_ao("BOX", 300.0, -40, 6, shop=f"s{i}") for i in range(40)], cat=_CAT)) <= 12)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
