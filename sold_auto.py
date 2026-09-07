#!/usr/bin/env python3
"""SOLD — le marché des ventes RÉALISÉES, recalculé à chaque passage.

CE QUI CHANGE PAR RAPPORT AU FICHIER ÉCRIT À LA MAIN
----------------------------------------------------
`sold_prizm.json` contenait des agrégats saisis à la main : une moyenne, un n, une date de
relevé. On ne pouvait rien en refaire — ni recalculer une fenêtre, ni écarter une vente
douteuse, ni voir vieillir la donnée. Un agrégat est un cul-de-sac.

Ici, l'unité de base est LA TRANSACTION : une vente, une date, un prix, une source, une URL.
Le registre `sold_ledger.json` les conserve toutes, et `sold_prizm.json` devient une SORTIE
CALCULÉE, régénérée à chaque passage. Personne ne l'édite plus.

LA DISTINCTION QUE CE MODULE NE LAISSERA JAMAIS S'EFFACER
---------------------------------------------------------
Un prix DEMANDÉ n'est pas un prix OBTENU. Aucune annonce, aucun `external_prizm.json`, aucun
catalogue marchand n'entre ici : ce fichier ne contient que des transactions conclues. C'est
la règle qui empêche le moteur de mesurer le marché avec les espoirs des vendeurs.

Et LAST_SALE n'est jamais une médiane. C'est un point, souvent le plus bruyant de la série :
une Mega vendue 350 $ quand la moyenne trimestrielle est à 199 $. Il s'affiche, il ne sert
jamais de référence de valorisation.

D'OÙ VIENNENT LES TRANSACTIONS
------------------------------
Les fournisseurs automatiques (PriceCharting, eBay Marketplace Insights) sont écrits et
appelés à chaque passage ; ils s'activent dès qu'une clé est présente dans l'environnement.
Sans clé, ils déclarent SANS_CLÉ dans le rapport — jamais un zéro silencieux. Les deux sites
refusent toute lecture non authentifiée (403 sur le HTML, 400 « Must provide an access token »
sur l'API) et cette protection ne se contourne pas.

Les relevés déjà faits à la main restent une entrée valide : ingérés une fois, ils deviennent
des transactions datées et se recalculent tout seuls ensuite.
"""
from __future__ import annotations
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "discovered"
LEDGER = OUT / "sold_ledger.json"
STATS = OUT / "sold_prizm.json"

TX_FIELDS = ("sold_date", "sold_price", "currency", "source", "url", "format",
             "variant", "condition", "confidence")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sold_confidence(n: int) -> str:
    """L'échelle validée. Elle ne se négocie pas au cas par cas : une médiane sur deux ventes
    reste une médiane sur deux ventes, quel que soit l'enthousiasme du moment."""
    if n >= 10:
        return "HIGH"
    if n >= 3:
        return "MEDIUM"
    if n >= 1:
        return "LOW"
    return "NONE"


def aggregate(transactions: list[dict], today: date | None = None) -> dict:
    """Les statistiques d'un format, calculées depuis ses transactions.

    Une vente sans date ne peut entrer dans aucune fenêtre : on la conserve au registre, on ne
    la compte pas. Lui attribuer la date du jour la ferait peser sur MEDIAN_30D alors que
    personne ne sait quand elle a eu lieu.
    """
    today = today or date.today()
    dated = []
    for t in transactions:
        if not t.get("sold_date") or t.get("sold_price") is None:
            continue
        try:
            dated.append((date.fromisoformat(t["sold_date"]), float(t["sold_price"])))
        except (ValueError, TypeError):
            continue
    dated.sort()
    w30 = [p for d, p in dated if d >= today - timedelta(days=30)]
    w90 = [p for d, p in dated if d >= today - timedelta(days=90)]
    return {
        # LAST_SALE est un POINT, pas une référence. Il est nommé ainsi pour qu'aucun appelant
        # ne puisse le confondre avec une médiane par distraction.
        "LAST_SALE": round(dated[-1][1], 2) if dated else None,
        "LAST_SALE_DATE": dated[-1][0].isoformat() if dated else None,
        "MEDIAN_30D": round(statistics.median(w30), 2) if w30 else None,
        "MEDIAN_90D": round(statistics.median(w90), 2) if w90 else None,
        "AVG_90D": round(statistics.fmean(w90), 2) if w90 else None,
        "N_30D": len(w30),
        "N_90D": len(w90),
        "LOW_90D": round(min(w90), 2) if w90 else None,
        "HIGH_90D": round(max(w90), 2) if w90 else None,
        "SOLD_CONFIDENCE": sold_confidence(len(w90)),
        "N_TOTAL": len(transactions),
        "N_UNDATED": sum(1 for t in transactions if not t.get("sold_date")),
        "COMPUTED_FROM": "transactions",
    }


def from_aggregate_report(rep: dict) -> dict:
    """Repli sur un relevé agrégé, quand aucune transaction n'existe pour ce format.

    Un relevé agrégé est une capture : « moyenne 3 mois 2 818 $, 19 ventes, StockX, le 06/09 ».
    On peut l'afficher, on ne peut pas le recalculer. Il est donc rendu tel quel, avec sa
    provenance et son âge, et surtout `COMPUTED_FROM: aggregate_report` — pour qu'aucune
    lecture ne le prenne pour une médiane que nous aurions établie.
    """
    n = rep.get("N_90D") or 0
    return {"LAST_SALE": rep.get("LAST_SALE"), "LAST_SALE_DATE": None,
            "MEDIAN_30D": rep.get("MEDIAN_30D"), "MEDIAN_90D": rep.get("MEDIAN_90D"),
            "AVG_90D": rep.get("AVG_90D"), "N_30D": rep.get("N_30D") or 0, "N_90D": n,
            "LOW_90D": (rep.get("RANGE_90D") or [None, None])[0],
            "HIGH_90D": (rep.get("RANGE_90D") or [None, None])[1],
            "SOLD_CONFIDENCE": rep.get("CONFIDENCE") or sold_confidence(n),
            "N_TOTAL": n, "N_UNDATED": None,
            "COMPUTED_FROM": "aggregate_report",
            "SOURCE": rep.get("SOURCE"), "URL": rep.get("URL"),
            "FETCHED_AT": rep.get("FETCHED_AT"), "METHOD": rep.get("METHOD")}


# ---------------------------------------------------------------- fournisseurs automatiques
def _get(url, headers=None, timeout=25):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.load(r)


def provider_pricecharting(formats: dict, log=print):
    """PriceCharting / SportsCardsPro — l'historique des ventes réalisées, par produit.

    L'endpoint répond `{"error":"Must provide an access token"}` avec un code 400, pas 403 :
    il existe, il est documenté, il attend une clé. Poser `PRICECHARTING_TOKEN` dans les
    secrets du dépôt suffit à ouvrir ce canal pour les 307 SKU, sans rien changer d'autre.
    """
    token = os.environ.get("PRICECHARTING_TOKEN")
    if not token:
        return [], {"provider": "pricecharting", "outcome": "SANS_CLÉ",
                    "why": "PRICECHARTING_TOKEN absent de l'environnement"}
    tx, erreurs = [], []
    for fmt in formats:
        q = f"2023-24 Panini Prizm Basketball {fmt} Box"
        try:
            data = _get("https://www.pricecharting.com/api/product?t="
                        + urllib.parse.quote(token) + "&q=" + urllib.parse.quote(q))
        except Exception as e:
            erreurs.append(f"{fmt}: {e.__class__.__name__}")
            continue
        for s in (data.get("sales") or []):
            price = s.get("price")
            if price is None:
                continue
            tx.append({"sold_date": s.get("date"), "sold_price": round(float(price) / 100, 2),
                       "currency": "USD", "source": "pricecharting",
                       "url": data.get("url"), "format": fmt,
                       "variant": data.get("product-name"), "condition": s.get("condition") or "sealed",
                       "confidence": "HIGH", "ingested_at": now_iso()})
    return tx, {"provider": "pricecharting", "outcome": "OK" if tx else "VIDE",
                "n": len(tx), "erreurs": erreurs}


def provider_ebay_insights(formats: dict, log=print):
    """eBay Marketplace Insights — les ventes conclues des 90 derniers jours.

    C'est la seule API eBay qui rende des transactions ; la Browse API ne rend que des
    annonces, donc des prix DEMANDÉS, qui n'ont rien à faire ici. L'accès est soumis à
    approbation ; le jeton se pose dans `EBAY_OAUTH_TOKEN`.
    """
    token = os.environ.get("EBAY_OAUTH_TOKEN")
    if not token:
        return [], {"provider": "ebay_marketplace_insights", "outcome": "SANS_CLÉ",
                    "why": "EBAY_OAUTH_TOKEN absent de l'environnement"}
    tx, erreurs = [], []
    hdr = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    for fmt in formats:
        q = f"2023-24 Panini Prizm Basketball {fmt} Box"
        url = ("https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"
               "?limit=100&q=" + urllib.parse.quote(q))
        try:
            data = _get(url, hdr)
        except Exception as e:
            erreurs.append(f"{fmt}: {e.__class__.__name__}")
            continue
        for it in (data.get("itemSales") or []):
            px = (it.get("lastSoldPrice") or {})
            if px.get("value") is None:
                continue
            d = (it.get("lastSoldDate") or "")[:10]
            tx.append({"sold_date": d or None, "sold_price": float(px["value"]),
                       "currency": px.get("currency", "USD"), "source": "ebay_marketplace_insights",
                       "url": it.get("itemWebUrl"), "format": fmt,
                       "variant": it.get("title"), "condition": it.get("condition") or "sealed",
                       "confidence": "HIGH", "ingested_at": now_iso()})
    return tx, {"provider": "ebay_marketplace_insights", "outcome": "OK" if tx else "VIDE",
                "n": len(tx), "erreurs": erreurs}


PROVIDERS = (provider_pricecharting, provider_ebay_insights)


def tx_key(t: dict) -> tuple:
    """Deux fournisseurs peuvent rapporter la même vente. La clé qui l'identifie est
    date + prix + format : l'URL change d'un agrégateur à l'autre, la vente non."""
    return (t.get("sold_date"), round(float(t.get("sold_price") or 0), 2), t.get("format"))


# ---------------------------------------------------------------- registre
def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"generated_at": None, "transactions": [], "aggregate_reports": {}}


def migrate_legacy(ledger: dict, stats_path: Path = STATS) -> int:
    """Reprend l'ancien `sold_prizm.json` écrit à la main.

    Les agrégats y sont conservés COMME agrégats. On n'en fabrique pas de fausses transactions :
    « moyenne 2 818 $ sur 19 ventes » ne se déplie pas en dix-neuf lignes datées sans inventer
    dix-neuf dates et dix-neuf prix. Un chiffre qu'on ne peut pas décomposer se cite, il ne se
    simule pas.
    """
    if not stats_path.exists():
        return 0
    old = json.loads(stats_path.read_text(encoding="utf-8"))
    if old.get("computed_by") == "sold_auto":
        return 0
    n = 0
    for fmt, rec in (old.get("records") or {}).items():
        if rec.get("retracted"):
            continue
        ledger.setdefault("aggregate_reports", {})[fmt] = {
            k: rec.get(k) for k in ("LAST_SALE", "MEDIAN_30D", "MEDIAN_90D", "AVG_90D",
                                    "N_30D", "N_90D", "RANGE_90D", "SOURCE", "URL",
                                    "METHOD", "FETCHED_AT", "CONFIDENCE")}
        n += 1
    return n


def ingest(ledger: dict, new_tx: list[dict]) -> int:
    """Ajoute des transactions sans jamais en dupliquer une."""
    vus = {tx_key(t) for t in ledger["transactions"]}
    ajout = 0
    for t in new_tx:
        k = tx_key(t)
        if k in vus:
            continue
        vus.add(k)
        ledger["transactions"].append(t)
        ajout += 1
    return ajout


def ingest_pasted(ledger: dict, text: str, fmt: str, source: str, url: str | None = None) -> tuple[int, list]:
    """Un tableau collé devient des transactions PERMANENTES.

    Le canal manuel ne disparaît pas — il cesse d'être un cul-de-sac. Une ligne collée une fois
    est datée, filtrée par les exclusions du moteur de ventes (lot, case, pack, FOTL, exemplaire
    abîmé, autre saison) et conservée : elle se recalculera toute seule ensuite.
    """
    import sold_engine
    kept, dropped = sold_engine.parse_pasted(text, season="2023-24")
    tx = [{"sold_date": k["date"], "sold_price": k["price"], "currency": "USD",
           "source": source, "url": url, "format": fmt, "variant": k.get("title"),
           "condition": "sealed", "confidence": "HIGH", "ingested_at": now_iso()} for k in kept]
    return ingest(ledger, tx), dropped


def main(argv=None):
    import prizm_core
    OUT.mkdir(exist_ok=True)
    argv = list(argv if argv is not None else sys.argv[1:])
    ledger = load_ledger()
    ledger.setdefault("transactions", [])
    n_mig = migrate_legacy(ledger)

    print("SOLD — ventes réalisées\n")
    if "--ingest" in argv:
        i = argv.index("--ingest")
        chemin, fmt = argv[i + 1], argv[i + 2]
        n, rejets = ingest_pasted(ledger, Path(chemin).read_text(encoding="utf-8"), fmt,
                                  source="relevé collé")
        print(f"  ingestion {chemin} → {fmt} : {n} transaction(s), {len(rejets)} rejet(s)")
        for r in rejets[:8]:
            print(f"      écarté [{r['excluded']}] {r['title'][:70]}")
    avant = len(ledger["transactions"])
    attempts = []
    for prov in PROVIDERS:
        tx, info = prov(prizm_core.FORMATS)
        attempts.append(info)
        n = ingest(ledger, tx)
        info["ingérées"] = n
        print(f"  {info['provider']:<32} {info['outcome']:<10} "
              f"{info.get('n', 0):>4} vue(s) · {n:>3} nouvelle(s)  {info.get('why', '')}")
    ajoutees = len(ledger["transactions"]) - avant

    ledger["generated_at"] = now_iso()
    ledger["note"] = ("Transactions individuelles. Ce registre est la SOURCE ; sold_prizm.json "
                      "en est la sortie calculée. Aucun prix demandé n'entre ici.")
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    par_format: dict[str, list[dict]] = {}
    for t in ledger["transactions"]:
        par_format.setdefault(t.get("format") or "Inconnu", []).append(t)

    records, reports = {}, ledger.get("aggregate_reports", {})
    for fmt in prizm_core.FORMATS:
        tx = par_format.get(fmt, [])
        calcule = aggregate(tx) if tx else None
        releve = from_aggregate_report(reports[fmt]) if fmt in reports else None
        # On garde la base la MIEUX fondée, pas la plus récente ni la plus élégante. Une
        # médiane calculée sur une vente ne remplace pas un relevé qui en portait trois :
        # préférer le calculé par principe reviendrait à perdre de l'information au nom
        # de la méthode. Le relevé conservé dit d'où il vient et qu'il n'est pas recalculable.
        if calcule and releve:
            records[fmt] = calcule if calcule["N_90D"] >= (releve["N_90D"] or 0) else {
                **releve, "N_TRANSACTIONS_CONNUES": calcule["N_TOTAL"],
                "NOTE": "relevé agrégé conservé : il repose sur plus de ventes que nos transactions datées"}
        elif calcule:
            records[fmt] = calcule
        elif releve:
            records[fmt] = releve
    for fmt, tx in par_format.items():
        if fmt not in records:
            records[fmt] = aggregate(tx)

    payload = {"generated_at": now_iso(),
               "computed_by": "sold_auto",
               "note": ("Sortie CALCULÉE à chaque passage depuis sold_ledger.json. Ne pas éditer "
                        "à la main : la prochaine exécution écrase le fichier. LAST_SALE est un "
                        "point de la série, jamais une médiane ni une référence de valorisation."),
               "confidence_scale": "HIGH n>=10 · MEDIUM n 3-9 · LOW n 1-2 · NONE n=0 (fenêtre 90 j)",
               "providers": attempts,
               "n_transactions": len(ledger["transactions"]),
               "records": records}
    STATS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    calc = sum(1 for r in records.values() if r["COMPUTED_FROM"] == "transactions")
    print(f"\n{len(ledger['transactions'])} transaction(s) au registre "
          f"({ajoutees} ajoutée(s) ce passage · {n_mig} relevé(s) agrégé(s) repris)")
    print(f"{len(records)} format(s) chiffré(s) — {calc} depuis des transactions, "
          f"{len(records) - calc} depuis un relevé agrégé → {STATS}")
    return payload


if __name__ == "__main__":
    main()
