"""Current Market — la valeur d'aujourd'hui, distincte du plus-bas historique."""
import sys, tempfile, pathlib, yaml
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<60} got={got!r}")

NOW = "2026-08-23T00:00:00"
hunt.DB = pathlib.Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
c = hunt.db()
def obs(key, price, days, shop="sh", region="US", sealed=1, avail=1):
    from datetime import datetime, timedelta
    sa = (datetime.fromisoformat(NOW) - timedelta(days=days)).isoformat()
    c.execute("INSERT INTO observations (sku_id,shop,title,variant_title,price,available,url,"
              "match_score,seen_at,exact_comp_key,sealed,quantity,unit_price,market_region) "
              "VALUES ('S',?,'t','',?,?,?,1.0,?,?,?,1,?,?)",
              (shop, price, avail, f"u{price}{shop}{days}", sa, key, sealed, price, region))

# TEST A — marché montant : le vieux plus-bas ne pilote plus
K = "A|std|x1"
obs(K, 25.0, 500, "vieux")
for i, p in enumerate([99, 101, 103, 105, 108]): obs(K, p, 5 + i, f"s{i}")
c.commit()
cm = hunt.current_market(c, {}, K, NOW)
check("A · le marché actuel se cale sur le cluster récent, pas sur le 25 $",
      95 <= (cm["value"] or 0) <= 110)
check("A · le 25 $ vieux de 500 j est hors fenêtre", 25.0 not in [cm["value"]])
hl = hunt.historical_low(c, K)
check("A · le plus-bas historique est CONSERVÉ", hl["low"], 25.0)
check("A · et il est marqué STALE", hunt.freshness(500), "STALE")
check("A · une offre à 75 $ est sous le marché actuel", 75.0 < cm["value"])

# TEST F — outlier dans la fenêtre récente
K2 = "F|std|x1"
for i, p in enumerate([25, 99, 101, 103, 105]): obs(K2, p, 3 + i, f"f{i}")
c.commit()
cm2 = hunt.current_market(c, {}, K2, NOW)
check("F · l'aberration à 25 $ est écartée", 25.0 in cm2["outliers"])
check("F · la cote reste sur le cluster", 95 <= cm2["value"] <= 110)

# une observation du JOUR MÊME doit compter (age 0 est falsy en Python)
K0 = "TODAY|std|x1"; obs(K0, 75.0, 0, "hiddengems"); c.commit()
cm0 = hunt.current_market(c, {}, K0, NOW)
check("une observation du jour même n'est pas traitée comme vieille", cm0["value"], 75.0)
check("son âge est bien 0", cm0["age_days"], 0)

# TEST E — échantillon faible
K3 = "E|std|x1"; obs(K3, 100.0, 2, "solo"); c.commit()
check("E · une seule boutique -> confiance faible", hunt.current_market(c, {}, K3, NOW)["confidence"], "LOW")

# TEST J — aucune donnée exploitable
check("J · rien d'exploitable -> valeur UNKNOWN", hunt.current_market(c, {}, "VIDE|std|x1", NOW)["value"], None)

# TEST H/I — fraîcheur
K4 = "H|std|x1"; obs(K4, 100.0, 400, "vieux"); c.commit()
check("H · une donnée trop vieille ne fait pas un marché", hunt.current_market(c, {}, K4, NOW)["value"], None)
check("I · une donnée récente est FRESH", hunt.freshness(5), "FRESH")
check("fraîcheur intermédiaire", hunt.freshness(60), "AGING")

# TEST K — cloisonnement régional
K5 = "K|std|x1"
for i, p in enumerate([100, 102, 104]): obs(K5, p, 2 + i, f"us{i}", region="US")
for i, p in enumerate([40, 41, 42]): obs(K5, p, 2 + i, f"fr{i}", region="FR")
c.commit()
us = hunt.current_market(c, {}, K5, NOW, region="US")
check("K · une observation FR ne modifie pas le marché US", 99 <= us["value"] <= 105)
check("K · le marché FR se calcule séparément",
      39 <= hunt.current_market(c, {}, K5, NOW, region="FR")["value"] <= 43)

# TEST G — quantité : la cloison sépare déjà x1 et xN
K6 = "G|std|x6"; obs(K6, 600.0, 2, "lot"); c.commit()
check("G · un lot x6 n'entre pas dans le marché x1",
      hunt.current_market(c, {}, "G|std|x1", NOW)["value"], None)

# sold exact prioritaire sur les asks
sold_sku = {"market_sold_us": 106.0, "market_sold_n": 8, "market_sold_window_days": 30,
            "market_sold_checked_at": "2026-08-20"}
cmS = hunt.current_market(c, sold_sku, K, NOW)
check("SOLD > ASK : un sold fiable prime", cmS["basis"], "exact_sold")
check("SOLD : n=8 sur 30 j -> confiance HIGH", cmS["confidence"], "HIGH")
check("un sold LOW ne prime pas sur les asks",
      hunt.current_market(c, {"market_sold_us": 1.0, "market_sold_n": 1,
                              "market_sold_window_days": 400}, K, NOW)["basis"], "observed_ask")

# TEST M/N — la fiche réelle Hidden Gems
skus = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))["skus"]
m = hunt.match_title("2023-24 Topps Chrome NBA Basketball Value Box SEALED", skus)
check("M · la fiche Hidden Gems matche enfin la bonne SKU",
      m.sku_id, "TOPPS_2023-24_CHROME_VALUE_BLASTER")
check("M · SEALED est un état, pas une édition", hunt.sealed_product(
      hunt.norm("2023-24 Topps Chrome NBA Basketball Value Box SEALED")), True)
for t, why in [("2023-24 Topps Chrome Basketball Hobby Box", "Hobby"),
               ("2023-24 Topps Chrome Basketball BLASTER PACK", "pack"),
               ("2023-24 Topps Chrome Basketball Blaster 40-Box Case", "case"),
               ("2023-24 Topps Chrome UEFA Women's Champions League Value Box", "soccer")]:
    got = hunt.match_title(t, skus).sku_id
    check(f"N · Value Box ≠ {why}", got != "TOPPS_2023-24_CHROME_VALUE_BLASTER")

# ================= PR B : sold réels, buy_below_v2, marché baissier
NOW2 = "2026-08-23"
K_TC = "TOPPS_2023-24_CHROME_VALUE_BLASTER|std|x1"
st = hunt.sold_stats(K_TC, NOW2)
check("le jeu de ventes réelles est chargé", st is not None)
check("fenêtre 30 j : 7 ventes", st["windows"][30]["n"], 7)
check("médiane 30 j", st["windows"][30]["median"], 64.0)
check("médiane 60 j supérieure à la 30 j (le marché redescend)",
      st["windows"][60]["median"] > st["windows"][30]["median"])
check("tendance constatée DOWN", st["trend"], "DOWN")
check("source conservée", st["source"], "sportscardspro")
check("confiance HIGH sur 7 ventes récentes peu dispersées", st["confidence"], "HIGH")

cmTC = hunt.current_market(c, {}, K_TC, NOW2)
check("les ventes réelles priment sur les asks observés", cmTC["basis"], "exact_sold")
bb, _ = hunt.buy_below_v2(cmTC)
check("buy_below_v2 dérive du marché actuel", bb, 57.6)
check("buy_below_v2 est très au-dessus du seuil manuel de 35 $", bb > 35.0)
check("sans marché fiable, aucun seuil n'est fabriqué",
      hunt.buy_below_v2({"value": None})[0], None)
check("confiance faible -> pas de seuil",
      hunt.buy_below_v2({"value": 100, "confidence": "LOW"})[0], None)

skTC = {"buy_below_usd": 35.0}
flag = hunt.threshold_vs_market(skTC, cmTC)
check("le seuil manuel obsolète est signalé", flag[0], "OBSOLETE_LOW")
check("un seuil au-dessus du marché est signalé aussi",
      hunt.threshold_vs_market({"buy_below_usd": 90.0}, cmTC)[0], "OBSOLETE_HIGH")
check("un seuil cohérent n'est pas signalé",
      hunt.threshold_vs_market({"buy_below_usd": 58.0}, cmTC), None)

# TEST B — marché stable · TEST C — marché baissier
def verdict(offer, ref):
    g = (offer - ref) / ref * 100
    return "STRONG DEAL" if g <= -20 else "DEAL" if g <= -10 else "FAIR" if g <= 10 else "CHER"
check("B · marché stable : 90 face à 100 -> DEAL", verdict(90, 100), "DEAL")
check("C · marché baissier : offre 110 face à un sold récent de 80 -> aucun deal",
      verdict(110, 80), "CHER")
check("C · un ancien ask élevé ne sauve pas l'offre", verdict(110, 80) != "DEAL")
check("le cas réel : 75 $ face à un marché à 64 $ n'est pas un deal", verdict(75, 64), "CHER")
check("à 55 $ ce serait un deal", verdict(55, 64), "DEAL")
check("à 50 $ un strong deal", verdict(50, 64), "STRONG DEAL")

# ---------------------------------------------------------------------------
# HOT NOW : un verdict de marché défavorable est sans appel
# ---------------------------------------------------------------------------
def hn_entry(sid, price, pv, triggers=("RESTOCK",), gap=-38.0, ref=120.0, kind="ask"):
    o = ("S", "sh", "titre", price, 1, f"https://x.test/{sid}", 1.0,
         "2026-08-21T00:00:00", "", "EXACT", None, 1, price, f"{sid}|std|x1", "US", "USD")
    return {"o": o, "key": f"{sid}|std|x1", "sid": sid, "sku": {}, "available": True,
            "triggers": list(triggers), "descriptors": [], "gap": gap, "ref": ref,
            "kind": kind, "mem": None, "comp": "EXACT", "hist": None, "region": "US", "pv": pv}

def pvd(v, basis="sold", gap=0.0):
    return {"verdict": v, "basis": basis, "gap": gap, "ref": {"value": 64.0},
            "confidence": "HIGH", "why": "preuve"}

# le cas réel : Topps Chrome à 75 $, restock + plus-bas historique + -38 % vs seuil manuel,
# mais sept ventes réelles à 64 $. L'ancien moteur l'affichait en HOT NOW.
cher = hn_entry("TOPPS_CHROME", 75.0, pvd("EXPENSIVE", "sold", 17.2))
check("un EXPENSIVE sold-backed n'entre pas dans HOT NOW malgré ses déclencheurs",
      hunt.hot_now([cher]), [])
check("un ASK EXPENSIVE non plus",
      hunt.hot_now([hn_entry("X", 75.0, pvd("ASK EXPENSIVE", "ask", 30.0))]), [])
check("un ASK FAIR non plus",
      hunt.hot_now([hn_entry("X", 75.0, pvd("ASK FAIR", "ask", 2.0))]), [])
check("sans aucune preuve de marché, les déclencheurs historiques restent recevables",
      len(hunt.hot_now([hn_entry("X", 39.99, pvd("DATA INSUFFICIENT", None, None))])), 1)
check("un ASK DEAL entre dans HOT NOW sans aucun déclencheur historique",
      len(hunt.hot_now([hn_entry("X", 10.0, pvd("ASK DEAL", "ask", -33.7),
                                 triggers=(), gap=None, ref=None)])), 1)
check("un BUY sold-backed passe devant un ASK DEAL plus généreux",
      [e["sid"] for e in hunt.hot_now([
          hn_entry("ASKD", 10.0, pvd("ASK DEAL", "ask", -33.7), triggers=(), gap=None, ref=None),
          hn_entry("SOLDB", 50.0, pvd("BUY", "sold", -12.0), triggers=(), gap=None, ref=None)])],
      ["SOLDB", "ASKD"])
# l'écart affiché : celui du verdict quand il existe, jamais un plantage quand il manque
check("un ASK DEAL sans gap historique ne fait pas planter le rapport",
      hunt.hot_now([hn_entry("X", 10.0, pvd("ASK DEAL", "ask", -33.7),
                             triggers=(), gap=None, ref=None)])[0]["gap"], None)

# ---------------------------------------------------------------------------
# L'objectif de prix suit le marché, pas le seuil manuel
# ---------------------------------------------------------------------------
def op_for(price, pv, buy_below):
    e = hn_entry("X", price, pv, triggers=(), gap=None, ref=None)
    e["sku"] = {"id": "X", "buy_below_usd": buy_below, "tier": "retail", "season": "2023-24",
                "manufacturer": "Topps", "set": "Topps Chrome", "format": "Blaster"}
    import yaml, pathlib as _pl
    _cat = yaml.safe_load((_pl.Path(__file__).parent / "catalog.yaml").read_text(encoding="utf-8"))
    return hunt.opportunity(e, "buy", _cat)

# le cas réel : Topps Chrome à 75 $, seuil manuel 35 $, ventes réelles à 64 $.
# L'ancien « attendre 40 $ » visait le seuil manuel. Le marché justifie 57,60 $.
_pv = {"verdict": "EXPENSIVE", "basis": "sold", "gap": 17.2,
       "ref": {"value": 64.0}, "confidence": "HIGH", "why": "7 ventes"}
_o = op_for(75.0, _pv, 35.0)
check("l'objectif de prix dérive du marché, pas du seuil manuel", _o.buy_target_v2, 57.6)
check("ce qu'il reste à attendre se mesure sur cet objectif", round(_o.missing, 2), 17.4)
check("le seuil manuel reste affiché comme contexte", _o.buy_below, 35.0)
check("l'objectif porte sa justification", bool(_o.target_why))
check("un objectif adossé aux ventes le dit", "ventes récentes" in _o.target_why)
# écrire « ventes récentes » au-dessus d'un objectif calculé sur des prix demandés serait
# exactement la confusion que tout ce moteur existe pour empêcher.
_pva = {"verdict": "ASK DEAL", "basis": "ask", "gap": -33.7,
        "ref": {"value": 15.0}, "confidence": "HIGH", "why": "4 vendeurs"}
_oa = op_for(9.95, _pva, None)
check("un objectif adossé aux prix demandés ne parle jamais de ventes",
      "ventes" not in (op_for(20.0, _pva, None).target_why or ""))
check("il nomme les prix demandés",
      "prix demandés" in (op_for(20.0, _pva, None).target_why or ""))
check("l'objectif ask suit la même règle de marge", op_for(20.0, _pva, None).buy_target_v2, 13.5)
# confiance moyenne : marge exigée plus large
_pvm = dict(_pv, confidence="MEDIUM")
check("une confiance moyenne exige une marge plus large", op_for(75.0, _pvm, 35.0).buy_target_v2, 54.4)
# sans marché, on retombe sur le seuil manuel plutôt que de ne rien dire
_pvn = {"verdict": "DATA INSUFFICIENT", "basis": None, "gap": None, "ref": None,
        "confidence": None, "why": None}
_on = op_for(75.0, _pvn, 35.0)
check("sans marché, l'objectif retombe sur le seuil manuel", _on.buy_target_v2, None)
check("et l'attente se mesure alors sur ce seuil", _on.missing, 40.0)
check("sans seuil ni marché, aucune attente n'est affichée", op_for(75.0, _pvn, None).missing, None)

print(f"\nTOTAL FINAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
