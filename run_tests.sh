#!/usr/bin/env bash
# Lance toutes les suites et échoue si l'une échoue. À utiliser avant chaque commit :
# un `for … done; echo OK` masque les échecs, vécu le 20/08 sur tests_ui.
set -uo pipefail
fail=0
for t in tests_matching tests_robustness tests_badges tests_ui tests_history tests_health tests_thresholds tests_cockpit tests_fr; do
  out=$(./.venv/bin/python "$t.py" 2>&1 | grep -v "NotOpenSSL\|warnings.warn" | tail -1)
  code=${PIPESTATUS[0]}
  printf "%-20s %s\n" "$t" "$out"
  [ "$code" -ne 0 ] && fail=1
done
[ "$fail" -eq 0 ] && echo "TOUTES LES SUITES VERTES" || { echo "ÉCHEC : au moins une suite est rouge"; exit 1; }
