#!/usr/bin/env python3
"""Rapport Europe — couverture d'abord, conclusions ensuite.

« EUROPEAN GEMS : aucune » et « nous n'avons pas pu chercher » sont deux phrases opposées, et
le 15/09 la seconde a été publiée sous la forme de la première. Ce rapport commence donc par
dire ce qu'il a RÉELLEMENT pu couvrir — automatiquement, manuellement, et ce que la découverte
a pu faire — avant d'énoncer le moindre résultat.
"""
import json
import os
from collections import defaultdict
from pathlib import Path

import yaml

import europe_intel as ei

ROOT = Path(__file__).parent
EU = {"ES","PL","RS","CZ","SE","DE","IT","NL","GR","BE","AT","PT","FR","CH","SK"}
TIER_A = ["CZ", "ES", "DE", "IT", "GR", "PL"]
TIER_B = ["NL", "SE"]
EXPLO = ["RS"]


def statut_decouverte() -> tuple:
    """L'état réel du canal de découverte. Jamais déduit d'un résultat vide."""
    if os.environ.get("BRAVE_API_KEY"):
        return "working", "Brave Search API active"
    return ("unavailable",
            "DISCOVERY_DISABLED_MISSING_API_KEY — aucune clé Brave. Les interfaces HTML "
            "gratuites sont bloquées (brave 429, mojeek, duckduckgo) ou dégradées (bing rend "
            "des résultats sans rapport avec la requête). Aucune conclusion de marché ne peut "
            "être tirée de ce canal.")


def main():
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]
    cat = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))
    skus, fx = cat["skus"], float(cat["fx_usd_eur"])
    obs = ei.charge().get("observations", [])

    eu_src = [s for s in src if (s.get("country") or "") in EU]
    auto = [s for s in eu_src if s.get("type") in ("shopify_json", "html")
            and not s.get("robots_disallow") and not s.get("crawl_blocked")]
    bloques = [s for s in eu_src if s.get("robots_disallow") or s.get("crawl_blocked")
               or s.get("robots_ambiguous")]
    manuels = sorted({o["seller"] for o in obs})

    st, why = statut_decouverte()
    print("=== EUROPE COVERAGE ===\n")
    print(f"AUTOMATED COVERAGE   : {len(auto)} boutiques")
    print(f"                       {', '.join(s['key'] for s in auto)}")
    print(f"MANUAL VERIFIED      : {len(manuels)} boutiques")
    print(f"                       {', '.join(manuels)}")
    print(f"NON CRAWLABLES       : {len(bloques)}")
    for s in bloques:
        motif = ("robots.txt nous interdit nommément" if s.get("robots_disallow")
                 else "403 permanent (pare-feu)" if s.get("crawl_blocked")
                 else "robots.txt ambigu — abstention")
        print(f"                       {s['key']:<16} {motif}")
    print(f"DISCOVERY STATUS     : {st}")
    print(f"                       {why}")
    n_tot = len(auto) + len(manuels)
    conf = ("HIGH" if st == "working" and n_tot >= 12 else
            "MEDIUM" if n_tot >= 6 else "LOW")
    print(f"CONFIDENCE           : {conf}")
    print("                       la découverte étant à l'arrêt, aucune absence de résultat")
    print("                       ne doit se lire comme une absence de marché.\n")

    live = ei.toutes_les_offres_live(skus, src)
    eur = [r for r in live if (r.get("pays") or "") in EU and r.get("prix")]
    print(f"=== OFFRES EUROPÉENNES VIVANTES : {len(eur)} ===\n")
    lignes = []
    for r in eur:
        px = ei.en_eur(r["prix"], r["devise"], fx)
        if px is None:
            continue
        c = ei.compare(r, live, fx)
        s = next((x for x in skus if x["id"] == r.get("sku_id")), {})
        lignes.append({**r, "eur": px, "cmp": c, "league": s.get("league"),
                       "rc": s.get("wemby_rc"), "fmt": s.get("format"),
                       "saison": s.get("season")})
    for l in sorted(lignes, key=lambda x: x["eur"]):
        tag = "🎯 RC" if l["rc"] else (f"⚠️ {l['league']}" if l["league"] else "  ")
        bas = ""
        if l["cmp"].get("comparable"):
            if l["cmp"]["is_lowest_known"]: bas = "  ← PLUS BASSE OFFRE CONNUE"
            elif l["cmp"]["is_lowest_known_europe"]: bas = "  ← plus basse offre connue en Europe"
        ev = "M" if l["evidence_type"] == ei.MANUAL_VERIFIED else "C"
        q = f"×{l['quantite']}" if l.get("quantite") else ""
        print(f"  [{ev}] {l['eur']:>8.2f} € {str(l['pays']):<3} {l['seller']:<17} {q:<4} "
              f"{tag:<14} {(l['titre'] or '')[:42]}{bas}")
    print("\n  [C] lu par le crawler   [M] vérifié à la main — même rang, provenance différente")
    return lignes


if __name__ == "__main__":
    main()
