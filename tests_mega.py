#!/usr/bin/env python3
"""Les cinq Mega canoniques, et les corrections du 24/09 qui ne doivent plus régresser.

Chaque test ici correspond à une erreur réellement commise pendant la chasse. Ce ne sont pas
des garanties théoriques : ce sont des cicatrices.
"""
import sys
import mega_hunt as mh
import offers
from mega_targets import TARGETS, PAR_UPC, UPC_VOISINS

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

ident = lambda t, **kw: mh.identifie(t, **kw)

# ------------------------------------------------ le référentiel canonique ne bouge pas
check("cinq produits canoniques", len(TARGETS), 5)
check("chacun porte un UPC unique", len(PAR_UPC), 5)
check("les identifiants sont figés", sorted(t["id"] for t in TARGETS),
      ["prizm_2023_24_mega_green_ice", "prizm_2023_24_mega_red_ice",
       "select_2023_24_hobby_mega_green_shock", "select_2023_24_mega_blue_pink",
       "select_2023_24_mega_red_purple"])
# Blue/Pink fait 32 cartes, les deux autres Select en font 40 : c'est ce qui rend le mélange
# si coûteux, et ce qui permet de valider une identification sans UPC.
check("Blue & Pink contient 32 cartes",
      next(t for t in TARGETS if t["id"] == "select_2023_24_mega_blue_pink")["cards_per_box"], 32)
check("Red & Purple en contient 40",
      next(t for t in TARGETS if t["id"] == "select_2023_24_mega_red_purple")["cards_per_box"], 40)

# ------------------------------------------------ UPC d'abord, et UPC voisin rejeté
check("un UPC exact l'emporte sur tout",
      ident("Panini Prizm 2023-24 Mega 746134160479")["confiance"], "UPC_EXACT")
check("et désigne le bon produit",
      ident("Panini Prizm 2023-24 Mega 746134160479")["target"]["id"],
      "prizm_2023_24_mega_green_ice")
# 746134160462 est le Mega PACK isolé, deux chiffres d'écart avec la boîte
check("l'UPC voisin du Mega Pack est reconnu ET rejeté",
      ident("Prizm Green Ice Mega 746134160462")["confiance"], "UPC_VOISIN")
check("il ne produit aucun rattachement",
      ident("Prizm Green Ice Mega 746134160462")["target"], None)
check("le piège est documenté", "746134160462" in UPC_VOISINS)

# ------------------------------------------------ AMBIGU reste AMBIGU
check("« 2023-24 Select Mega Box » seul n'est jamais attribué",
      ident("2023-24 Panini Select Basketball Mega Box")["confiance"], "AMBIGU")
check("et ne désigne aucun produit",
      ident("2023-24 Panini Select Basketball Mega Box")["target"], None)
check("« 2023-24 Prizm Mega » seul non plus",
      ident("2023-24 Panini Prizm NBA Mega Box")["target"], None)
# la variante nommée lève l'ambiguïté
check("la couleur nommée suffit à trancher",
      ident("2023-24 Panini Select Mega Box Blue & Pink Cracked Ice")["target"]["id"],
      "select_2023_24_mega_blue_pink")
check("Green Shock aussi",
      ident("2023-24 Panini Select Hobby Mega Box Green Shock")["target"]["id"],
      "select_2023_24_hobby_mega_green_shock")

# ------------------------------------------------ le filtre des ligues, appliqué AU TITRE
# Panini décline « Select Mega Box » sur presque toutes ses licences.
for t in ("Panini Select 2023/24 Premier League Mega Box",
          "Panini Select Road to FIFA World Cup 2026 Mega Box",
          "Panini Select La Liga 2025/26 Mega Box",
          "2023-24 Panini Prizm Euroleague Basketball Mega Box",
          "2023-24 Panini Prizm Draft Picks Mega Box"):
    check(f"écarté : {t[:46]}", ident(t)["confiance"], "HORS_PERIMETRE")
# ... mais PAS au texte entier d'une page : le menu d'une boutique multi-sports contient
# « football », et un Mega basket légitime s'y perdait.
_page = "Accueil Football Soccer Basketball Panier ... Blue & Pink Cracked Ice ... 8 packs 4 cards"
check("le menu d'une boutique ne disqualifie pas une Mega basket",
      ident("2023-24 Panini Select Basketball Mega Box", texte=_page)["target"]["id"],
      "select_2023_24_mega_blue_pink")

# ------------------------------------------------ la configuration, preuve secondaire
bp = next(t for t in TARGETS if t["id"] == "select_2023_24_mega_blue_pink")
check("8 packs × 4 cartes confirment Blue & Pink",
      mh.valide_config(bp, "contient 8 packs de 4 cards").startswith("config confirmée"))
check("une configuration contradictoire est SIGNALÉE, pas ignorée",
      mh.valide_config(bp, "10 packs de 4 cards").startswith("⚠️"))
check("sans configuration lisible, rien n'est affirmé",
      mh.valide_config(bp, "boîte scellée"), None)

# ------------------------------------------------ les lots et cases ne sont pas des boîtes
check("un case n'est pas une Mega Box",
      ident("2023-24 Panini Select Mega Box Green Shock CASE of 10")["confiance"], "HORS_PERIMETRE")
check("un lot non plus",
      ident("Lot 2023-24 Panini Select Mega Box Blue Pink x3")["confiance"], "HORS_PERIMETRE")

# ------------------------------------------------ OFFER : produit × boutique, avec histoire
check("les seize champs d'une offre sont définis", len(offers.CHAMPS), 16)
_d = {"generated_at": None, "offers": []}
_o = {"product_id": "p", "shop_id": "s", "url": "https://x/p?a=1", "price": 100.0,
      "currency": "USD", "stock_status": offers.OUT_OF_STOCK}
check("une offre inédite est NEW", offers.upsert(_d, dict(_o)), "NEW")
check("la revoir identique ne produit aucun événement",
      offers.upsert(_d, dict(_o)), "UNCHANGED")
check("un retour en stock est un RESTOCK",
      offers.upsert(_d, dict(_o, stock_status=offers.IN_STOCK)), "RESTOCK")
check("une rupture est un SOLD_OUT",
      offers.upsert(_d, dict(_o, stock_status=offers.OUT_OF_STOCK)), "SOLD_OUT")
check("une baisse de prix est repérée",
      offers.upsert(_d, dict(_o, price=80.0)), "PRICE_DROP")
check("une hausse aussi", offers.upsert(_d, dict(_o, price=120.0)), "PRICE_UP")
check("tout cela reste UNE seule offre", len(_d["offers"]), 1)
check("et son histoire est conservée", len(_d["offers"][0]["history"]), 6)
check("le prix précédent est gardé", _d["offers"][0]["last_price"], 80.0)
# les paramètres d'URL ne créent pas de doublon : ?_pos= et ?_psq= changent à chaque recherche
check("les paramètres d'URL ne dédoublent pas une offre",
      offers.upsert(_d, dict(_o, url="https://x/p?b=2")) and len(_d["offers"]), 1)
# une rupture reste en base : c'est elle qui portera le restock
check("une rupture n'est jamais effacée",
      _d["offers"][0]["stock_status"], offers.OUT_OF_STOCK)

# ------------------------------------------------ ne jamais confondre notre registre et le marché
_p = offers.formule_absence(58, ["eBay", "COMC"])
check("l'absence se formule sur le PÉRIMÈTRE couvert", "périmètre actuellement couvert" in _p)
check("elle nomme les canaux fermés", "eBay" in _p)
check("elle rappelle que la couverture est incomplète", "incomplète" in _p)
for mot in offers.ABSENCE_INTERDITE:
    check(f"elle ne dit jamais « {mot} »", mot in _p.lower(), False)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
