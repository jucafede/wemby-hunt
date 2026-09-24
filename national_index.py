#!/usr/bin/env python3
"""NATIONAL CANDIDATE INDEX — l'annuaire entier, à plat, sans crawl marchand.

CE QUE CETTE ÉTAPE FAIT, ET CE QU'ELLE NE FAIT PAS
--------------------------------------------------
Elle transforme cardshopmap en INDEX : un nom, une ville, un État, un domaine marchand,
un téléphone, des catégories. Elle ne visite AUCUN site marchand. Le funnel viendra après,
et seulement sur le TOP 100 priorisé — ouvrir 3 842 catalogues pour n'en garder que quelques
dizaines serait un gaspillage, et une impolitesse envers 3 800 serveurs.

CE QUE L'INDEX N'EST PAS
------------------------
Il n'est pas l'univers du marché. Une boutique absente de cardshopmap n'est pas une boutique
inexistante : c'est une boutique que cet annuaire ne référence pas. Le champ `source` le dit
explicitement pour que personne, plus tard, ne lise « absent de l'index » comme « n'existe pas ».

CE QUE L'ON NE LIT PAS
----------------------
robots.txt interdit /admin/, /api/, /go/ et /auth-error/. /go/ est la redirection sortante de
l'annuaire : on ne la suit jamais. Le domaine marchand se lit dans le HTML de la fiche, où il
est publié en clair. Quand il n'y est pas, le champ reste vide — et « pas de site publié dans
l'annuaire » ne veut pas dire « pas de site ».
"""
from __future__ import annotations
import json, re, sys, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import external_engine as xe
import shop_discovery as sd
from shop_accounting import NON_MARCHAND

ROOT = Path(__file__).parent
INDEX = ROOT / "discovered" / "national_index.json"
ANNUAIRE = "https://cardshopmap.com"
INTERDITS = ("/admin/", "/api/", "/go/", "/auth-error/")

# Une fiche boutique vit sous /card-shops/<etat>/<ville>/<boutique>/ : 7 segments une fois
# l'URL découpée. Cinq = la page d'État, six = une page de ville. Ni l'une ni l'autre n'est
# un marchand.
FICHE_RX = re.compile(r"^https://cardshopmap\.com/card-shops/([a-z0-9-]+)/([a-z0-9-]+)/([a-z0-9-]+)/?$")


# Deux lectures par seconde, comptées sous verrou. `xe.fetch` cadence déjà par hôte, mais son
# compteur n'est pas protégé : à plusieurs fils, il laisserait passer des rafales. On ne délègue
# pas la politesse à une condition de course.
PACE_S = 0.5
_verrou, _dernier = threading.Lock(), [0.0]


def _pace():
    with _verrou:
        attente = PACE_S - (time.monotonic() - _dernier[0])
        if attente > 0:
            time.sleep(attente)
        _dernier[0] = time.monotonic()


def _http(url: str, timeout: int = 25):
    """La même lecture que `xe.fetch`, mais cadencée par NOTRE compteur, pas par le sien.

    `xe.fetch` espace d'une seconde par hôte avec un compteur non protégé : à plusieurs fils
    il devient une condition de course, et l'annuaire rend ses pages en 0,4 s ou en 9 s selon
    son cache — deux fils suffisaient à tout figer. On émet donc deux requêtes par seconde,
    comptées sous verrou, et plusieurs lectures lentes se recouvrent. robots.txt reste
    souverain : il autorise /card-shops/, ne publie aucun Crawl-delay, et /go/, /api/,
    /admin/ et /auth-error/ ne sont jamais demandés.
    """
    _pace()
    import gzip, urllib.error, urllib.request
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=xe.HDR),
                                   timeout=timeout, context=xe.CTX)
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return r.status, raw.decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return e.code, "", f"HTTP {e.code}"
    except Exception as e:
        return None, "", e.__class__.__name__


# Un domaine PARTAGÉ par plusieurs marchands n'identifie aucun marchand : un serveur Discord,
# la boutique du fabricant, la place de marché où le magasin a un stand, une page de dons.
# Les exclure n'est pas un jugement sur la boutique — c'est constater que ce domaine ne la
# désigne pas.
#
# À NE PAS CONFONDRE avec une vitrine hébergée : `x.myshopify.com`, `x.wixsite.com`,
# `x.bigcartel.com`, `x.tcgplayerpro.com` appartiennent à UN magasin et sont sa boutique. Les
# écarter reviendrait à pénaliser le manque de moyens techniques — exactement ce que la
# consigne interdit.
DOMAINE_PARTAGE = re.compile(
    r"^(?:www\.)?(?:discord\.(?:gg|com)|topps\.com|paniniamerica\.net|upperdeck\.com|"
    r"tcgplayer\.com|(?:shop|store)\.tcgplayer\.com|beckett\.com|[\w-]+\.beckett\.com|"
    r"sgccard\.com|psacard\.com|collectors\.com|cardladder\.com|"
    r"eventbrite\.com|meetup\.com|patreon\.com|venmo\.com|cash\.app|paypal\.(?:com|me)|"
    r"gofundme\.com|beacons\.ai|linktr\.ee|bit\.ly|goo\.gl|forms\.gle|"
    r"(?:docs|drive|sites)\.google\.com)$", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def autorise(url: str) -> bool:
    return not any(i in url for i in INTERDITS)


# ------------------------------------------------------------------ sitemap
def sitemap_urls() -> list[str]:
    """Toutes les URL publiées par l'annuaire, en suivant les sitemaps imbriqués."""
    vus, urls, file = set(), [], [f"{ANNUAIRE}/sitemap/0.xml", f"{ANNUAIRE}/sitemap.xml"]
    while file:
        sm = file.pop(0)
        if sm in vus:
            continue
        vus.add(sm)
        st, b, _ = xe.fetch(sm, timeout=30)
        if st != 200 or not b:
            continue
        enfants = re.findall(r"<sitemap>.*?<loc>([^<]+)</loc>.*?</sitemap>", b, re.S)
        if enfants:
            file.extend(e.strip() for e in enfants)
            continue
        urls.extend(u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", b))
    return sorted(set(u for u in urls if autorise(u)))


def classe_national(urls: list[str]) -> dict:
    """Le sitemap trié par nature, à l'échelle du pays."""
    out = {"fiches_boutique": [], "pages_etat": [], "pages_ville": [],
           "evenements": [], "categories": [], "autres": []}
    for u in urls:
        if FICHE_RX.match(u):
            out["fiches_boutique"].append(u)
        elif "/events" in u:
            out["evenements"].append(u)
        elif u.startswith(f"{ANNUAIRE}/card-shops/"):
            n = len(u.rstrip("/").split("/"))
            out["pages_etat" if n == 5 else "pages_ville" if n == 6 else "categories"].append(u)
        elif re.search(r"/categor|/best-|/near-me|/guide", u, re.I):
            out["categories"].append(u)
        else:
            out["autres"].append(u)
    return out


# ------------------------------------------------------------------ fiches
def etat_ville(url: str) -> tuple[str, str]:
    m = FICHE_RX.match(url)
    return (m.group(1), m.group(2)) if m else ("", "")


# Le fil d'Ariane se mêle aux rubriques : « Home », l'État, la ville, le nom de la boutique.
# Ce ne sont pas des attributs du marchand, et les garder fausserait le score de la phase 2.
FIL_ARIANE = {"home", "card shops", "card shops near me", "usa", "united states", "all states"}


def categories(html: str) -> list[str]:
    """Les rubriques que l'annuaire attribue à la boutique, telles qu'il les publie."""
    cats = re.findall(r'"(?:itemListElement|keywords)"[^\[]*\[(.*?)\]', html, re.S)
    mots = set()
    for bloc in cats:
        mots.update(m.strip() for m in re.findall(r'"name":\s*"([^"]{2,40})"', bloc))
    for rx in (r'class="[^"]*(?:tag|badge|chip|category)[^"]*"[^>]*>\s*([^<]{2,40})\s*<',):
        mots.update(m.strip() for m in re.findall(rx, html, re.I))
    return sorted(m for m in mots
                  if m and m.lower() not in FIL_ARIANE
                  and not m.lower().startswith("card shops in"))[:12]


def _sans_identite(cats: list[str], nom, ville, etat: str) -> list[str]:
    """Le nom, la ville et l'État ne sont pas des rubriques : ce sont l'adresse."""
    bruit = {etat.replace("-", " ").lower()}
    if nom:
        bruit.add(nom.group(1).strip().lower())
    if ville:
        bruit.add(ville.group(1).strip().lower())
    return [c for c in cats if c.lower() not in bruit]


def lis(url: str) -> dict:
    """Une fiche d'annuaire, sans jamais ouvrir le site du marchand."""
    etat, ville = etat_ville(url)
    base = {"cardshopmap_url": url, "state": etat, "city_slug": ville, "shop_name": None,
            "city": None, "street_address": None, "phone": None, "website": None,
            "domain": None, "categories": [], "description": None, "since": None,
            "read": False}
    st, b, why = _http(url)
    if st != 200 or not b:
        base["error"] = why or f"HTTP {st}"
        return base
    base["read"] = True
    nom = (re.search(r'"@type":\s*"WebPage".*?"name":\s*"([^"]+)"', b, re.S)
           or re.search(r'"@type":\s*"(?:LocalBusiness|Store)".*?"name":\s*"([^"]+)"', b, re.S)
           or re.search(r"<title>([^<|]+)", b))
    v = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', b)
    tel = re.search(r'"telephone"\s*:\s*"([^"]+)"', b)
    rue = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', b)
    # « depuis 1994 », « established 2008 » : une ancienneté que l'annuaire publie lui-même.
    an = re.search(r"(?:since|established|est\.|serving\s+\w+\s+since|opened\s+in)\s+"
                   r"(19[5-9]\d|20[0-2]\d)", b, re.I)
    desc = re.search(r'"description":\s*"([^"]{20,400})"', b)
    sortants = [u for u in re.findall(r'href="(https?://[^"]+)"', b)
                if not NON_MARCHAND.search(u) and "cardshopmap.com" not in u]
    site = next((u for u in sortants if not sd.MARKETPLACES.search(u)), None)
    base.update(shop_name=nom.group(1).strip() if nom else None,
                city=v.group(1) if v else None,
                street_address=rue.group(1) if rue else None,
                since=int(an.group(1)) if an else None,
                phone=tel.group(1) if tel else None,
                description=desc.group(1) if desc else None,
                categories=_sans_identite(categories(b), nom, v, etat), website=site,
                domain=sd.domaine(site) if site else None)
    return base


# ------------------------------------------------------------------ index
BROUILLON = ROOT / "discovered" / "national_index.partial.json"


def construis(fiches: list[str], workers: int = 6, journal=print) -> list[dict]:
    """Lit les fiches. Le débit est tenu par `_pace`, les fils ne servent qu'à recouvrir
    les lectures lentes — l'annuaire répond parfois en neuf secondes."""
    deja = {}
    if BROUILLON.exists():
        try:
            deja = {f["cardshopmap_url"]: f
                    for f in json.loads(BROUILLON.read_text(encoding="utf-8"))}
            journal(f"  reprise : {len(deja)} fiches déjà lues")
        except Exception:
            deja = {}
    reste = [u for u in fiches if u not in deja]
    out, t0 = list(deja.values()), time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, f in enumerate(ex.map(lis, reste), 1):
            out.append(f)
            if i % 100 == 0 or i == len(reste):
                ec = time.monotonic() - t0
                journal(f"  {len(out)}/{len(fiches)} fiches — {ec/60:.1f} min "
                        f"({sum(1 for x in out if x.get('domain'))} domaines)")
                BROUILLON.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    BROUILLON.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def dedoublonne(fiches: list[dict]) -> dict:
    """Un domaine = un marchand. Vintage Stock a quatre boutiques et un seul site."""
    uniques: dict[str, dict] = {}
    for f in fiches:
        d = f.get("domain")
        if not d or DOMAINE_PARTAGE.match(d):
            continue
        if d in uniques:
            u = uniques[d]
            u["listings"] += 1
            if f["state"] not in u["states"]:
                u["states"].append(f["state"])
            u["cities"].append(f.get("city") or f["city_slug"])
            u["categories"] = sorted(set(u["categories"]) | set(f["categories"]))[:16]
            continue
        uniques[d] = {"domain": d, "shop_name": f["shop_name"], "website": f["website"],
                      "state": f["state"], "states": [f["state"]],
                      "cities": [f.get("city") or f["city_slug"]], "phone": f["phone"],
                      "categories": list(f["categories"]), "description": f["description"],
                      "cardshopmap_url": f["cardshopmap_url"], "listings": 1,
                      "source": "cardshopmap"}
    return uniques


def exclus_partages(fiches: list[dict]) -> list[dict]:
    """Ce que le dédoublonnage écarte, consigné — aucune disparition silencieuse."""
    out: dict[str, dict] = {}
    for f in fiches:
        d = f.get("domain")
        if d and DOMAINE_PARTAGE.match(d):
            e = out.setdefault(d, {"domain": d, "listings": 0, "shops": []})
            e["listings"] += 1
            if len(e["shops"]) < 8:
                e["shops"].append(f.get("shop_name"))
    return sorted(out.values(), key=lambda x: -x["listings"])


def sauve(payload: dict):
    payload["generated_at"] = now()
    payload["note"] = ("Index de CANDIDATS, pas l'univers du marché. cardshopmap est une source "
                       "de découverte parmi d'autres : une boutique qui n'y figure pas n'est pas "
                       "une boutique qui n'existe pas, et un domaine absent ici n'autorise aucune "
                       "conclusion sur le marchand. Aucun site marchand n'a été visité à cette étape.")
    INDEX.parent.mkdir(exist_ok=True)
    INDEX.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def charge() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print("PHASE 1 — INDEX NATIONAL DES CANDIDATS\n" + "=" * 46)
    urls = sitemap_urls()
    print(f"sitemap : {len(urls)} URL autorisées par robots.txt")
    c = classe_national(urls)
    for k, v in c.items():
        print(f"  {k:18} {len(v):5}")
    fiches = c["fiches_boutique"]
    if limite:
        fiches = fiches[:limite]
        print(f"\n[ÉCHANTILLON {limite}]")
    print(f"\nlecture de {len(fiches)} fiches (aucun site marchand visité)")
    lues = construis(fiches)
    uniques = dedoublonne(lues)
    par_etat: dict[str, set] = {}
    for u in uniques.values():
        for s in u["states"]:
            par_etat.setdefault(s, set()).add(u["domain"])
    sauve({"sitemap_total": len(urls),
           "compte_par_nature": {k: len(v) for k, v in c.items()},
           "fiches_lues": len(lues),
           "fiches_avec_site": sum(1 for f in lues if f.get("domain")),
           "fiches_sans_site": sum(1 for f in lues if f["read"] and not f.get("domain")),
           "fiches_illisibles": sum(1 for f in lues if not f["read"]),
           "domaines_uniques": len(uniques),
           "par_etat": {k: len(v) for k, v in sorted(par_etat.items(), key=lambda x: -len(x[1]))},
           "candidates": list(uniques.values()),
           "listings": lues})
    print(f"\nfiches lues              {len(lues)}")
    print(f"avec site marchand       {sum(1 for f in lues if f.get('domain'))}")
    print(f"sans site publié         {sum(1 for f in lues if f['read'] and not f.get('domain'))}")
    print(f"illisibles               {sum(1 for f in lues if not f['read'])}")
    print(f"DOMAINES UNIQUES         {len(uniques)}")
    print(f"États représentés        {len(par_etat)}")


if __name__ == "__main__":
    main()
