"""Tests de robustesse de la pagination — sans réseau, session simulée.

Régression couverte : le 18/08, awesome est tombé de 7 266 à 2 000 produits (8 pages) et de
40 matchs à 1, sur une erreur HTTP passagère. shopify_products faisait `break` sur tout
non-200 et retournait silencieusement un catalogue tronqué, sous un run vert.
"""
import sys, sqlite3, tempfile
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

hunt.RATE_S = 0          # pas d'attente en test
hunt.BACKOFF = (0, 0)

class Resp:
    def __init__(self, code, payload=None): self.status_code, self._p = code, payload or {}
    def json(self): return self._p

class FakeSession:
    """`script` : liste de codes HTTP servis dans l'ordre. 200 -> une page pleine de 250 produits."""
    def __init__(self, script, page_size=250):
        self.script, self.page_size, self.calls = list(script), page_size, 0
        self.headers = {}
    def get(self, url, params=None, timeout=None):
        code = self.script[self.calls] if self.calls < len(self.script) else 500
        self.calls += 1
        if code != 200: return Resp(code)
        n = self.page_size
        start = (params or {}).get("page", 1) * 1000
        return Resp(200, {"products": [{"id": start + i, "title": "x", "handle": "h",
                                        "variants": [{"title": "Default Title", "price": "1"}]}
                                       for i in range(n)]})

fails = []
def check(name, got, want):
    ok = got == want
    if not ok: fails.append((name, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {name:<62} got={got} want={want}")

# 1. Nominal : 3 pages pleines puis une page courte -> complet
s = FakeSession([200, 200, 200, 200]); s.page_size = 250
class ShortLast(FakeSession):
    def get(self, url, params=None, timeout=None):
        p = (params or {}).get("page", 1)
        if p == 4: self.page_size = 10
        return super().get(url, params, timeout)
s = ShortLast([200, 200, 200, 200])
prods, partial = hunt.shopify_products("https://x.test", s)
check("nominal : pagination complète -> partial=False", partial, False)
check("nominal : 3x250 + 10 produits collectés", len(prods), 760)

# 2. Erreur définitive après 3 pages -> PARTIAL (le cas awesome)
s = FakeSession([200, 200, 200] + [500] * 20)
prods, partial = hunt.shopify_products("https://x.test", s)
check("erreur persistante en page 4 -> partial=True", partial, True)
check("erreur persistante : produits déjà collectés conservés", len(prods), 750)
check("erreur persistante : 3 tentatives sur la page en échec", s.calls, 3 + hunt.RETRIES)

# 3. Erreur PASSAGÈRE : le retry doit sauver la pagination
class Flaky(FakeSession):
    def get(self, url, params=None, timeout=None):
        p = (params or {}).get("page", 1)
        if p == 2 and not getattr(self, "hit", False):
            self.hit = True; self.calls += 1; return Resp(503)
        if p == 3: self.page_size = 5
        return super().get(url, params, timeout)
s = Flaky([200] * 30)
prods, partial = hunt.shopify_products("https://x.test", s)
check("erreur passagère : retry réussi -> partial=False", partial, False)
check("erreur passagère : catalogue complet", len(prods), 505)

# 4. Échec dès la page 1 -> pas de produits, pas PARTIAL (shop vide, pas tronqué)
s = FakeSession([500] * 40)
prods, partial = hunt.shopify_products("https://x.test", s)
check("échec dès la page 1 -> partial=False (rien à tronquer)", partial, False)
check("échec dès la page 1 -> 0 produit", len(prods), 0)

# 5. Un passage PARTIAL n'est jamais le dernier passage réussi
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
hunt.DB = __import__("pathlib").Path(db)
conn = hunt.db()
conn.execute("INSERT INTO products_raw VALUES ('sh','h','t','',NULL,NULL,1,NULL,1,'u',NULL,NULL,NULL,NULL,NULL,0,'[]','2026-01-01T00:00:00')")
conn.execute("INSERT INTO products_raw VALUES ('sh','h2','t','',NULL,NULL,1,NULL,1,'u',NULL,NULL,NULL,NULL,NULL,0,'[]','2026-01-02T00:00:00')")
conn.execute("INSERT INTO crawl_runs VALUES ('sh','2026-01-01T00:00:00',0,100)")
conn.execute("INSERT INTO crawl_runs VALUES ('sh','2026-01-02T00:00:00',1,7)")   # tronqué
conn.commit()
last = dict(conn.execute("""
    SELECT shop, MAX(seen_at) FROM products_raw p
    WHERE NOT EXISTS (SELECT 1 FROM crawl_runs c
                      WHERE c.shop=p.shop AND c.seen_at=p.seen_at AND c.partial=1)
    GROUP BY shop""").fetchall())
check("passage PARTIAL ignoré : référence = passage complet précédent",
      last.get("sh"), "2026-01-01T00:00:00")

print(f"\nTOTAL : 10 tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
