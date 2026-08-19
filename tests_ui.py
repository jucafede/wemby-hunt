"""V2-b — structure du dashboard et règles UI. Rendu réel, aucune assertion sur des maquettes."""
import sys, re, pathlib, yaml
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(name, got, want=True):
    total.append(name); ok = got == want
    if not ok: fails.append((name, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {name:<58} got={got!r}")

cat = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
sku = [s for s in cat["skus"] if s["id"].endswith("EUROLEAGUE_BLASTER")][0]
o = ("SKU", "cardiacs", "Prizm EuroLeague Blaster Box", 9.95, 1, "https://x/p", 1.0,
     "2026-08-18T00:00:00", "", "EXACT", "https://img/x.jpg")
e = {"o": o, "available": True, "triggers": ["STRONG_DEAL -60%"], "descriptors": ["EUROLEAGUE", "VERIFY"],
     "gap": -60.2, "ref": 25.0, "kind": "ask", "mem": None, "comp": "EXACT", "sku": sku, "sid": sku["id"]}
blocks = [("retail", "PRICE ANOMALY — NO SOLD DATA", "⚡", sku, [o], o)]
hunt.write_html(cat, blocks, [], [], "2026-08-18T00:00:00", {"cardiacs": "watch"},
                hot=[e], entries=[e], shopcount=[("cardiacs", "watch", 5278, 2)])
h = pathlib.Path("/Users/ju/Draft Class/wemby-hunt/out/index.html").read_text(encoding="utf-8")

order = ["Hot now", "Rookie 23/24", "Year 2", "Trophy", "Mouvements récents",
         "Watchlist", "Shops découverts", "À revoir", "Rapport complet"]
idx = [h.index(x) for x in order]
check("D : les 8 sections sont dans l'ordre", idx == sorted(idx))
# N : la watchlist expose ses trois couches, les deux dernières repliées
check("N : couche Restock priority ou son absence justifiée",
      "Restock priority" in h or "Aucune priorité qualifiable" in h)
check("N : Historical lows et All OOS sont repliés",
      h.count("<details>") >= 2)
check("C : HOT NOW est en tête", h.index("Hot now") < h.index("Rookie 23/24"))
check("D : compteurs techniques hors premier écran", h.index("Compteurs par source") > h.index("Rapport complet"))

ext = re.findall(r"<a\s[^>]*href='(?!#)[^']*'[^>]*>", h)
check("O : tous les liens sortants en nouvel onglet",
      all('target="_blank"' in a and 'rel="noopener noreferrer"' in a for a in ext))
check("O : au moins un lien sortant rendu", len(ext) > 0)
check("O : miniature 56 px sur HOT NOW", "width=56" in h and 'loading="lazy"' in h)
check("O : toute image est lazy", h.count('loading="lazy"') == h.count("<img"))
check("C : badge déclencheur rendu", "STRONG_DEAL -60%" in h)
check("C : écart affiché", "-60.2" in h)
check("libellé inclut la ligue", "Prizm EuroLeague Blaster" in h)
check("mobile : viewport présent", "width=device-width" in h)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for x in fails: print("  FAIL", x)
sys.exit(1 if fails else 0)
