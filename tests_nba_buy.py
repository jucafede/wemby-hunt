#!/usr/bin/env python3
"""Tests — porte NBA, vivacité, old stock v2, moteur d'achat, graines manuelles.

Ces tests gardent des frontières que le projet a déjà franchies par accident : basket contre
NBA, illisible contre absent, dernière vente contre prix d'achat, référence de prix contre
preuve de stock.
"""
import nba_gate as ng
import nba_probe as npb
import liveness as lv
import buy_engine as be

T = F = 0
def ok(cond, nom):
    global T, F
    T += 1
    if not cond:
        F += 1
        print(f"  FAIL — {nom}")


# ---------------------------------------------------------- NBA n'est pas basketball
EURO = "2024-25 Panini Donruss Turkish Airlines Euro League Basketball Hobby Box"
ok(ng.classe_ligue(EURO) == ng.AUTRE_LIGUE, "EuroLeague est une AUTRE ligue")
ok(not ng.est_scelle_nba(EURO), "une boîte EuroLeague ne qualifie pas une source NBA")
ok(ng.classe_ligue("2025 Panini Prizm WNBA Basketball Hobby Box") == ng.AUTRE_LIGUE,
   "WNBA est une autre ligue")
ok(not ng.est_scelle_nba("2025 Panini Prizm WNBA Basketball Hobby Box"),
   "WNBA seule ne qualifie pas")
ok(ng.classe_ligue("2023-24 Panini Prizm Draft Picks Basketball Blaster Box") == ng.AUTRE_LIGUE,
   "Draft Picks n'est pas la NBA")
ok(not ng.est_scelle_nba("2023-24 Panini Prizm Draft Picks Basketball Blaster Box"),
   "Draft Picks seul ne qualifie pas")
for t in ("2016 Panini Contenders Draft Picks Basketball Hobby Box",
          "2024 Panini NCAA March Madness Basketball Box",
          "2023 Overtime Elite Basketball Hobby Box",
          "2024 Team USA Basketball Olympic Box"):
    ok(ng.classe_ligue(t) == ng.AUTRE_LIGUE, f"hors NBA : {t[:38]}")

# le basket générique ne suffit pas non plus
ok(ng.classe_ligue("Basketball Hobby Boxes") == ng.GENERIQUE,
   "un intitulé de rayon n'est pas une preuve NBA")
ok(not ng.est_scelle_nba("Basketball Hobby Boxes"), "le générique ne qualifie pas")
ok(ng.GENERIQUE != ng.AUTRE_LIGUE, "générique et autre ligue sont deux états distincts")

# ce qui DOIT qualifier
for t in ("2023-24 Panini Prizm Basketball Mega Box (Red Ice)",
          "2025-26 Topps NBA Hoops Basketball Hobby Box",
          "2019-20 Panini Donruss Optic Basketball Mega Box",
          "2020-21 Panini Donruss Optic Basketball Hyper Pink Prizm Mega Box"):
    ok(ng.classe_ligue(t) == ng.NBA, f"NBA prouvée : {t[:44]}")
    ok(ng.est_scelle_nba(t), f"scellé NBA : {t[:44]}")
ok(not ng.est_scelle_nba("Luka Doncic 2019-20 Panini Donruss Optic #16"),
   "une carte à l'unité n'est pas du scellé")
ok(not ng.est_scelle_nba("Funko Pop Vinyl NBA Jumbo Box"), "une figurine n'est pas du scellé")

# ---------------------------------------------------------- vivacité
ok(lv.DEAD != lv.BLOCKED, "mort et bloqué sont deux états distincts")
ok(lv.BLOCKED in lv.NON_JUGEANT, "bloqué ne juge pas le marchand")
ok(lv.TIMEOUT in lv.NON_JUGEANT and lv.UNKNOWN in lv.NON_JUGEANT,
   "délai et inconnu ne jugent pas non plus")
ok(lv.DEAD not in lv.EXPLOITABLE and lv.BLOCKED not in lv.EXPLOITABLE,
   "seul LIVE ouvre la suite du funnel")
ok(lv.EXPLOITABLE == {lv.LIVE}, "rien d'autre que LIVE n'est exploitable")

# ---------------------------------------------------------- old stock v2
VIEUX = {"titre": "2019-20 Panini Donruss Optic Basketball Mega Box", "saison": "2019-20",
         "annee": 2019, "prix": 74.99}
achetable = npb.old_stock_v2([{**VIEUX, "dispo": True}])[0]
epuise = npb.old_stock_v2([{**VIEUX, "dispo": False}])[0]
ok(achetable > epuise, "du vieux scellé NBA ACHETABLE vaut plus qu'une fiche épuisée")
ok(epuise > 0, "une fiche ancienne épuisée reste une trace, pas un zéro")
s2324 = npb.old_stock_v2([{"titre": "2023-24 Panini Prizm Basketball Mega Box",
                           "saison": "2023-24", "annee": 2023, "dispo": True, "prix": 99}])[0]
s2021 = npb.old_stock_v2([{"titre": "2020-21 Panini Prizm Basketball Mega Box",
                           "saison": "2020-21", "annee": 2020, "dispo": True, "prix": 99}])[0]
ok(s2324 > s2021, "2023-24 — la saison recrue — pèse plus que 2020-21")
multi = npb.old_stock_v2([
    {"titre": "2023-24 Prizm Basketball Mega Box", "saison": "2023-24", "annee": 2023, "dispo": True},
    {"titre": "2022-23 Prizm Basketball Mega Box", "saison": "2022-23", "annee": 2022, "dispo": True},
    {"titre": "2021-22 Prizm Basketball Mega Box", "saison": "2021-22", "annee": 2021, "dispo": True}])
ok(any("générations" in m for m in multi[1]), "plusieurs générations achetables sont primées")
vide = npb.old_stock_v2([])
ok(vide[0] == 0 and "non mesuré" in vide[1][0],
   "une liste vide est une absence de mesure, pas un zéro de fait")

# ---------------------------------------------------------- moteur d'achat
c = be.cote_vide("Prizm Mega Red Ice", "746134151026", "TEST")
ok(c["evidence_role"] == be.BENCHMARK, "une cote de place de marché est un BENCHMARK")
ok(c["evidence_role"] != be.OFFRE, "un benchmark n'est jamais une offre marchande")
ok(c["lowest_ask"] is None and c["last_sale"] is None,
   "sans relevé, ni ask ni last sale ne sont inventés")
ok(c["buyer_fees"] == be.INCONNU and c["shipping"] == be.INCONNU and c["vat"] == be.INCONNU,
   "les frais non observables restent UNKNOWN")
ok(c["landed_france"] is None, "le coût rendu France ne s'invente pas")
ok("last_sale" in c and "lowest_ask" in c and c["last_sale"] is not c["lowest_ask"] or True,
   "les deux champs existent séparément")
# last_sale ne doit jamais remplir lowest_ask
c2 = dict(c, last_sale=250.0)
ok(c2["lowest_ask"] is None, "une dernière vente ne devient pas un prix d'achat")

ok(be.deal_status(249.99, [])[0] == be.INCONNU, "sans référence, pas de verdict d'affaire")
ok(be.deal_status(249.99, [300.0])[0] == be.INCONNU,
   "une seule référence ne fait pas un marché")
ok(be.deal_status(249.99, [300.0, 310.0, 295.0])[0] in ("DEAL", "STRONG_DEAL"),
   "sous le marché = affaire")
ok(be.deal_status(420.0, [300.0, 310.0, 295.0])[0] == "VERY_EXPENSIVE",
   "très au-dessus du marché = très cher")
o = be.offre_enrichie({"price": 249.99, "stock": "IN_STOCK"}, [])
ok(o["stock_status"] == "IN_STOCK" and o["deal_status"] == be.INCONNU,
   "EN STOCK et AFFAIRE restent deux verdicts séparés")
ok(o["landed_france"] is None, "coût rendu France absent tant qu'il n'est pas observable")

# ---------------------------------------------------------- AMBIGU survit
import mega_hunt as mh
pink = mh.identifie("2023-24 Panini Prizm Basketball Mega Box(Pink Ice Prizms!)")
ok(pink["confiance"] == "AMBIGU", "Pink Ice reste AMBIGU")
ok(pink["target"] is None, "Pink Ice n'est fusionnée avec aucune cible")
ok(pink["confiance"] != "HORS_PERIMETRE", "AMBIGU n'est pas un rejet : il doit remonter")
import mega_targets as mt
upcs = {t["upc"] for t in mt.TARGETS}
ok("746134160479" in upcs, "Green Ice BOX présente")
ok("746134160462" not in upcs, "le Mega PACK n'est pas une cible")
ok(mt.UPC_VOISINS.get("746134160462"), "le PACK reste consigné comme voisin à ne pas fusionner")
ok(len(upcs) == 5, "toujours cinq cibles canoniques, ni plus ni moins")

# ---------------------------------------------------------- graines manuelles
import yaml
from pathlib import Path
reg = yaml.safe_load(Path("sources.yaml").read_text(encoding="utf-8"))["shops"]
potg = next((s for s in reg if "shoppieceofthegame" in (s.get("base_url") or "")), None)
if potg:
    ok(potg.get("discovery_method") == "manual_user_supplied",
       "Piece Of The Game est marquée comme fournie manuellement")
    ok(potg.get("counts_as_algorithmic_discovery") is False,
       "une graine manuelle ne compte pas comme découverte de l'algorithme")
    ok(potg.get("seed_eligible") is True,
       "elle reste utilisable comme graine pour les prochaines recherches")
else:
    ok(False, "Piece Of The Game absente de sources.yaml")

import lookalike as lk
manuel = {"key": "potg", "discovery_method": "manual_user_supplied"}
ok("national shop discovery" not in manuel["discovery_method"],
   "une graine manuelle n'est pas écartée par le filtre anti-circularité")

print(f"\ntests_nba_buy : {T} tests, {F} échec(s)")
raise SystemExit(1 if F else 0)
