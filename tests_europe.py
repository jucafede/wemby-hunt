#!/usr/bin/env python3
"""Observations manuelles, comparaison inter-boutiques, historique de stock.

Les trois règles nées du 15/09 : une observation humaine vaut une lecture automatique ; aucun
prix ne se juge seul ; une quantité qui ne bouge pas est une information.
"""
import sys
import europe_intel as ei

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

# ------------------------------------------------ la provenance se déclare, elle ne déclasse pas
check("les deux provenances existent", {ei.CRAWLER_VERIFIED, ei.MANUAL_VERIFIED},
      {"CRAWLER_VERIFIED", "MANUAL_VERIFIED"})

# ------------------------------------------------ transitions de quantité
check("une quantité qui baisse dit que ça se vend", "STOCK_MOVING" in ei.etat_quantite(11, 8, 3))
check("une unité restante se signale", "LAST_UNIT" in ei.etat_quantite(3, 1, 1))
check("deux unités ou moins = stock faible", "LOW_STOCK" in ei.etat_quantite(5, 2, 1))
check("une unité n'est pas rangée en LOW_STOCK mais en LAST_UNIT",
      "LOW_STOCK" not in ei.etat_quantite(3, 1, 1))
check("zéro vers positif = restock", "RESTOCK" in ei.etat_quantite(0, 4, 1))
check("positif vers zéro = rupture", "SOLD_OUT" in ei.etat_quantite(4, 0, 1))
check("une rupture ne se double pas d'un LAST_UNIT", ei.etat_quantite(4, 0, 1), ["SOLD_OUT"])
# du stock que personne ne touche : souvent le plus intéressant à négocier
check("une quantité figée trois semaines = stock dormant",
      "DORMANT_STOCK" in ei.etat_quantite(3, 3, 25))
check("figée depuis deux jours, ce n'est pas encore dormant",
      "DORMANT_STOCK" not in ei.etat_quantite(3, 3, 2))
check("sans quantité connue, aucune transition inventée", ei.etat_quantite(5, None, 30), [])

# ------------------------------------------------ conversion monétaire
check("les couronnes tchèques se convertissent", ei.en_eur(1190, "CZK", 0.862), 48.2)
check("les couronnes suédoises aussi", ei.en_eur(3995, "SEK", 0.862), 347.57 - 0.01)
check("l'euro reste l'euro", ei.en_eur(25, "EUR", 0.862), 25.0)
check("une devise inconnue ne produit pas de chiffre", ei.en_eur(10, "XYZ", 0.862), None)

# ------------------------------------------------ aucun prix ne se juge seul
LIVE = [
 {"exact_comp_key": "K1", "prix": 36.05, "devise": "EUR", "seller": "bandurka", "pays": "CZ"},
 {"exact_comp_key": "K1", "prix": 25.00, "devise": "EUR", "seller": "supercollectors", "pays": "ES"},
 {"exact_comp_key": "K2", "prix": 99.00, "devise": "EUR", "seller": "autre", "pays": "DE"},
]
c = ei.compare({"exact_comp_key": "K1", "prix": 36.05, "devise": "EUR", "seller": "bandurka"}, LIVE, 0.862)
check("une offre est située parmi TOUTES celles du même produit", c["n_offres"], 2)
check("et n'est pas déclarée plus basse quand une autre est moins chère", c["is_world_low"], False)
check("l'écart au meilleur prix est chiffré", c["ecart_vs_world_low_pct"], 44.2)
c2 = ei.compare({"exact_comp_key": "K1", "prix": 25.0, "devise": "EUR", "seller": "supercollectors"}, LIVE, 0.862)
check("la moins chère, elle, porte le plus-bas", c2["is_world_low"])
# deux produits différents ne se comparent jamais, même aux noms voisins
check("une cloison sans concurrent ne produit aucune comparaison",
      ei.compare({"exact_comp_key": "K9", "prix": 10, "devise": "EUR"}, LIVE, 0.862)["comparable"], False)
check("un produit non identifié ne se compare pas",
      ei.compare({"exact_comp_key": None, "prix": 10, "devise": "EUR"}, LIVE, 0.862)["comparable"], False)

# ------------------------------------------------ un prix HT non confirmé ne fixe aucun plancher
LIVE_HT = LIVE + [{"exact_comp_key": "K1", "prix": 20.0, "devise": "EUR",
                   "seller": "shopuscards", "pays": "FR", "prix_ht_non_confirme": True}]
c3 = ei.compare({"exact_comp_key": "K1", "prix": 25.0, "devise": "EUR", "seller": "supercollectors"},
                LIVE_HT, 0.862)
check("un prix HT non confirmé ne vole pas le plus-bas", c3["is_world_low"])
check("et il est nommé parmi les exclus", "shopuscards" in c3["exclus_ht"])
c4 = ei.compare({"exact_comp_key": "K1", "prix": 20.0, "devise": "EUR",
                 "seller": "shopuscards", "prix_ht_non_confirme": True}, LIVE_HT, 0.862)
check("et lui-même ne revendique rien", c4["comparable"], False)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
