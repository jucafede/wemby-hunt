#!/usr/bin/env python3
"""manual-add — ingérer une observation vue dans un navigateur, et recevoir un verdict.

    ./.venv/bin/python manual_add.py "https://boutique/produit" --price 25 --currency EUR \
        --stock in_stock [--qty 3] [--title "..."] [--note "..."]

Une observation humaine vaut une lecture automatique. Elle porte MANUAL_VERIFIED, elle entre
dans l'inventaire vivant, dans la comparaison inter-boutiques, dans les plus-bas européens et
dans l'historique de stock. Elle n'est pas un pis-aller : sur les sites qui nous refusent
l'accès, c'est la seule donnée qui existe — et elle est vraie.
"""
import argparse
import sys

import europe_intel as ei


def main():
    ap = argparse.ArgumentParser(description="Ajouter une observation vérifiée à la main")
    ap.add_argument("url")
    ap.add_argument("--price", type=float, default=None)
    ap.add_argument("--currency", default=None)
    ap.add_argument("--stock", default=None,
                    choices=["in_stock", "low_stock", "last_unit", "oos", "sold_out", "preorder"])
    ap.add_argument("--qty", type=int, default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--note", default=None)
    a = ap.parse_args()

    r = ei.ajoute(a.url, prix=a.price, devise=a.currency, stock=a.stock,
                  quantite=a.qty, titre=a.title, note=a.note)
    o, c, s = r["observation"], r["comparaison"], r["sold"]

    print("AJOUTÉ")
    print(f"  {o['titre'][:76]}")
    eur = (f" ({o['prix_eur']} €)"
           if o["prix_eur"] and (o["devise"] or "").upper() != "EUR" else "")
    print(f"  {o['seller']} {o['pays'] or ''} · {o['prix']} {o['devise']}{eur}")
    print(f"  stock : {o['stock'] or '?'}" + (f" ×{o['quantite']}" if o["quantite"] is not None else ""))
    print(f"  preuve : {o['evidence_type']}"
          f"{' · page relue' if o['page_lue'] else ' · page non relue'}"
          f"{'' if o['robots_autorise'] else ' (robots.txt nous refuse ce site)'}")
    print(f"  identité : {o['sku_id'] or 'NON IDENTIFIÉ'}"
          + (f"  [{o['league']}]" if o.get("league") else "")
          + ("  🎯 année rookie Wemby" if o.get("wemby_rc") else ""))
    if o["transitions"]:
        print(f"  transitions : {', '.join(o['transitions'])}")

    if c.get("comparable"):
        print(f"\n  comparé à {c['n_offres']} offre(s) vivante(s) du MÊME produit")
        print(f"  EUROPE LOW : {'OUI' if c['is_europe_low'] else 'non'}"
              + (f" (plus bas européen {c['europe_low_eur']} €)" if c.get("europe_low_eur") else ""))
        print(f"  WORLD LOW  : {'OUI' if c['is_world_low'] else 'non'}"
              f" (plus bas {c['world_low_eur']} € chez {c['world_low_seller']})")
        if not c["is_world_low"]:
            print(f"  écart      : {c['ecart_vs_world_low_pct']:+.0f} % vs le meilleur prix connu")
    else:
        print(f"\n  comparaison impossible : {c.get('raison')}")

    v = s.get("verdict")
    print(f"\n  vs VENTES RÉALISÉES : {v}")
    if s.get("base"):
        print(f"     référence {s['base']} € ({s.get('source')}, {s.get('checked_at')})"
              f" · écart {s['ecart_pct']:+.0f} %")
    elif v:
        print(f"     {s.get('why', 'aucune vente réalisée exploitable')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
