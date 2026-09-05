"""O — santé des sources. Un PARTIAL dû au chrono n'est pas une source morte."""
import sys, tempfile, pathlib
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<60} got={got!r}")

hunt.DB = pathlib.Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
c = hunt.db()
def run(shop, day, partial, n_raw, reason=None, dur=60.0):
    c.execute("INSERT OR REPLACE INTO crawl_runs VALUES (?,?,?,?,?,?)",
              (shop, f"2026-04-{day:02d}T00:00:00", partial, n_raw, dur, reason))

# sain : volume stable
for d, n in [(1, 1000), (2, 1010), (3, 990)]: run("ok", d, 0, n)
# coupé par le chrono une fois : PARTIAL, surtout pas DEAD
for d, n in [(1, 1000), (2, 1010)]: run("slow", d, 0, n)
run("slow", 3, 1, 0, "TIMEOUT", 481.0)
# interrompu à répétition
for d in (1, 2, 3): run("flaky", d, 1, 5, "ERROR:ConnectionError")
# volume effondré
for d, n in [(1, 1000), (2, 1000), (3, 120)]: run("drop", d, 0, n)
# réellement muette
for d in (1, 2, 3): run("dead", d, 0, 0)
# volontairement non crawlée
run("skipped", 3, 0, 0, "SKIPPED:MARKETPLACE", 0.0)
c.commit()

h = hunt.source_health(c, ["ok", "slow", "flaky", "drop", "dead", "skipped", "jamais"])
check("volume stable -> HEALTHY", h["ok"][0], "HEALTHY")
check("timeout unique -> PARTIAL, pas DEAD", h["slow"][0], "PARTIAL")
check("le motif du PARTIAL est conservé", "TIMEOUT" in h["slow"][1])
check("interruptions répétées -> DEGRADED", h["flaky"][0], "DEGRADED")
check("volume effondré vs sa propre base -> DEGRADED", h["drop"][0], "DEGRADED")
check("passages complets à zéro -> DEAD", h["dead"][0], "DEAD")
check("skip volontaire -> SKIPPED, jamais DEAD", h["skipped"][0], "SKIPPED")
check("aucun passage -> UNKNOWN", h["jamais"][0], "UNKNOWN")
check("une source ne disparaît jamais en silence", len(h), 7)

# ---------------------------------------------------------------------------
# Blocklist — un jugement humain que le moteur ne rediscute pas
# ---------------------------------------------------------------------------
import yaml as _y, discover as _d
_src = _y.safe_load(open("/Users/ju/Draft Class/wemby-hunt/sources.yaml", encoding="utf-8"))
_bl = hunt.load_blocklist(_src)

check("la blocklist est chargée", len(_bl), 2)
check("chaque entrée porte un motif ET sa date",
      all("[preuve du 2026-" in v for v in _bl.values()))
check("le domaine dissous est bloqué", bool(hunt.blocklisted("https://toyboxbarnsleymarket.co.uk")))
check("le storefront de 4 jours est bloqué", bool(hunt.blocklisted("https://jojosbazar.shop")))
check("le www. ne contourne pas la blocklist", bool(hunt.blocklisted("https://www.jojosbazar.shop")))
check("un sous-domaine non plus", bool(hunt.blocklisted("https://shop.jojosbazar.shop/products/x")))
check("une boutique légitime n'est pas bloquée", hunt.blocklisted("https://ehcards.com"), None)
check("un domaine qui CONTIENT le nom bloqué ne l'est pas",
      hunt.blocklisted("https://notjojosbazar.shop"), None)
check("le motif est restitué, pas seulement le rejet",
      "Companies House" in hunt.blocklisted("https://toyboxbarnsleymarket.co.uk"))

# discover : rejet AVANT le sondage — on ne dépense pas une requête sur un domaine jugé
_bd = _d.blocklist_of(_src)
check("discover partage la même blocklist", sorted(_bd), sorted(_bl))
check("discover rejette le domaine bloqué",
      (_d.is_excluded("jojosbazar.shop", set(), _bd) or "").startswith("BLOCKLIST"))
check("et le motif voyage avec le rejet",
      "Giant Sports Cards" in _d.is_excluded("jojosbazar.shop", set(), _bd))
check("discover laisse passer un inconnu légitime",
      _d.is_excluded("uneboutiqueinconnue.fr", set(), _bd), None)
check("la blocklist prime sur « déjà connu »",
      (_d.is_excluded("jojosbazar.shop", {"jojosbazar.shop"}, _bd) or "").startswith("BLOCKLIST"))

# les trois sources FR du 04/09 : déclarées, datées, non crawlées
_by = {x["key"]: x for x in _src["shops"]}
for _k in ("ludotrotter", "hikarudistribution", "mafiosicards"):
    check(f"source FR déclarée : {_k}", _by[_k]["type"], "eu_reference")
    check(f"{_k} porte sa date de vérification", bool(_by[_k].get("legitimacy_checked_at")))
    check(f"{_k} est en région FR", _by[_k]["market_region"], "FR")
check("le breaker concurrent est signalé comme tel", _by["mafiosicards"]["competitor_breaker"], True)
check("aucune des trois n'est crawlable en l'état",
      [k for k in ("ludotrotter", "hikarudistribution", "mafiosicards") if _by[k]["type"] != "eu_reference"], [])

# ---------------------------------------------------------------------------
# Annuaire Topps du 05/09 : ce qu'il a corrigé dans nos propres données
# ---------------------------------------------------------------------------
_q = _by["qscards"]
check("Q's Cards est déclarée néerlandaise", _q["country"], "NL")
check("la correction est datée", str(_q["country_corrected_at"]), "2026-09-05")
check("elle reste un canal d'achat en euros", _q["currency"], "EUR")
check("ludotrotter est marquée revendeur Topps agréé", _by["ludotrotter"]["official_topps_retailer"], True)
# garde-fou : aucune source ne peut prétendre être en France sans l'être
check("toute source déclarée country FR l'est vraiment",
      [x["key"] for x in _src["shops"]
       if x.get("country") == "FR" and "+31" in str(x.get("notes", ""))], [])

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
