"""Hygiène UI de la page publiée. L'ordre des sections et la logique décisionnelle sont
couverts par tests_cockpit ; ici on garde ce qui doit rester vrai quelle que soit la refonte."""
import sys, re, pathlib, yaml
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<58} got={got!r}")

cat = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
sku = [s for s in cat["skus"] if s["id"].endswith("EUROLEAGUE_BLASTER")][0]
o = ("SKU", "cardiacs", "Prizm EuroLeague Blaster Box", 9.95, 1, "https://x.test/products/p", 1.0,
     "2026-08-21T00:00:00", "", "EXACT", "https://img/x.jpg", 1, 9.95, "K")
e = {"o": o, "key": "K", "sid": sku["id"], "sku": sku, "available": True,
     "triggers": ["STRONG_DEAL -60%"], "descriptors": ["EUROLEAGUE", "VERIFY"],
     "gap": -60.2, "ref": 25.0, "kind": "ask", "mem": None, "comp": "EXACT", "hist": None}
hunt.write_html(cat, [("retail", "PRICE ANOMALY — NO SOLD DATA", "⚡", sku, [], None)],
                [], [], "2026-08-21T00:00:00", {"cardiacs": "watch"},
                hot=[e], entries=[e], shopcount=[("cardiacs", "watch", 5278, 2)],
                health={"cardiacs": ("HEALTHY", "5278 produits")})
h = pathlib.Path("/Users/ju/Draft Class/wemby-hunt/out/index.html").read_text(encoding="utf-8")

ext = re.findall(r"<a\s[^>]*href='(?!#)[^']*'[^>]*>", h)
check("tous les liens sortants en nouvel onglet",
      all('target="_blank"' in a and 'rel="noopener noreferrer"' in a for a in ext))
check("au moins un lien sortant rendu", len(ext) > 0)
check("les ancres internes restent dans l'onglet",
      all('target="_blank"' not in a for a in re.findall(r"<a\s[^>]*href='#[^']*'[^>]*>", h)))
check("toute image est lazy", h.count('loading="lazy"') == h.count("<img"))
check("miniature 56 px sur la carte de décision", "width=56" in h)
check("libellé produit inclut la ligue", "Prizm EuroLeague Blaster" in h)
check("viewport mobile", "width=device-width" in h)
check("thème sombre pris en charge", "prefers-color-scheme:dark" in h)
# La règle protège la ZONE DE DÉCISION — Acheter et Surveiller — où l'on tranche par cartes,
# jamais par tableaux. Elle était écrite « avant Explorer », ce qui ne mordait pas : la section
# FR rend un tableau et se trouve avant Explorer. Sur la page publiée du 30/08, un tableau
# passait donc déjà la garde. Recalée sur l'ancre exacte, elle mord enfin.
_zone = h[:h.index("<h2 id=inventaire>")] if "<h2 id=inventaire>" in h else h[:h.index("<h2 id=fr>")]
check("aucun tableau dans la zone de décision (Acheter + Surveiller)", "<table" in _zone, False)
check("la zone de décision contient bien des cartes", "class=card" in _zone)
check("le prix est mis en avant sur la carte", 'class=pr' in h)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
