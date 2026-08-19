"""Q — hygiène des seuils. Le moteur signale qu'un seuil a vieilli, il ne le recalcule jamais."""
import sys
sys.path.insert(0, "/Users/ju/Draft Class/wemby-hunt")
import yaml, hunt

fails, total = [], []
def check(n, got, want=True):
    total.append(n); ok = got == want
    if not ok: fails.append((n, got, want))
    print(f"{'PASS' if ok else 'FAIL'} {n:<58} got={got!r}")

TODAY = "2026-08-20"
recent = {"buy_below_usd": 30, "watch_below_usd": 40, "thresholds_reviewed_at": "2026-08-17"}
old    = {"buy_below_usd": 30, "watch_below_usd": 40, "thresholds_reviewed_at": "2026-06-01"}
never  = {"buy_below_usd": 30, "watch_below_usd": 40}
none   = {"buy_below_usd": None, "watch_below_usd": None}

check("seuil revu il y a 3 jours -> non STALE", hunt.threshold_age(recent, TODAY), (3, False))
check("seuil revu il y a 80 jours -> STALE", hunt.threshold_age(old, TODAY)[1], True)
check("seuil jamais revu -> STALE (conservateur)", hunt.threshold_age(never, TODAY), (None, True))
check("SKU sans seuil -> rien à signaler", hunt.threshold_age(none, TODAY), (None, False))
check("frontière : 30 jours exactement n'est pas encore STALE",
      hunt.threshold_age({"buy_below_usd": 1, "thresholds_reviewed_at": "2026-07-21"}, TODAY)[1], False)
check("31 jours -> STALE",
      hunt.threshold_age({"buy_below_usd": 1, "thresholds_reviewed_at": "2026-07-20"}, TODAY)[1], True)
check("le seuil documenté vaut 30 jours", hunt.STALE_THRESHOLD_DAYS, 30)

# aucun recalcul automatique : la valeur du seuil est inchangée après appel
before = dict(old)
hunt.threshold_age(old, TODAY)
check("threshold_age ne modifie jamais les seuils", old == before)

cat = yaml.safe_load(open("/Users/ju/Draft Class/wemby-hunt/catalog.yaml", encoding="utf-8"))
withth = [s for s in cat["skus"] if s.get("buy_below_usd") is not None]
check("tout SKU à seuil porte une date de revue",
      all(s.get("thresholds_reviewed_at") for s in withth))

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
