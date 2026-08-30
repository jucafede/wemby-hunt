#!/usr/bin/env python3
"""Couche inventaire.

Le test qui compte est le dernier : les verdicts doivent être RIGOUREUSEMENT identiques avec
et sans inventory.yaml. Tant qu'il passe, l'inventaire ne peut pas s'être glissé dans une
décision de marché — et c'est la seule garantie qui empêche le radar de se recommander à
lui-même en prenant mon coût d'achat pour une référence de prix.
"""
import sys, io, contextlib, tempfile, pathlib, yaml
import hunt

total, fails = [], []
def check(name, got, exp=True):
    total.append(name)
    ok = (got == exp)
    if not ok: fails.append((name, got, exp))
    print(f"{'PASS' if ok else 'FAIL'} {name}")

CAT = yaml.safe_load((hunt.ROOT / "catalog.yaml").read_text(encoding="utf-8"))
IDS = {x["id"] for x in CAT["skus"]}

def tmp_yaml(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(text); f.close()
    return pathlib.Path(f.name)

# ---------------------------------------------------------------- lecture
inv = hunt.load_inventory()
check("inventory.yaml se lit", len(inv) > 0)
check("toutes les lignes portent un sku connu du catalogue",
      [l["sku"] for l in inv if l["sku"] not in IDS], [])
check("toutes les quantités sont strictement positives", all(l["qty"] > 0 for l in inv))
check("tous les coûts sont renseignés", all(l["unit_landed_eur"] > 0 for l in inv))

# fichier absent -> tout fonctionne comme avant
check("un fichier absent rend un inventaire vide, sans exception",
      hunt.load_inventory(pathlib.Path("/nonexistent/inventory.yaml")), [])
# fichier illisible -> idem, on ne fait pas tomber le radar pour un YAML cassé
bad = tmp_yaml("lines: [ this is not: valid: yaml:")
with contextlib.redirect_stdout(io.StringIO()):
    check("un fichier illisible rend un inventaire vide", hunt.load_inventory(bad), [])
# ligne invalide -> ignorée, les autres passent
part = tmp_yaml('lines:\n  - {sku: A, qty: 0, unit_landed_eur: 10}\n'
                '  - {sku: B, qty: 2, unit_landed_eur: 10}\n')
with contextlib.redirect_stdout(io.StringIO()):
    got = hunt.load_inventory(part)
check("une ligne invalide est écartée sans emporter les autres", [l["sku"] for l in got], ["B"])

# ---------------------------------------------------------------- agrégation
one = tmp_yaml(
    'lines:\n'
    '  - {sku: PANINI_2023-24_PHOENIX_BLASTER, qty: 3, unit_landed_eur: 60.00, status: received}\n'
    '  - {sku: PANINI_2023-24_PHOENIX_BLASTER, qty: 1, unit_landed_eur: 40.00, status: at_forwarder}\n'
    '  - {sku: PANINI_2023-24_PHOENIX_BLASTER, qty: 5, unit_landed_eur: 99.00, status: opened}\n'
    '  - {sku: PANINI_2023-24_PHOENIX_BLASTER, qty: 9, unit_landed_eur: 99.00, status: sold}\n'
    '  - {sku: SKU_QUI_NEXISTE_PAS, qty: 1, unit_landed_eur: 10.00, status: received}\n')
with contextlib.redirect_stdout(io.StringIO()):
    owned, unknown = hunt.inventory_by_sku(hunt.load_inventory(one), IDS)
a = owned["PANINI_2023-24_PHOENIX_BLASTER"]
check("seuls ordered / at_forwarder / received comptent comme scellé possédé", a["qty"], 4)
check("le coût unitaire est la moyenne PONDÉRÉE des lots", a["unit_landed_eur"], 55.0)
check("le coût total suit", a["cost"], 220.0)
check("une boîte ouverte ne compte plus dans le stock scellé", a["qty"] != 9)
check("un sku inconnu est signalé, jamais deviné", unknown, ["SKU_QUI_NEXISTE_PAS"])
check("et n'entre pas dans l'agrégat", "SKU_QUI_NEXISTE_PAS" not in owned)

# ---------------------------------------------------------------- badge sur les cartes
def entry(sid, price, avail=True):
    o = ("S", "sh", "titre", price, 1 if avail else 0, f"https://x.test/{sid}", 1.0,
         "2026-08-21T00:00:00", "", "EXACT", None, 1, price, f"{sid}|std|x1", "US", "USD")
    return {"o": o, "key": f"{sid}|std|x1", "sid": sid, "available": avail,
            "sku": next(x for x in CAT["skus"] if x["id"] == sid),
            "triggers": [], "descriptors": [], "gap": None, "ref": None, "kind": None,
            "mem": None, "comp": "EXACT", "hist": None, "region": "US", "currency": "USD",
            "pv": {"verdict": "ASK DEAL", "basis": "ask", "gap": -30.0, "ref": 50.0,
                   "confidence": "HIGH", "why": "4 vendeurs"}}

e = entry("PANINI_2023-24_PHOENIX_BLASTER", 35.0)
op_own = hunt.opportunity(e, "buy", CAT, None, owned)
op_bare = hunt.opportunity(e, "buy", CAT, None, {})
check("la carte porte la quantité possédée", op_own.owned_qty, 4)
check("et le coût unitaire payé", op_own.owned_landed_eur, 55.0)
check("sans inventaire, aucune quantité", op_bare.owned_qty, 0)
check("le badge est rendu quand il y a du stock", "📦 EN STOCK ×4" in hunt.render_card(op_own))
check("le coût payé apparaît dans le badge", "55.00 €/boîte payés" in hunt.render_card(op_own))
check("aucun badge sans stock", "EN STOCK ×" not in hunt.render_card(op_bare))

# INFORMATION, PAS BLOCAGE : la carte reste entière, verdict compris
check("le verdict de la carte possédée est inchangé", op_own.verdict, op_bare.verdict)
check("son écart marché aussi", op_own.market, op_bare.market)
check("sa preuve aussi", op_own.evidence, op_bare.evidence)
check("son objectif de prix aussi", op_own.buy_target_v2, op_bare.buy_target_v2)
check("une ligne possédée reste éligible à HOT NOW",
      len(hunt.hot_now([dict(e, pv=dict(e["pv"]))])), 1)

# ---------------------------------------------------------------- tableau
rows = hunt.inventory_rows(owned, [e], CAT)
r = rows[0]
check("une ligne par SKU possédé", len(rows), 1)
check("le tableau reprend la quantité", r["qty"], 4)
check("et le meilleur ask US en stock", r["best_ask_usd"], 35.0)
check("la référence vient du moteur, pas de l'inventaire", r["ref_usd"], 50.0)
check("l'écart est calculé", r["spread_pct"] is not None)
# un SKU possédé sans observation : « — », jamais une valeur inventée
rows_vides = hunt.inventory_rows(owned, [], CAT)
v = rows_vides[0]
check("sans observation, aucun ask", v["best_ask_usd"], None)
check("sans observation, aucune référence", v["ref_usd"], None)
check("sans observation, aucun écart inventé", v["spread_pct"], None)
check("mais la quantité et le coût restent connus", (v["qty"], v["unit_landed_eur"]), (4, 55.0))
# le marché FR prime : euro contre euro, sans conversion
fr = {"PANINI_2023-24_PHOENIX_BLASTER|std|x1": {"unit": 82.50, "shop": "tanteo"}}
rf = hunt.inventory_rows(owned, [e], CAT, fr)[0]
check("le marché FR prime pour l'écart", rf["spread_src"], "FR")
check("et se compare sans conversion", rf["spread_pct"], round((82.50 - 55.0) / 55.0 * 100, 1))
check("sans marché FR, on retombe sur l'ask US converti", r["spread_src"], "US")

# ---------------------------------------------------------------- NON-RÉGRESSION
# Le test qui compte. On rejoue la chaîne de décision complète, avec et sans inventaire, et on
# exige une égalité stricte. Si l'inventaire touchait un verdict, un écart ou un tri, ceci casse.
def empreinte(inv_path):
    vrai = hunt.load_inventory
    hunt.load_inventory = lambda p=None: vrai(inv_path)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hunt.report(CAT, hunt.db(), None,
                        {sh["key"]: sh.get("trust", "trusted")
                         for sh in yaml.safe_load((hunt.ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]})
        txt = buf.getvalue()
    finally:
        hunt.load_inventory = vrai
    # on retire les sections qui PARLENT d'inventaire : le reste doit être bit-à-bit identique
    return [l for l in txt.splitlines()
            if "inventory.yaml" not in l and "EN STOCK ×" not in l and not l.startswith("CSV →")
            and not l.startswith("HTML →")]

vide = tmp_yaml("lines: []\n")
sans = empreinte(vide)
avec = empreinte(hunt.ROOT / "inventory.yaml")
diff = [(a, b) for a, b in zip(sans, avec) if a != b]
check("le rapport est identique avec et sans inventaire (longueur)", len(sans), len(avec))
check("le rapport est identique avec et sans inventaire (contenu)", diff, [])
if diff:
    for a, b in diff[:5]: print(f"   sans: {a}\n   avec: {b}")

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
