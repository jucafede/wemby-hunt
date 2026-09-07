#!/usr/bin/env python3
"""Le compte rendu d'un passage autonome, en une page.

Il ne collecte rien : il relit ce que le passage a produit. Sa seule raison d'être est qu'un
run doit pouvoir être JUGÉ sans ouvrir cinq fichiers JSON — combien de sources crawlées,
combien d'URL revérifiées, combien de recherches réellement exécutées, ce qui est passé de
disponible à rupture, et ce qui a vieilli.

La ligne la plus importante est « recherches exécutées » avec le sort de chaque moteur. Un
zéro de découverte peut vouloir dire « nous avons cherché partout et le marché est vide » ou
« tous les moteurs nous ont fermé la porte ». Ce sont deux situations opposées et elles ne
doivent jamais s'afficher pareil.
"""
from __future__ import annotations
import collections
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
D = ROOT / "discovered"


def _j(name):
    p = D / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    ext, sold, core = _j("external_prizm.json"), _j("sold_prizm.json"), _j("prizm_core.json")
    ledger, reg = _j("sold_ledger.json"), _j("candidate_domains.json")
    run = ext.get("run", {})

    print("=" * 74)
    print("PASSAGE AUTONOME — PRIZM_WEMBY_CORE")
    print("=" * 74)

    # ---- une seule collecte, et la preuve
    import hunt
    conn = sqlite3.connect(hunt.DB)
    dernier = conn.execute("SELECT MAX(seen_at) FROM crawl_runs").fetchone()[0]
    shops = conn.execute("SELECT shop, COUNT(*) FROM crawl_runs WHERE seen_at=? GROUP BY shop",
                         (dernier,)).fetchall()
    print(f"\nCOLLECTE RETAILER (passage {str(dernier)[:16].replace('T', ' ')})")
    print(f"  sources crawlées par hunt.py        {len(shops)}")
    print(f"  requêtes de prizm_core aux boutiques  0   (lecture de products_raw — "
          f"tests_autonomy l'appelle sockets coupées)")
    ecartes = (ext.get("run", {}) or {}).get("ecartes_deja_crawles") or []
    print(f"  domaines écartés du balayage        {len(ecartes)}"
          f"   (déjà crawlés par hunt.py)" + (f" {ecartes}" if ecartes else ""))
    print(f"  lecture du noyau Prizm              {core.get('collection', '?')}")
    print(f"  listings Prizm core                 {len(core.get('listings', []))}"
          f" · {len(core.get('sources_read', []))} source(s) lue(s)")

    # ---- couches externes
    print("\nEXTERNAL WEB + MARKETPLACE")
    print(f"  URL connues revérifiées             {run.get('known_urls_checked', 0)}"
          f"  (dont {run.get('unreadable', 0)} illisibles : lecture refusée par le site)")
    print(f"  recherches web exécutées            {run.get('web_searches', 0)}")
    print(f"  recherches marketplace              {run.get('marketplace_searches', 0)}")
    print(f"  domaines candidats balayés          {run.get('domains_swept', 0)}"
          f"  ({run.get('domains_reachable', 0)} joignables, "
          f"{run.get('catalog_items_read', 0)} fiches lues)")
    moteurs = collections.Counter()
    for a in run.get("engine_attempts", []):
        for x in a.get("attempts", []):
            moteurs[(x["engine"], x["outcome"])] += 1
    if moteurs:
        print("  sort des moteurs                    "
              + " · ".join(f"{e}:{o}×{n}" for (e, o), n in sorted(moteurs.items())))
    print(f"  nouveaux domaines découverts        {len(run.get('new_domains', []))}"
          + (f"  {run['new_domains']}" if run.get("new_domains") else ""))
    print(f"  nouvelles annonces découvertes      {run.get('new_listings', 0)}"
          f"  ({run.get('new_by_search', 0)} par recherche, {run.get('new_by_sweep', 0)} par balayage)")
    print(f"  registre de domaines candidats      {len(reg.get('domains', []))}")

    # ---- mouvements
    def bloc(titre, cle):
        v = run.get(cle) or []
        print(f"  {titre:<34}{len(v)}")
        for x in v[:6]:
            if cle == "price_changes":
                print(f"      {x.get('format', '?'):<14} {x['de']} → {x['à']}   {x['url'][:52]}")
            else:
                print(f"      {x.get('format', '?'):<14} {x['url'][:64]}")
    print("\nMOUVEMENTS")
    bloc("changements de prix", "price_changes")
    bloc("passées LIVE → OOS", "live_to_oos")
    bloc("passées OOS → LIVE", "oos_to_live")
    bloc("devenues STALE (> 24 h)", "became_stale")
    bloc("disparues (LOST)", "lost")

    etats = ext.get("states", {})
    if etats:
        print("\n  états des annonces externes         "
              + " · ".join(f"{k} {v}" for k, v in etats.items() if v))

    # ---- ventes
    print("\nSOLD")
    for p in sold.get("providers", []):
        print(f"  {p['provider']:<34}{p['outcome']}"
              f"  {p.get('ingérées', 0)} ajoutée(s)   {p.get('why', '')}")
    print(f"  transactions au registre            {len(ledger.get('transactions', []))}")
    calc = sum(1 for r in sold.get("records", {}).values()
               if r.get("COMPUTED_FROM") == "transactions")
    print(f"  statistiques recalculées            {len(sold.get('records', {}))} format(s)"
          f"  ({calc} depuis des transactions, "
          f"{len(sold.get('records', {})) - calc} depuis un relevé agrégé)")
    for f, r in sold.get("records", {}).items():
        med = r.get("MEDIAN_90D") or r.get("AVG_90D")
        print(f"      {f:<16} last={r.get('LAST_SALE')} med90={r.get('MEDIAN_90D')} "
              f"avg90={r.get('AVG_90D')} n90={r.get('N_90D')} {r.get('SOLD_CONFIDENCE')}"
              f"  [{r.get('COMPUTED_FROM')}]")
    print("=" * 74)


if __name__ == "__main__":
    main()
