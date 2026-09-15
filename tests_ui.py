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
# la zone de décision s'arrête à la PREMIÈRE section de lecture, quelle qu'elle soit :
# Prizm Core est arrivée entre Surveiller et Inventaire le 06/09
_fin = next((h.index(a) for a in ("<h2 id=prizm>", "<h2 id=inventaire>", "<h2 id=fr>") if a in h), len(h))
_zone = h[:_fin]
check("aucun tableau dans la zone de décision (Acheter + Surveiller)", "<table" in _zone, False)
check("la zone de décision contient bien des cartes", "class=card" in _zone)
check("le prix est mis en avant sur la carte", 'class=pr' in h)

# ---------------------------------------------- liens produit, bug du 15/09
# Le tableau des anomalies passait o[6] — le SCORE DE MATCHING — à A() au lieu de o[5], l'URL.
# Chaque lien pointait donc vers « 1.0 », que le navigateur résolvait en chemin relatif sur le
# site public : jucafede.github.io/wemby-hunt/1.0, une 404 chez nous au lieu de la boutique.
check("une URL absolue est un lien", "<a" in hunt.A("https://boutique.fr/p", "x"))
check("un score n'en est pas un", "<a" in hunt.A(1.0, "x"), False)
check("« 1.0 » non plus", "<a" in hunt.A("1.0", "x"), False)
check("un chemin relatif non plus", "<a" in hunt.A("/produit/3", "x"), False)
check("une chaîne vide non plus", "<a" in hunt.A("", "x"), False)
check("None non plus", "<a" in hunt.A(None, "x"), False)
check("une clé de boutique non plus", "<a" in hunt.A("kutogo", "x"), False)
check("javascript: non plus", "<a" in hunt.A("javascript:alert(1)", "x"), False)
# le produit reste affiché, seule l'action de lien disparaît
check("le libellé survit quand le lien tombe", "Prizm Hobby" in hunt.A("1.0", "Prizm Hobby"))
check("et il est rendu en span", "<span" in hunt.A("1.0", "Prizm Hobby"))

# ---------------------------------------------- le tableau Prizm doit être cliquable
# C'est la section la plus consultée, et elle n'offrait AUCUN moyen d'atteindre la fiche :
# il fallait relever le nom du vendeur puis retrouver le produit à la main sur son site.
import pathlib as _pl
_pg = _pl.Path(__file__).parent / "out" / "index.html"
if _pg.exists():
    _h = _pg.read_text(encoding="utf-8")
    _seg = _h[_h.find("Prizm Wemby Core"):][:12000]
    import re as _re
    _liens = _re.findall(r"href='(https?://[^']+)'", _seg)
    check("le tableau Prizm porte des liens produit", len(_liens) > 0)
    check("et ils sortent tous vers une vraie boutique",
          all(not u.startswith("https://jucafede.github.io") for u in _liens))

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
