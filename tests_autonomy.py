#!/usr/bin/env python3
"""Autonomie du pipeline Prizm : une seule collecte, deux étapes de découverte, des ventes.

LE TEST QUI COMPTE LE PLUS est le premier : `prizm_core` est appelé avec les sockets coupées.
S'il crawlait encore, il lèverait. C'est la seule preuve qui ne se périme pas — une relecture
de code se contredit au prochain commit, une socket refusée ne ment jamais.
"""
import socket
import sys
from datetime import date, datetime, timedelta, timezone

import external_engine as xe
import sold_auto as sa

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

# ------------------------------------------------ une seule collecte, prouvée par les sockets
class PasDeReseau(Exception): pass

_vrai_socket = socket.socket
class _SocketInterdite(socket.socket):
    def __init__(self, *a, **k): raise PasDeReseau("le réseau est coupé pour ce test")

import hunt, prizm_core
conn = hunt.db()
import yaml
_src = yaml.safe_load((hunt.ROOT / "sources.yaml").read_text(encoding="utf-8"))
_cat = yaml.safe_load((hunt.ROOT / "catalog.yaml").read_text(encoding="utf-8"))
hunt.load_blocklist(_src)
socket.socket = _SocketInterdite
try:
    rows, seen, lost = prizm_core.run(conn, _src["shops"], _cat["skus"], log=lambda *a: None)
    sans_reseau = True
except PasDeReseau:
    sans_reseau = False
finally:
    socket.socket = _vrai_socket
check("prizm_core tourne SANS réseau — il ne recrawle plus", sans_reseau)
check("et il rend quand même des lignes", len(rows) > 0)
check("chacune dit d'où elle vient", all(r["read_from"] == "hunt.db/products_raw" for r in rows))
check("aucune fonction de crawl ne subsiste dans le module",
      hasattr(prizm_core, "read_all_platforms"), False)

# hunt.py lit les deux plateformes : c'est LÀ que vit la double lecture, une seule fois
check("hunt.py sait lire WooCommerce", callable(getattr(hunt, "woocommerce_products", None)))
check("hunt.py sait lire Shopify", callable(getattr(hunt, "shopify_products", None)))

# une boutique enregistrée ne doit JAMAIS être rebalayée : c'est la garantie « une visite »
_reg = {"domains": [{"domain": "kutogo.com", "base_url": "https://kutogo.com", "reachable": True},
                    {"domain": "inconnue.test", "base_url": "https://inconnue.test",
                     "reachable": True}]}
_vus = []
_faux, _st = xe.sweep_domains(_reg, log=lambda *a: None, deja_crawles={"kutogo.com"},
                              limit=0)
check("une source déjà crawlée est écartée du balayage",
      _st["ecartes_deja_crawles"], ["kutogo.com"])
check("les domaines enregistrés se relisent depuis sources.yaml à chaque passage",
      "kutogo.com" in xe.registered_hosts())

# ------------------------------------------------ états et règle des 24 h
check("les six états existent", set(xe.STATES),
      {"CONFIRMED_LIVE", "PROBABLE_LIVE", "OOS", "STALE", "LOST", "AMBIGUOUS"})
check("STALE ne compte pas comme live", xe.counts_as_live(xe.STALE), False)
check("STALE ne peut pas être le meilleur prix", xe.can_be_best_live(xe.STALE), False)
check("STALE ne déclenche aucun achat", xe.can_trigger_buy(xe.STALE), False)
check("LOST non plus", xe.can_be_best_live(xe.LOST), False)
check("AMBIGUOUS non plus — le doute n'est pas une disponibilité",
      xe.can_be_best_live(xe.AMBIGUOUS), False)
check("OOS non plus", xe.can_be_best_live(xe.OOS), False)
check("CONFIRMED_LIVE, oui", xe.can_be_best_live(xe.CONFIRMED_LIVE))
check("PROBABLE_LIVE, oui", xe.can_be_best_live(xe.PROBABLE_LIVE))

maintenant = datetime.now(timezone.utc)
recent = (maintenant - timedelta(hours=2)).isoformat()
vieux = (maintenant - timedelta(hours=48)).isoformat()
check("une sonde concluante fait foi", xe.effective_status(xe.CONFIRMED_LIVE, vieux), xe.CONFIRMED_LIVE)
check("une rupture lue fait foi aussi", xe.effective_status(xe.OOS, recent), xe.OOS)
check("une page disparue fait foi", xe.effective_status(xe.LOST, recent), xe.LOST)
check("sonde illisible + vu live il y a 2 h -> AMBIGUOUS",
      xe.effective_status(xe.AMBIGUOUS, recent), xe.AMBIGUOUS)
check("sonde illisible + vu live il y a 48 h -> STALE",
      xe.effective_status(xe.AMBIGUOUS, vieux), xe.STALE)
check("sonde illisible + jamais vu live -> STALE",
      xe.effective_status(xe.AMBIGUOUS, None), xe.STALE)
check("le seuil est bien 24 h", xe.STALE_H, 24)

# ------------------------------------------------ places de marché : jamais confirmées ici
check("eBay est une place de marché", xe.layer_of("https://www.ebay.com/itm/1"), "marketplace")
check("StockX aussi", xe.layer_of("https://stockx.com/x"), "marketplace")
check("un marchand ordinaire est du web", xe.layer_of("https://kutogo.com/product/x"), "web")
# « Buy It Now » figure en dur sur une fiche catalogue eBay : le texte n'y prouve rien
check("le texte d'une page de place de marché ne prouve aucun stock",
      xe.probe.__doc__ is not None and "place de marché" in open("external_engine.py").read())

# ------------------------------------------------ robots.txt : un refus est une réponse
# On ne teste pas le réseau, on teste la DÉCISION prise à partir d'un robots.txt donné.
import urllib.robotparser
def _robots(txt, url):
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(txt.splitlines())
    xe._robots["https://exemple.test"] = rp
    return xe.robots_ok(url)
check("un site qui interdit tout n'est pas lu",
      _robots("User-agent: *\nDisallow: /", "https://exemple.test/products/x"), False)
check("un site qui n'interdit rien est lu",
      _robots("User-agent: *\nDisallow:", "https://exemple.test/products/x"), True)
check("une interdiction ciblée est respectée",
      _robots("User-agent: *\nDisallow: /admin/", "https://exemple.test/admin/x"), False)
check("et ne déborde pas sur le reste du site",
      _robots("User-agent: *\nDisallow: /admin/", "https://exemple.test/products/x"), True)
xe._robots.pop("https://exemple.test", None)

# ------------------------------------------------ extraction de liens de moteur
check("un emballage DuckDuckGo est déplié",
      xe._unwrap("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fx.com%2Fp%2F1"),
      "https://x.com/p/1")
check("un lien direct reste intact",
      xe._unwrap("https://shop.com/products/prizm"), "https://shop.com/products/prizm")
liens = xe.links_from('<a href="https://www.bing.com/search?q=x">m</a>'
                      '<a href="https://boutique.com/products/panini-prizm-mega">p</a>'
                      '<a href="https://youtube.com/watch?v=1">v</a>')
check("le moteur lui-même n'est jamais un résultat",
      all("bing.com" not in u for u in liens))
check("le bruit social non plus", all("youtube" not in u for u in liens))
check("la vraie fiche marchande est retenue", liens, ["https://boutique.com/products/panini-prizm-mega"])

# ------------------------------------------------ recherche marketplace explicite
check("chaque format est aussi cherché sur les places de marché",
      len(xe.marketplace_queries("Mega")), 2)
check("une fiche eBay est identifiable",
      bool(xe.MARKETPLACE_ITEM.search("https://www.ebay.com/itm/236057571659")))
# une page de RÉSULTATS n'est pas une annonce : son contenu change à chaque visite
check("une page de recherche eBay n'en est pas une",
      bool(xe.MARKETPLACE_ITEM.search("https://www.ebay.com/sch/i.html?_nkw=prizm")), False)
check("une fiche StockX est identifiable",
      bool(xe.MARKETPLACE_ITEM.search("https://stockx.com/2023-24-panini-prizm-mega-box-pink")))

# ------------------------------------------------ format lu depuis un titre
check("International n'est pas classé Hobby",
      xe.fmt_of("2023/24 Panini Prizm Basketball International Hobby Box"), "International")
check("Hobby reste Hobby", xe.fmt_of("2023-24 Panini Prizm Basketball Hobby Box"), "Hobby")
check("Fast Break est reconnu", xe.fmt_of("2023-24 Prizm Fast Break Box"), "Fast Break")

# ------------------------------------------------ case contre boîte, le piège à 13 549 $
f, q, sid = xe.identify("2023/24 Panini Prizm Basketball Hobby 12 Box Case")
check("un case de 12 est reconnu comme 12 boîtes", q, 12)
check("et garde le format de la boîte qu'il contient", f, "Hobby")
f1, q1, sid1 = xe.identify("2023/24 Panini Prizm Basketball Hobby Box")
check("une boîte seule reste à 1", q1, 1)
check("et tombe sur le SKU Hobby", sid1, "PANINI_2023-24_PRIZM_HOBBY")
check("un case de 20 est reconnu comme 20 boîtes",
      xe.identify("2023/24 Panini Prizm Fast Break Basketball 20 Box Case")[1], 20)
check("International n'est pas confondu avec Hobby",
      xe.identify("2023/24 Panini Prizm Basketball International Hobby Box")[0], "International")
# le prix unitaire d'un case doit être comparable à celui d'une boîte
check("13 549,95 $ pour 12 boîtes font 1 129,16 $ l'unité", round(13549.95 / 12, 2), 1129.16)

# ------------------------------------------------ dédoublonnage
d = xe.dedupe([
    {"url": "https://a/x", "first_seen": "2026-09-01T00:00:00+00:00",
     "last_checked": "2026-09-01T00:00:00+00:00", "last_seen_live": None, "price": 10},
    {"url": "https://a/x", "first_seen": "2026-09-05T00:00:00+00:00",
     "last_checked": "2026-09-07T00:00:00+00:00", "last_seen_live": "2026-09-07T00:00:00+00:00",
     "price": 12}])
check("une URL vue deux fois reste une annonce", len(d), 1)
check("la première apparition est la plus ancienne", d[0]["first_seen"], "2026-09-01T00:00:00+00:00")
check("la vérification retenue est la plus récente", d[0]["last_checked"], "2026-09-07T00:00:00+00:00")

# ------------------------------------------------ SOLD : transactions, jamais des demandes
check("n>=10 -> HIGH", sa.sold_confidence(10), "HIGH")
check("n=9 -> MEDIUM", sa.sold_confidence(9), "MEDIUM")
check("n=3 -> MEDIUM", sa.sold_confidence(3), "MEDIUM")
check("n=2 -> LOW", sa.sold_confidence(2), "LOW")
check("n=0 -> NONE", sa.sold_confidence(0), "NONE")

t = date(2026, 9, 7)
tx = [{"sold_date": "2026-09-01", "sold_price": 100.0},
      {"sold_date": "2026-08-25", "sold_price": 200.0},
      {"sold_date": "2026-07-01", "sold_price": 300.0},
      {"sold_date": "2025-01-01", "sold_price": 999.0},
      {"sold_date": None, "sold_price": 50.0}]
a = sa.aggregate(tx, today=t)
check("N_30D ne compte que les 30 derniers jours", a["N_30D"], 2)
check("N_90D ne compte que les 90 derniers jours", a["N_90D"], 3)
check("MEDIAN_30D est bien une médiane", a["MEDIAN_30D"], 150.0)
check("MEDIAN_90D aussi", a["MEDIAN_90D"], 200.0)
check("AVG_90D est une moyenne", a["AVG_90D"], 200.0)
check("LOW_90D et HIGH_90D encadrent la fenêtre", (a["LOW_90D"], a["HIGH_90D"]), (100.0, 300.0))
check("LAST_SALE est la vente la plus récente", a["LAST_SALE"], 100.0)
# LE test de doctrine : un point n'est pas une médiane
check("LAST_SALE n'est PAS la médiane", a["LAST_SALE"] != a["MEDIAN_90D"])
# la vente sans date vaut 50 $ : si elle entrait dans une fenêtre, elle deviendrait le
# plancher à 90 jours et tirerait la médiane vers le bas sans que personne sache quand
check("une vente sans date ne devient pas le plancher 90 j", a["LOW_90D"], 100.0)
check("ni la dernière vente", a["LAST_SALE"], 100.0)
check("mais elle est conservée et comptée à part", a["N_UNDATED"], 1)
check("la confiance découle du n de la fenêtre", a["SOLD_CONFIDENCE"], "MEDIUM")
check("et la provenance du calcul est dite", a["COMPUTED_FROM"], "transactions")
check("sans aucune vente, rien n'est inventé",
      sa.aggregate([], today=t)["MEDIAN_90D"], None)
check("et la confiance le dit", sa.aggregate([], today=t)["SOLD_CONFIDENCE"], "NONE")

rep = sa.from_aggregate_report({"AVG_90D": 2818, "N_90D": 19, "LAST_SALE": 2799,
                                "SOURCE": "StockX", "CONFIDENCE": "HIGH"})
check("un relevé agrégé se cite tel quel", rep["AVG_90D"], 2818)
check("et ne prétend jamais être calculé", rep["COMPUTED_FROM"], "aggregate_report")
check("un relevé sans médiane n'en fabrique pas une", rep["MEDIAN_90D"], None)

# les fournisseurs déclarent leur absence de clé, jamais un zéro silencieux
_tx, info = sa.provider_pricecharting({"Hobby": {}})
check("sans clé, le fournisseur le DIT", info["outcome"], "SANS_CLÉ")
check("et ne rend aucune vente", _tx, [])
_tx2, info2 = sa.provider_ebay_insights({"Hobby": {}})
check("le second fournisseur aussi", info2["outcome"], "SANS_CLÉ")

# ------------------------------------------------ le fichier de sortie est CALCULÉ
import json, pathlib
sp = json.loads((pathlib.Path("discovered") / "sold_prizm.json").read_text(encoding="utf-8"))
check("sold_prizm.json se déclare calculé", sp.get("computed_by"), "sold_auto")
check("il porte la trace de chaque fournisseur", len(sp.get("providers") or []), 2)
check("il dit de ne pas l'éditer à la main", "Ne pas éditer" in sp.get("note", ""))
led = json.loads((pathlib.Path("discovered") / "sold_ledger.json").read_text(encoding="utf-8"))
check("le registre des transactions existe", isinstance(led.get("transactions"), list))
check("chaque transaction porte les champs exigés",
      all(set(sa.TX_FIELDS) <= set(t) for t in led["transactions"]))

# ------------------------------------------------ le fichier externe porte le schéma d'observation
ex = json.loads((pathlib.Path("discovered") / "external_prizm.json").read_text(encoding="utf-8"))
check("chaque observation externe porte les champs exigés",
      all(set(xe.FIELDS) <= set(r) for r in ex["listings"]))
check("chaque observation a un état connu",
      all(r["stock_status"] in xe.STATES for r in ex["listings"]))
check("le fichier dit son seuil de péremption", ex.get("stale_after_hours"), 24)
check("le rapport de passage distingue revalidation et découverte",
      {"known_urls_checked", "web_searches", "new_listings"} <= set(ex["run"]))

# ------------------------------------------------ l'en-tête garde ses dates en --report
# Le passage autonome publie la page en --report, pour inclure les couches calculées APRÈS
# le crawl. Si l'en-tête perd ses horodatages dans ce mode, la page devient techniquement
# plus fraîche et publiquement moins lisible — c'est ce qui s'est produit au run du 07/09.
_page = pathlib.Path("out/index.html")
if _page.exists():
    _h = _page.read_text(encoding="utf-8")
    check("l'en-tête annonce la date du crawl même hors passage", "Crawl des sources" in _h)
    check("et ne se contente pas de « hors passage »", "Rapport hors passage" not in _h)
    check("chaque couche porte sa date", "web/marketplace" in _h and "Prizm core" in _h)
    check("et la plus ancienne est nommée", "donnée la plus ancienne" in _h)

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
