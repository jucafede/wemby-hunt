#!/usr/bin/env python3
"""Contrôle des liens produit AVANT publication.

Un lien qui ment sur sa destination est pire qu'une absence de lien : il envoie l'acheteur
sur une 404 de NOTRE site en lui laissant croire que la boutique a disparu. Ce script refuse
la publication tant qu'une URL cliquable n'est pas une URL absolue.
"""
import json
import sqlite3
import sys
from pathlib import Path

import hunt

ROOT = Path(__file__).parent
CHAMPS = ("url", "product_url", "source_url", "seller_url", "href", "url_proof")


def scanne_json(chemin: Path):
    """Toute valeur d'un champ d'URL, où qu'elle se trouve dans le document."""
    if not chemin.exists():
        return []
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception as e:
        return [{"fichier": chemin.name, "erreur": str(e)}]
    out = []

    def marche(n, ctx):
        if isinstance(n, dict):
            ctx = {**ctx,
                   "seller": n.get("seller") or n.get("shop") or ctx.get("seller"),
                   "produit": n.get("titre") or n.get("title") or n.get("name") or ctx.get("produit")}
            for k, v in n.items():
                if k in CHAMPS:
                    out.append({"fichier": chemin.name, "champ": k, "valeur": v, **ctx})
                else:
                    marche(v, ctx)
        elif isinstance(n, list):
            for x in n:
                marche(x, ctx)

    marche(d, {})
    return out


def main():
    lignes = []
    for f in ("prizm_core.json", "external_prizm.json", "manual_observations.json",
              "supercollectors_history.json", "hokejkarty_history.json",
              "candidate_domains.json", "hunt_hoops_rookie_special_3.json"):
        lignes += scanne_json(ROOT / "discovered" / f)

    # la base : c'est elle qui alimente la page publique
    try:
        c = sqlite3.connect(hunt.DB)
        for sku, shop, url, titre in c.execute(
                "SELECT sku_id, shop, url, title FROM observations "
                "WHERE seen_at=(SELECT MAX(seen_at) FROM observations)"):
            lignes.append({"fichier": "hunt.db/observations", "champ": "url", "valeur": url,
                           "seller": shop, "produit": titre})
    except Exception as e:
        print(f"⚠️  base illisible : {e}")

    total = len(lignes)
    valides = [l for l in lignes if hunt.url_valide(l.get("valeur"))]
    manquants = [l for l in lignes if l.get("valeur") in (None, "", [])]
    invalides = [l for l in lignes
                 if l not in valides and l.get("valeur") not in (None, "", [])]

    print("=== CONTRÔLE DES LIENS PRODUIT ===\n")
    print(f"TOTAL PRODUCTS      {total}")
    print(f"VALID PRODUCT URLS  {len(valides)}")
    print(f"MISSING URLS        {len(manquants)}")
    print(f"INVALID URLS        {len(invalides)}")
    if invalides:
        print("\n--- URLs invalides ---")
        for l in invalides[:40]:
            print(f"  {str(l.get('seller'))[:18]:<18} {str(l.get('produit'))[:38]:<38} "
                  f"{l['champ']}={l['valeur']!r}  ({l['fichier']})")
    if manquants:
        print("\n--- URLs absentes ---")
        for l in manquants[:20]:
            print(f"  {str(l.get('seller'))[:18]:<18} {str(l.get('produit'))[:44]:<44} ({l['fichier']})")
    print()
    if invalides:
        print("PUBLICATION REFUSÉE : au moins un lien cliquable serait mensonger.")
        return 1
    print("Aucun lien invalide. Publication autorisée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
