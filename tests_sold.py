#!/usr/bin/env python3
"""Moteur de ventes réalisées : ingestion, filtres, fenêtres.

Le bloc qui compte est celui des filtres. Un tableau de cotation mélange la boîte, le case, le
lot et l'exemplaire abîmé ; les inclure ne rend pas la médiane plus robuste, elle la rend fausse.
"""
import sys
from datetime import date
import sold_engine as se

total, fails = [], []
def check(name, got, exp=True):
    total.append(name); ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

T = date(2026, 9, 6)

check("date en clair", se.parse_date("Aug 19, 2026"), date(2026, 8, 19))
check("date ISO", se.parse_date("2026-08-19"), date(2026, 8, 19))
check("date ambiguë refusée plutôt que devinée", se.parse_date("19/08/26"), None)

# ---- filtres : chaque motif écarte ce qu'il doit, et rien d'autre
for t, why in [("Panini Origins Hobby Box 3-Box Lot", "lot"),
               ("Origins Basketball Hobby 12-Box Case", "case"),
               ("Origins Basketball Hobby Pack", "pack"),
               ("Origins Basketball FOTL Hobby Box", "fotl"),
               ("Origins Hobby Box damaged corner", "imparfait"),
               ("Origins Hobby Box resealed", "imparfait")]:
    check(f"écarté : {why} — {t[:36]}", se.excluded(t), why)
check("une boîte normale passe", se.excluded("2023-24 Panini Origins Basketball Hobby Box"), None)
check("la mauvaise saison est écartée",
      se.excluded("2022-23 Panini Origins Basketball Hobby Box", season="2023-24"), "autre saison")
check("la bonne saison passe",
      se.excluded("2023-24 Panini Origins Basketball Hobby Box", season="2023-24"), None)
check("« 2023/24 » est la même saison que « 2023-24 »",
      se.excluded("2023/24 Panini Origins Hobby Box", season="2023-24"), None)

# ---- ingestion : les rejets sont conservés avec leur motif, pas jetés en silence
txt = """Aug 19, 2026  Origins Hobby Box  $400.00
Jun 01, 2026  Origins Hobby Box  $390.00
May 30, 2026  Origins Hobby 3-Box Lot  $1100.00
Jan 08, 2026  Origins Hobby Box  $410.00
ligne sans prix ni date"""
kept, drop = se.parse_pasted(txt, season="2023-24", today=T)
check("trois ventes retenues", len(kept), 3)
check("le lot est rejeté", len(drop), 1)
check("et son motif est conservé", drop[0]["excluded"], "lot")
check("une ligne sans date ni prix est ignorée", len(kept) + len(drop), 4)

# ---- fenêtres et confiance
w = se.windows(kept, today=T)
check("30 jours : une seule vente", w["d30"]["n"], 1)
check("et la confiance est LOW", w["d30"]["confidence"], "LOW")
check("365 jours : les trois", w["d365"]["n"], 3)
check("et la confiance passe MEDIUM", w["d365"]["confidence"], "MEDIUM")
check("la médiane est bien la médiane", w["d365"]["median"], 400.0)
check("la fourchette est rendue", (w["d365"]["low"], w["d365"]["high"]), (390.0, 410.0))
b = se.best_window(w)
check("la meilleure fenêtre est la plus COURTE qui reste crédible", b["window"], "d365")
check("aucune vente -> NONE", se.windows([], today=T)["d30"]["confidence"], "NONE")
check("et aucune médiane inventée", se.windows([], today=T)["d90"]["median"], None)

# ---- le cas réel qui a renversé la recommandation du 06/09
ORIG = """Aug 19, 2026 Origins Hobby Box $400.00
Jun 01, 2026 Origins Hobby Box $390.00
May 30, 2026 Origins Hobby Box $450.00
Jan 17, 2026 Origins Hobby Box $421.59
Jan 12, 2026 Origins Hobby Box $330.00
Jan 08, 2026 Origins Hobby Box $410.00"""
k, _ = se.parse_pasted(ORIG, season="2023-24", today=T)
bw = se.best_window(se.windows(k, today=T))
check("Origins : six ventes réelles", bw["n"], 6)
check("médiane 405 $, pas les 549,95 $ de Waxstat", bw["median"], 405.0)
check("l'ASK surestimait de plus de 30 %", round((549.95 / bw["median"] - 1) * 100) >= 30)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
