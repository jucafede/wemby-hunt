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

print(f"\nTOTAL : {len(total)} tests, {len(fails)} FAIL")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
