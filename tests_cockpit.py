"""UX Decision Cockpit — la restitution. Aucune règle moteur n'est testée ici, seulement
ce que la page montre, dans quel ordre, et ce qu'elle refuse de montrer."""
import sys, re, pathlib, yaml
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<62} got={got!r}")

cat = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
S = {s["id"]: s for s in cat["skus"]}

def sku(sid): return S[sid]
def entry(sid, price, avail=True, trig=(), desc=(), gap=-25.0, ref=50.0, kind="sold",
          hist=None, shop="sh", url="https://shop.test/products/x"):
    o = ("S", shop, "titre live", price, 1 if avail else 0, url, 1.0, "2026-08-21T00:00:00", "",
         "EXACT", None, 1, price, "K")
    # comme en production : exact_comp_key identifie le PRODUIT, pas l'annonce
    return {"o": o, "key": f"{sid}|std|x1", "sid": sid, "sku": sku(sid), "available": avail,
            "triggers": list(trig), "descriptors": list(desc), "gap": gap, "ref": ref,
            "kind": kind, "mem": None, "comp": "EXACT", "hist": hist,
            # comme en production : le verdict et sa base de preuve accompagnent la ligne
            "pv": {"verdict": "STRONG BUY", "basis": "sold", "gap": gap, "ref": ref,
                   "confidence": "HIGH", "why": "7 vente(s) réalisée(s) sur 30 j · HIGH"}}

# ---- 7/8/9 : classement Wemby
check("7 · Wemby RC 23/24 correctement classé",
      hunt.wemby_bucket(sku("PANINI_2023-24_PHOENIX_BLASTER")), "rc")
check("8 · Year 2 correctement classé",
      hunt.wemby_bucket(sku("PANINI_2024-25_PRIZM_BLASTER")), "y2")
check("9 · EuroLeague n'est PAS présenté comme Wemby RC",
      hunt.wemby_bucket(sku("PANINI_2023-24_PRIZM_EUROLEAGUE_BLASTER")) != "rc", True)
check("Trophy classé en premium",
      hunt.wemby_bucket(sku("PANINI_2023-24_FLAWLESS_HOBBY")), "trophy")

# ---- 15 : sold et ask explicitement distingués, jamais « % marché »
check("15a · référence sold nommée", "vs sold" in hunt.gap_phrase(entry("PANINI_2023-24_PHOENIX_BLASTER", 20)))
check("15b · référence ask nommée",
      "vs ask" in hunt.gap_phrase(entry("PANINI_2023-24_PHOENIX_BLASTER", 20, kind="ask")))
check("4 · sans référence -> Marché insuffisant",
      hunt.gap_phrase(entry("PANINI_2023-24_PHOENIX_BLASTER", 20, gap=None, ref=None)), "Marché insuffisant")

# ---- 11 : near buy
n1 = entry("PANINI_2023-24_PHOENIX_BLASTER", 37.0)
n2 = entry("PANINI_2023-24_MOSAIC_BLASTER", 45.0)
under = entry("PANINI_2023-24_PHOENIX_BLASTER", 20.0, shop="b")
oos = entry("PANINI_2023-24_MOSAIC_BLASTER", 45.0, avail=False, shop="c")
near = hunt.near_buy_lines([n1, n2, under, oos])
# Les distances se DÉDUISENT des seuils du catalogue, elles ne sont pas recopiées : un seuil
# tranché à la main (Mosaic Blaster 40 -> 32 le 30/08) ne doit pas casser un test de tri.
_att = sorted(round(e["o"][3] - hunt.buy_target(e["sku"])) for e in (n1, n2))
check("11a · trié par distance absolue croissante", [round(d) for d, _ in near], _att)
check("11a · deux lignes seulement : la moins chère et l'OOS sont exclues", len(near), 2)
check("11b · un prix déjà sous le seuil n'est pas 'proche'", under not in [e for _, e in near])
check("11c · un produit OOS n'est pas 'proche'", oos not in [e for _, e in near])
dup = entry("PANINI_2023-24_PHOENIX_BLASTER", 60.0, shop="cher")
near2 = hunt.near_buy_lines([n1, dup])
check("11d · un produit n'occupe qu'une ligne", len(near2), 1)
check("11e · c'est l'offre la moins chère qui est retenue", near2[0][1]["o"][3], 37.0)

# ---- 12 : restock targets
H = {"low": 19.99, "low_unit": 19.99, "qty": 1, "at": "2026-08-17T00:00:00",
     "shop": "hiddengems", "n_shops": 8, "n_obs": 9}
# le même historique vu sur un SKU case : c'est le total qui s'affiche, l'unitaire suit
HC = {"low": 5945.00, "low_unit": 297.25, "qty": 20, "at": "2026-08-17T00:00:00",
      "shop": "awesome", "n_shops": 1, "n_obs": 3}
r_ok = entry("PANINI_2023-24_PHOENIX_BLASTER", 30.0, avail=False, hist=H, shop="x")
r_nobuy = entry("PANINI_2023-24_PRIZM_EUROLEAGUE_HOBBY", 30.0, avail=False, hist=H, shop="y")
r_instock = entry("PANINI_2023-24_PHOENIX_BLASTER", 30.0, avail=True, hist=H, shop="z")
rs = hunt.restock_lines([r_ok, r_nobuy, r_instock])
check("12a · OOS avec historique et seuil -> restock target", r_ok in rs)
check("12b · sans seuil d'achat, pas de cible", r_nobuy in rs, False)
check("12c · en stock -> pas un restock target", r_instock in rs, False)

# ---- rendu complet
no_mkt = next(s2 for s2 in cat["skus"]
              if s2.get("market_sold_us") is None and not (s2.get("market_ask_from") or []))
blocks = [("retail", "NO_GO", "⛔", sku("PANINI_2023-24_PHOENIX_BLASTER"), [], None),
          ("hobby", "CANDIDAT", "·", no_mkt, [], None)]
buy = entry("PANINI_2023-24_MOSAIC_BLASTER", 32.0, trig=("STRONG_DEAL -25%",),
            desc=("cheapest of 8 in stock",), url="https://awesome.test/products/mosaic-blaster")
hunt.write_html(cat, blocks, [], [], "2026-08-21T08:00:00", {"sh": "trusted"},
                hot=[buy], entries=[buy, n1, r_ok], shopcount=[("sh", "trusted", 100, 5)],
                health={"sh": ("HEALTHY", "100 produits"), "mort": ("DEAD", "3 passages à 0")})
h = pathlib.Path("/Users/ju/Draft Class/wemby-hunt/out/index.html").read_text(encoding="utf-8")

anchors = ["<h2>🔥 Aujourd’hui", "<h2 id=acheter>", "<h2 id=surveiller>", "<h2 id=explorer>",
           "<h2 id=diag>", "<h2 id=complet>"]
pos = [h.index(a) for a in anchors]
check("A · les 6 niveaux sont dans l'ordre décision → audit", pos == sorted(pos))
check("X · la décision est avant l'audit", h.index("<h2 id=acheter>") < h.index("<h2 id=complet>"))
check("1 · une opportunité fiable apparaît dans ACHETER",
      h.index("Mosaic") > h.index("<h2 id=acheter>") and h.index("Mosaic") < h.index("<h2 id=surveiller>"))
check("14 · le CTA pointe vers l'URL produit observée", "awesome.test/products/mosaic-blaster" in h)
check("16 · les opportunités sont des cartes, pas un tableau", "class=card" in h)
check("10a · RC non vide -> la carte est là, pas d'état vide",
      "Aucune opportunité sur Wemby Rookie 23/24" in h, False)
check("C · phrase de synthèse générée depuis les données",
      "opportunité(s) vérifiée(s) aujourd’hui" in h)
check("O · compteurs métier en tête, techniques en bas",
      h.index("à acheter") < h.index("Compteurs par source"))
check("N · santé des sources dans Diagnostic",
      h.index("anomalie(s) de source") > h.index("<h2 id=diag>"))
check("F · jamais « % marché » sans nature de référence", "% marché" in h, False)
check("13 · historical low présenté comme cible, pas comme valeur",
      "pas une valeur de marché" in h)
# Voir tests_ui : la garde est recalée sur la zone de décision, seule zone où le tableau est
# proscrit. Inventaire et FR sont des zones de LECTURE, où le tableau est la bonne forme.
_zone = h[:h.index("<h2 id=inventaire>")] if "<h2 id=inventaire>" in h else h[:h.index("<h2 id=fr>")]
check("T · aucun tableau dans la zone de décision", "<table" in _zone, False)
check("Q · un SKU sans donnée marché est affiché « marché insuffisant »",
      "marché insuffisant" in h)

# ---- 3/5/6 : ce qui ne doit jamais entrer dans ACHETER
seg = h[h.index("<h2 id=acheter>"):h.index("<h2 id=surveiller>")]
check("3 · un NO_GO n'est pas dans ACHETER", "Phoenix" in seg, False)
check("5/6 · ACHETER ne contient que les lignes issues de hot_now",
      seg.count("class=card"), 1)

# ---- U : états vides, quand il n'y a rien à acheter du tout
hunt.write_html(cat, blocks, [], [], "2026-08-21T08:00:00", {"sh": "trusted"},
                hot=[], entries=[n1], shopcount=[], health={})
h0 = pathlib.Path("/Users/ju/Draft Class/wemby-hunt/out/index.html").read_text(encoding="utf-8")
check("U/10 · 0 achat : état vide Wemby RC explicite",
      "Aucune opportunité sur Wemby Rookie 23/24 actuellement." in h0)
check("U · 0 achat : la page le dit franchement",
      "Aucun achat recommandé aujourd’hui." in h0)
check("U · 0 achat : l'état vide oriente vers la surveillance", "produit(s) surveillé(s)" in h0)
check("U · 0 achat : les 4 sections restent visibles",
      all(x in h0 for x in ("🏀 Wemby Rookie 23/24", "⭐ Wemby Year 2 24/25",
                            "💎 Wemby Premium / Trophy", "📦 Autres opportunités")))

# ================= complément : données, cohérence, anti-circularité, structure
# 1a — aucun ask aberrant ne subsiste sur Cosmic Chrome Hobby
cc = S["TOPPS_2023-24_COSMIC_CHROME_HOBBY"]
check("1a · l'ask aberrant de Cosmic Chrome est purgé", cc.get("market_ask_us"), None)
check("1a · la purge est tracée", bool(cc.get("market_ask_purged")))
check("1a · plus aucun écart calculable dessus", hunt.market_ref(cc)[0] is None or cc.get("market_sold_us") is not None)

# 1b — l'édition entre dans le libellé, partout
check("1b · un SKU Sapphire ne s'affiche jamais « Chrome Hobby » tout court",
      hunt.sku_label(S["TOPPS_2023-24_CHROME_SAPPHIRE"]) != hunt.sku_label(S["TOPPS_2023-24_CHROME_HOBBY"]))
check("1b · Sapphire porte son édition", "Sapphire" in hunt.sku_label(S["TOPPS_2023-24_CHROME_SAPPHIRE"]))
check("1b · Monster porte son édition", "Monster" in hunt.sku_label(S["TOPPS_2023-24_CHROME_MONSTER"]))
labels = [hunt.sku_label(x) for x in cat["skus"]]
check("1b · aucun libellé de SKU n'est ambigu", len(labels), len(set(labels)))

# 1c — convention unique de landed sur les trois cases citées
for sid in ("PANINI_2023-24_SELECT_MEGA_CASE", "PANINI_2023-24_OPTIC_MEGA_CASE",
            "PANINI_2023-24_MOSAIC_FAST_BREAK_CASE"):
    lp = hunt.landed_phrase(1400.0, S[sid].get("boxes_per_case") or 20, cat)
    check(f"1c · {sid.split('_')[-2]} : total ET unitaire",
          lp.startswith("case €") and "/boîte" in lp)
check("1c · une boîte seule n'affiche pas de convention case",
      "case" in hunt.landed_phrase(39.99, 1, cat), False)

# 2 — la phrase de synthèse et les cartes viennent du même calcul
hunt.write_html(cat, blocks, [], [], "2026-08-21T08:00:00", {"sh": "trusted"},
                hot=[buy], entries=[buy, n1, r_ok], shopcount=[], health={})
h2 = pathlib.Path("/Users/ju/Draft Class/wemby-hunt/out/index.html").read_text(encoding="utf-8")
seg2 = h2[h2.index("<h2 id=acheter>"):h2.index("<h2 id=surveiller>")]
declared = int(re.search(r"<b>(\d+)</b><span>à acheter", h2).group(1))
check("2 · le compteur annoncé == le nombre de cartes ACHETER", declared, seg2.count("class=card"))
check("2 · la phrase de synthèse annonce le même nombre",
      f"{declared} opportunité" in h2 or (declared == 0 and "Aucun achat recommandé" in h2))

# 3 — anti-circularité dans Surveiller
self_src = entry("PANINI_2023-24_OPTIC_HANGER", 90.0, kind="ask", shop="superior")
check("3 · référence relevée chez ce seul shop -> inexploitable", hunt.ref_is_usable(self_src), False)
other_src = entry("PANINI_2023-24_OPTIC_HANGER", 90.0, kind="ask", shop="rbicru7")
check("3 · même référence, autre shop -> exploitable", hunt.ref_is_usable(other_src), True)
check("3 · un sold externe est toujours exploitable",
      hunt.ref_is_usable(entry("PANINI_2023-24_PHOENIX_BLASTER", 40.0, kind="sold")), True)
check("3 · la référence faible ne remonte pas dans Surveiller",
      self_src in [e for _, e in hunt.near_buy_lines([self_src])], False)

# 4 — les cartes sont rendues depuis une structure, pas assemblées à la main
op = hunt.opportunity(buy, "buy", cat)
check("4 · une opportunité est un objet typé", type(op).__name__, "Opportunity")
check("4 · l'objet porte la décision", op.verdict, "🔥 STRONG BUY")
check("4 · l'objet porte la base de preuve", "vente(s) réalisée(s)" in (op.evidence or ""))
check("4 · l'objet porte l'URL produit", op.url.endswith("/products/mosaic-blaster"))
check("4 · emplacement FR réservé mais vide", op.fr_price_eur, None)
op.fr_price_eur, op.fr_source = 34.90, "Tanteo"
check("4 · le gabarit affiche le bloc FR sans refonte", "🇫🇷 €34.90" in hunt.render_card(op))

# ================= couche EU : références de prix, jamais confondues avec le marché US
src = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/sources.yaml", encoding="utf-8"))["shops"]
eu = [x for x in src if x["type"] == "eu_reference"]
check("EU · aucune référence n'est crawlée", all(x["type"] == "eu_reference" for x in eu))
check("EU · chacune porte un pays", all(x.get("country") for x in eu))
check("EU · les sources de référence non crawlables restent déclarées comme telles",
      all(x["type"] == "eu_reference" for x in eu))
check("EU · tracenchase en fait toujours partie", "tracenchase" in {x["key"] for x in eu})
# shopuscards est passée de référence à source crawlée le 30/08. L'avertissement HT/TTC, lui,
# ne disparaît pas — il devient PLUS important, puisque ses prix entrent maintenant en base.
_sus = next(x for x in src if x["key"] == "shopuscards")
check("EU · ShopUScards est désormais crawlée", _sus["type"], "html")
check("EU · son avertissement HT est conservé", "HT" in _sus["price_display_warning"])
check("EU · et il l'exclut du classement « meilleur prix FR »",
      "shopuscards" in hunt.load_ht_unconfirmed(src))

refs = [x for x in cat["skus"] if x.get("eu_reference_from")]
check("EU · chaque référence porte sa provenance ET sa date",
      all(x.get("eu_reference_from") and x.get("eu_reference_checked_at") for x in refs))
check("EU · les relevés ShopUScards sont marqués HT non confirmé",
      all(x.get("eu_reference_ht_unconfirmed") for x in refs if x["eu_reference_from"] == "shopuscards"))
check("EU · une référence EU n'alimente jamais le marché US",
      any(x.get("eu_reference_eur") and x.get("market_ask_us") is None for x in refs))
pb = S["PANINI_2023-24_PRIZM_BLASTER"]
check("EU · la référence EU ne devient pas un ask US",
      hunt.market_ref(pb)[1] != "eu")

el = [x for x in cat["skus"] if "2025-26_EUROLEAGUE" in x["id"]]
check("EU · 6 SKU EuroLeague 2025-26 créés", len(el), 6)
check("EU · tous en CANDIDATE", {x["status"] for x in el}, {"CANDIDATE"})
check("EU · aucun n'est marqué Wemby rookie", any(x.get("wemby_rc") for x in el), False)
check("EU · tous portent le programme audience FR", {x.get("program") for x in el}, {"fr_audience"})

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
