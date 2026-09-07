#!/usr/bin/env bash
# Compare la PAGE PUBLIÉE aux fichiers que le run a produits.
# Écrit parce que « le code est corrigé » n'a jamais rien prouvé : seule l'URL publique compte.
set -uo pipefail
URL="https://jucafede.github.io/wemby-hunt/"
TMP=$(mktemp)
code=$(curl -s -o "$TMP" -w "%{http_code}" "$URL")
echo "GET $URL → $code · $(wc -c < "$TMP" | tr -d ' ') octets"
echo "gh-pages : $(gh api repos/jucafede/wemby-hunt/branches/gh-pages -q .commit.commit.committer.date 2>/dev/null)"
./.venv/bin/python - "$TMP" <<'PY'
import json, pathlib, re, sys
page = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
D = pathlib.Path("discovered")
ext = json.loads((D / "external_prizm.json").read_text(encoding="utf-8"))
core = json.loads((D / "prizm_core.json").read_text(encoding="utf-8"))
sold = json.loads((D / "sold_prizm.json").read_text(encoding="utf-8"))

seg = page[page.find("Prizm Wemby Core"):][:12000]
def cellules(ligne):
    return [re.sub(r"<[^>]+>", " ", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", ligne, re.S)]
lignes = [cellules(r) for r in re.findall(r"<tr>(.*?)</tr>", seg, re.S)]

print("\n-- horodatages annoncés par la page vs fichiers du run")
for nom, fic, ts in (("EXTERNAL WEB", "external_prizm.json", ext["generated_at"]),
                     ("REGISTERED SOURCES", "prizm_core.json", core["generated_at"]),
                     ("SOLD", "sold_prizm.json", sold["generated_at"])):
    attendu = str(ts)[:16].replace("T", " ")
    trouve = any(nom in (l[0] if l else "") and attendu in " ".join(l) for l in lignes)
    print(f"  {'✅' if trouve else '❌'} {nom:<20} {attendu}")

print("\n-- comptes de live par format : page vs fichiers")
import collections
compte = collections.Counter()
for r in ext["listings"]:
    if r["stock_status"] in ("CONFIRMED_LIVE", "PROBABLE_LIVE"):
        compte[r["format"]] += 1
for l in lignes:
    if len(l) >= 5 and l[1].isdigit() and l[2].isdigit():
        print(f"  {l[0]:<22} page live={l[2]:<3} stale={l[4]:<3} externes live={compte.get(l[0], 0)}")

print("\n-- la phrase retirée le 06/09 n'est pas revenue")
print(f"  {'✅' if 'cherché et rien trouvé' not in page else '❌'} "
      "« un zéro signifie cherché et rien trouvé » absente")
print(f"  {'✅' if 'STALE' in page else '❌'} la page explique l'état STALE")
PY
rm -f "$TMP"
