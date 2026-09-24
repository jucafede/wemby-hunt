#!/usr/bin/env python3
"""Les 5 Mega Box 2023-24 de la chasse Wemby — identifiées par UPC AVANT le nom commercial.

POURQUOI L'UPC PASSE EN PREMIER
-------------------------------
Les boutiques nomment très mal ces produits. La Select Green Shock s'appelle tantôt « Mega
Green Shock », tantôt « Hobby Mega » ; la Blue/Pink devient « Select Mega Box » tout court.
Un titre ne suffit donc jamais à trancher — et se tromper ici, ce n'est pas se tromper d'un
peu : Blue/Pink contient 32 cartes, Red/Purple et Green Shock en contiennent 40.

LE PIÈGE DES UPC VOISINS
------------------------
Un UPC de case ou de sachet n'est pas celui de la boîte. Pour la Prizm Green Ice, la Mega Box
est 746134160479 quand le Mega Pack isolé est 746134160462 : deux chiffres d'écart, deux
produits, deux marchés.

LA RÈGLE
--------
UPC exact → SKU fabricant exact → année+set+format+variante → alias textuel. Et JAMAIS de
rattachement sur « 2023-24 Prizm Mega » seul : cela mélangerait les trois Select d'un coup.
"""
TARGETS = [
    {"id": "prizm_2023_24_mega_red_ice",
     "libelle": "Prizm 2023-24 Mega Box — Red Ice Prizms",
     "set": "Prizm Basketball", "format": "Mega Box", "variant": "Red Ice Prizms",
     "cards_per_pack": 10, "packs_per_box": 6, "cards_per_box": 60,
     "upc": "746134151026", "manufacturer_sku": None,
     "variant_rx": r"red\s*ice",
     "aliases": ["2023-24 Panini Prizm Basketball Mega Box", "Prizm Mega Red Ice",
                 "Prizm Red Ice Mega", "Mega Box Red Ice Prizms"]},
    {"id": "prizm_2023_24_mega_green_ice",
     "libelle": "Prizm 2023-24 Mega Box — Green Ice Prizms",
     "set": "Prizm Basketball", "format": "Mega Box", "variant": "Green Ice Prizms",
     "cards_per_pack": 10, "packs_per_box": 6, "cards_per_box": 60,
     "upc": "746134160479", "manufacturer_sku": "23PAKPRZ-MBGRN(B)",
     "variant_rx": r"green\s*ice",
     "aliases": ["2023-24 Panini Prizm Basketball Mega Box Green Ice", "Prizm Mega Green Ice",
                 "Prizm Green Ice Mega"]},
    {"id": "select_2023_24_mega_blue_pink",
     "libelle": "Select 2023-24 Mega Box — Blue & Pink Cracked Ice",
     "set": "Select Basketball", "format": "Mega Box", "variant": "Blue & Pink Cracked Ice Prizms",
     "cards_per_pack": 4, "packs_per_box": 8, "cards_per_box": 32,
     "upc": "746134158100", "manufacturer_sku": None,
     "variant_rx": r"blue\s*(?:&|and|/|\+)?\s*pink|pink\s*(?:&|and|/|\+)?\s*blue|blue\s*cracked",
     "aliases": ["Select Mega Blue Pink", "Select Mega Blue/Pink", "Blue and Pink Cracked Ice",
                 "Blue & Pink Cracked Ice", "Blue Cracked Ice Mega"]},
    {"id": "select_2023_24_mega_red_purple",
     "libelle": "Select 2023-24 Mega Box — Red & Purple Cracked Ice",
     "set": "Select Basketball", "format": "Mega Box", "variant": "Red & Purple Cracked Ice Prizms",
     "cards_per_pack": 4, "packs_per_box": 10, "cards_per_box": 40,
     "upc": "746134158162", "manufacturer_sku": None,
     "variant_rx": r"red\s*(?:&|and|/|\+)?\s*purple|purple\s*(?:&|and|/|\+)?\s*red",
     "aliases": ["Select Mega Red Purple", "Select Mega Red/Purple",
                 "Red and Purple Cracked Ice", "Red & Purple Cracked Ice"]},
    {"id": "select_2023_24_hobby_mega_green_shock",
     "libelle": "Select 2023-24 Hobby Mega Box — Green Shock Prizms",
     "set": "Select Basketball", "format": "Hobby Mega Box", "variant": "Green Shock Prizms",
     "cards_per_pack": 4, "packs_per_box": 10, "cards_per_box": 40,
     "upc": "746134158223", "manufacturer_sku": "23PAKSEL-MBGRN(B)",
     "variant_rx": r"green\s*shock",
     "aliases": ["Select Hobby Mega", "Select Mega Green Shock", "Select Green Shock Mega",
                 "Hobby Mega Green Shock"]},
]

# UPC à NE PAS confondre : ce sont d'autres conditionnements du même produit.
UPC_VOISINS = {
    "746134160462": "Prizm Green Ice — MEGA PACK isolé, pas la boîte (boîte = 746134160479)",
}

PAR_UPC = {t["upc"]: t for t in TARGETS}
PAR_SKU = {t["manufacturer_sku"]: t for t in TARGETS if t.get("manufacturer_sku")}
