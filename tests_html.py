#!/usr/bin/env python3
"""Collecteur HTML — parsing des adaptateurs sur des fiches réelles archivées.

Les fixtures sont des pages téléchargées le 30/08, conservées telles quelles. Un test de
parsing contre le site vivant ne teste rien de reproductible : il échoue le jour où le site
est lent, et il passe le jour où il ne devrait pas.
"""
import sys, pathlib, yaml
import hunt, html_adapters as ha

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

FIX = pathlib.Path(__file__).parent / "fixtures" / "shopuscards"
SKUS = yaml.safe_load((hunt.ROOT / "catalog.yaml").read_text(encoding="utf-8"))["skus"]

# ---------------------------------------------------------------- filtre de slug
# Il économise des requêtes, il ne décide rien : large sur le basket, ferme sur le reste.
for u in ("https://x/products/2025-26-panini-prizm-basketball-blaster-20-box-case",
          "https://x/products/2023-24-panini-mosaic-basketball-mega-box",
          "https://x/products/2025-26-topps-chrome-update-value-box"):
    check(f"slug retenu : {u.split('/')[-1][:44]}", ha.basket_slug(u))
for u in ("https://x/products/2025-26-panini-select-road-to-fifa-world-cup-soccer-mega-box",
          "https://x/products/2026-panini-luminance-england-soccer-hobby",
          "https://x/products/2026-kakawow-gem-harry-potter-25th-anniversary-hobby-4-box-case",
          "https://x/products/ultra-pro-premium-card-sleeves-x100",
          "https://x/products/2025-panini-select-wnba-basketball-hobby-blaster-box"):
    check(f"slug écarté : {u.split('/')[-1][:44]}", ha.basket_slug(u), False)

# ---------------------------------------------------------------- parsing de 3 fiches réelles
ATTENDU = {
    "2025-26-panini-prizm-basketball-blaster-20-box-case": {
        "title": "2025/26 Panini Prizm Basketball Blaster 20-Box Case",
        "price": 699.99, "currency": "EUR", "available": True},
    "2025-26-panini-origins-basketball-hobby-12-box-case-preorder": {
        "title": "2025/26 Panini Origins Basketball Hobby 12-Box Case (Preorder)",
        "price": 2299.99, "currency": "EUR", "available": True},
    "2025-26-panini-origins-basketball-hobby-box-preorder-859857763": {
        "title": "2025/26 Panini Origins Basketball Hobby Box (Preorder)",
        "price": 189.99, "currency": "EUR", "available": True},
}
for slug, exp in ATTENDU.items():
    f = FIX / f"{slug}.html"
    check(f"fixture présente : {slug[:46]}", f.exists())
    if not f.exists(): continue
    got = ha.SHOPUSCARDS.parse(f.read_text(encoding="utf-8"), slug)
    check(f"titre lu : {slug[:46]}", got["title"], exp["title"])
    check(f"prix lu : {slug[:46]}", got["price"], exp["price"])
    check(f"devise lue : {slug[:46]}", got["currency"], exp["currency"])
    check(f"stock lu : {slug[:46]}", got["available"], exp["available"])

# ---------------------------------------------------------------- le moteur reste le moteur
# Un adaptateur rend un titre ; c'est le matcher, inchangé, qui décide de l'identité. On le
# vérifie sur les titres RÉELLEMENT lus, pas sur des titres réécrits pour l'occasion.
t_case = ATTENDU["2025-26-panini-prizm-basketball-blaster-20-box-case"]["title"]
m = hunt.match_title(t_case, SKUS)
check("un case lu en HTML passe par le même matcher", m.fmt, "Case")
check("et porte la quantité du titre", hunt.parse_quantity(hunt.norm(t_case)), 20)
t_pre = ATTENDU["2025-26-panini-origins-basketball-hobby-box-preorder-859857763"]["title"]
check("une précommande garde sa cloison séparée",
      "preorder" in hunt.exact_comp_key("X", hunt.norm(t_pre)))
check("le sealed gate s'applique tel quel", bool(hunt.sealed_product(hunt.norm(t_case))))
check("un single lu en HTML resterait écarté",
      bool(hunt.sealed_product(hunt.norm("2023-24 Panini Prizm Victor Wembanyama #136 RC"))), False)

# ---------------------------------------------------------------- robustesse
check("une page sans donnée structurée rend None",
      ha.SHOPUSCARDS.parse("<html><body>rien du tout</body></html>", "u"), None)
check("un JSON-LD cassé ne fait pas tomber la collecte",
      ha.SHOPUSCARDS.parse('<script type="application/ld+json">{oops</script>', "u"), None)
check("un sitemap vide rend une liste vide", ha.sitemap_urls("<urlset></urlset>"), [])
check("le sitemap est lu correctement",
      ha.sitemap_urls("<url><loc>https://a/products/x</loc></url>"), ["https://a/products/x"])

# la source est déclarée cohérente avec l'adaptateur
SRC = {s["key"]: s for s in yaml.safe_load((hunt.ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]}
s = SRC["shopuscards"]
check("la source est déclarée type html", s["type"], "html")
check("elle porte sa région", s["market_region"], "FR")
check("et sa devise", s["currency"], "EUR")
check("un adaptateur existe pour elle", ha.adapter_for("shopuscards") is not None)
check("la date de vérification de robots.txt est consignée", bool(s.get("robots_checked_at")))
check("aucun adaptateur pour une boutique non écrite", ha.adapter_for("dacw"), None)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
