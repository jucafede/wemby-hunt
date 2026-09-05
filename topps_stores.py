#!/usr/bin/env python3
"""Annuaire des revendeurs Topps — normalisation et synthèse.

POURQUOI CE SCRIPT EXISTE PLUTÔT QU'UN CRAWLER
----------------------------------------------
fr.topps.com et www.topps.com refusent tout client automatisé derrière un blocage Cloudflare
« Attention Required! » — y compris /robots.txt, ce qui empêche même de lire leur politique de
collecte. Ce n'est pas un défi JavaScript qu'on pourrait attendre, c'est un refus au pare-feu,
avant qu'aucun script de store locator ne soit servi. Je ne contourne pas une protection
anti-robot : la récupération se fait donc à la main, depuis un navigateur, et ce script prend
le relais dès que le JSON est sous la main.

COMMENT RÉCUPÉRER LE DATASET (2 minutes, dans le navigateur)
-----------------------------------------------------------
  1. Ouvrir https://fr.topps.com/stores, F12 → onglet Réseau, filtre « Fetch/XHR ».
  2. Recharger. Chercher l'appel qui rend les points de vente. Les widgets courants :
        Storepoint   api.storepoint.co/v1/<clé>/locations
        Stockist     stockist.co/api/v1/<clé>/locations/search
        StoreRocket  storerocket.io/api/user/<clé>/locations
        Closeby      api.closeby.co/...
     Presque tous rendent TOUTES les locations en un seul appel, sans authentification.
  3. Clic droit sur la réponse → « Copier la réponse », coller dans un fichier .json.
  4. python topps_stores.py brut.json

Le script accepte n'importe laquelle de ces formes : {"results":[...]}, {"locations":[...]},
{"data":{"items":[...]}}, ou une liste nue. Il cherche la première liste d'objets qui
ressemble à des points de vente et normalise les champs.

SORTIE
------
  topps_stores.json  — name, address, city, postal_code, country, website, email, lat, lng
  + une synthèse : total mondial, comptes par pays, FR+BE par département,
    et les boutiques à moins de 50 km de Wasquehal.
"""
from __future__ import annotations
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "topps_stores.json"

# Wasquehal (59290). Sert au rayon de 50 km quand le dataset porte des coordonnées.
WASQUEHAL = (50.6738, 3.1291)
RAYON_KM = 50

# Les noms de champs varient d'un widget à l'autre ; on ratisse large plutôt que de coder
# un adaptateur par fournisseur pour un script qui tournera une poignée de fois.
CHAMPS = {
    "name":        ("name", "title", "storename", "store_name", "location_name", "company"),
    "address":     ("address", "address1", "street", "streetaddress", "addressline1", "adresse"),
    "city":        ("city", "town", "locality", "ville"),
    "postal_code": ("postal_code", "postalcode", "zip", "zipcode", "postcode", "cp"),
    "country":     ("country", "country_code", "countrycode", "pays"),
    "website":     ("website", "url", "web", "site", "link"),
    "email":       ("email", "mail", "e_mail"),
    "lat":         ("lat", "latitude"),
    "lng":         ("lng", "lon", "long", "longitude"),
    # Storepoint rend une distance déjà calculée quand la recherche part d'une adresse. Elle
    # remplace avantageusement le calcul à vol d'oiseau : c'est le chiffre que le site affiche.
    "distance_km": ("distance_km", "distance", "dist"),
}

# Codes / libellés vers ISO-2, pour compter sans se laisser piéger par « France » vs « FR ».
PAYS = {"france": "FR", "fr": "FR", "belgium": "BE", "belgique": "BE", "be": "BE",
        "germany": "DE", "deutschland": "DE", "allemagne": "DE", "de": "DE",
        "spain": "ES", "españa": "ES", "espagne": "ES", "es": "ES",
        "italy": "IT", "italia": "IT", "italie": "IT", "it": "IT",
        "netherlands": "NL", "nederland": "NL", "pays-bas": "NL", "nl": "NL",
        "portugal": "PT", "pt": "PT", "united kingdom": "GB", "gb": "GB", "uk": "GB",
        "united states": "US", "usa": "US", "us": "US"}


def pick(d: dict, keys) -> str | None:
    """Premier champ non vide parmi les alias. Les clés sont comparées sans casse ni
    séparateur : « postalCode », « postal_code » et « PostCode » sont le même champ."""
    flat = {re.sub(r"[^a-z]", "", k.lower()): v for k, v in d.items() if not isinstance(v, (dict, list))}
    for k in keys:
        v = flat.get(re.sub(r"[^a-z]", "", k))
        if v not in (None, "", "null"):
            return v
    return None


def trouve_liste(obj):
    """La liste de points de vente, où qu'elle soit enfouie. On retient la plus longue liste
    d'objets dont au moins la moitié portent quelque chose qui ressemble à un nom."""
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list):
            objs = [x for x in o if isinstance(x, dict)]
            if objs and len(objs) > len(best):
                nommes = sum(1 for x in objs if pick(x, CHAMPS["name"]))
                if nommes >= max(1, len(objs) // 2):
                    best = objs
            for x in o: walk(x)
        elif isinstance(o, dict):
            for v in o.values(): walk(v)
    walk(obj)
    return best


def normalise(raw: dict) -> dict:
    out = {k: pick(raw, alias) for k, alias in CHAMPS.items()}
    p = str(out.get("country") or "").strip().lower()
    out["country"] = PAYS.get(p, (out.get("country") or "").strip().upper()[:2] or None)
    for k in ("lat", "lng", "distance_km"):
        try: out[k] = float(out[k])
        except (TypeError, ValueError): out[k] = None
    cp = str(out.get("postal_code") or "").strip()
    out["postal_code"] = cp or None
    return out


def departement(s: dict) -> str | None:
    """Département français à partir du code postal. Rien d'exotique : les deux premiers
    chiffres, sauf la Corse (2A/2B) et les DOM (3 chiffres), qu'on ne rencontrera sans doute
    jamais ici mais qu'on ne veut pas voir comptés dans le 97e du continent."""
    cp = (s.get("postal_code") or "").replace(" ", "")
    if s.get("country") != "FR" or not re.match(r"^\d{5}$", cp): return None
    return cp[:3] if cp.startswith("97") or cp.startswith("98") else cp[:2]


def km(a, b) -> float:
    """Distance à vol d'oiseau. Suffisant pour un rayon de prospection : personne ne choisit
    une boutique à 3 km près."""
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def synthese(stores: list[dict]) -> None:
    import collections
    print(f"\n{'='*72}\n  ANNUAIRE TOPPS — {len(stores)} point(s) de vente\n{'='*72}")

    par_pays = collections.Counter(s["country"] or "??" for s in stores)
    print("\n  Par pays :")
    for p, n in par_pays.most_common():
        print(f"    {p or '??':<4} {n:>5}")

    cible = ["FR", "BE", "DE", "ES", "IT", "NL", "PT"]
    print(f"\n  Périmètre demandé : " + " · ".join(f"{p} {par_pays.get(p, 0)}" for p in cible))
    print(f"  Total sur ce périmètre : {sum(par_pays.get(p, 0) for p in cible)}")

    frbe = [s for s in stores if s["country"] in ("FR", "BE")]
    print(f"\n{'='*72}\n  FR + BE — {len(frbe)} boutique(s), triées par département\n{'='*72}")
    for s in sorted(frbe, key=lambda x: (x["country"], departement(x) or "zz", x["city"] or "")):
        d = departement(s) or ("BE" if s["country"] == "BE" else "??")
        site = f"  {s['website']}" if s.get("website") else ""
        print(f"  [{d:<3}] {(s['name'] or '?')[:38]:<40} {(s['postal_code'] or ''):<7} "
              f"{(s['city'] or '')[:20]:<22}{site}")

    nord = [s for s in frbe if departement(s) == "59"]
    print(f"\n  Département 59 : {len(nord)} boutique(s)")

    print(f"\n{'='*72}\n  RAYON {RAYON_KM} km AUTOUR DE WASQUEHAL\n{'='*72}")
    dejacalc = [s for s in stores if s.get("distance_km") is not None]
    if dejacalc:
        # le locator a déjà fait le calcul depuis l'adresse cherchée : on lui fait confiance
        proches = sorted((s for s in dejacalc if s["distance_km"] <= RAYON_KM),
                         key=lambda s: s["distance_km"])
        print(f"  {len(proches)} boutique(s) à moins de {RAYON_KM} km "
              f"(distances rendues par le locator) :")
        for s in proches:
            print(f"    {s['distance_km']:>6.1f} km  {(s['name'] or '?')[:34]:<36} "
                  f"{(s['postal_code'] or ''):<8} {(s['city'] or '')[:20]:<22}{s.get('website') or ''}")
        suiv = min((s["distance_km"] for s in dejacalc if s["distance_km"] > RAYON_KM), default=None)
        if suiv: print(f"    (la suivante est à {suiv:.0f} km)")
        return
    avec_gps = [s for s in stores if s["lat"] and s["lng"]]
    if not avec_gps:
        print("  (aucune coordonnée dans le dataset — rayon non calculable)")
        print(f"  Repli : les {len(nord)} boutique(s) du 59 ci-dessus, plus le 62 et la Belgique")
        print("  frontalière, couvrent l'essentiel de ce rayon.")
    else:
        proches = sorted(((km(WASQUEHAL, (s["lat"], s["lng"])), s) for s in avec_gps),
                         key=lambda x: x[0])
        proches = [(d, s) for d, s in proches if d <= RAYON_KM]
        print(f"  {len(proches)} boutique(s) à moins de {RAYON_KM} km :")
        for d, s in proches:
            print(f"    {d:>5.1f} km  {(s['name'] or '?')[:38]:<40} "
                  f"{(s['postal_code'] or ''):<7} {(s['city'] or '')[:22]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    src = Path(sys.argv[1])
    raw = json.loads(src.read_text(encoding="utf-8"))
    brut = trouve_liste(raw)
    if not brut:
        print(f"Aucune liste de points de vente reconnue dans {src}.")
        print("Vérifiez que le fichier contient bien la réponse de l'API du store locator.")
        sys.exit(1)
    stores = [normalise(x) for x in brut]
    # dédoublonnage : un même magasin revient parfois sur plusieurs rayons de recherche
    vus, uniques = set(), []
    for s in stores:
        cle = (s["name"], s["postal_code"], s["city"])
        if cle in vus: continue
        vus.add(cle); uniques.append(s)
    if len(uniques) != len(stores):
        print(f"({len(stores) - len(uniques)} doublon(s) écartés)")
    OUT.write_text(json.dumps(uniques, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {OUT}  ({len(uniques)} points de vente)")
    synthese(uniques)


if __name__ == "__main__":
    main()
