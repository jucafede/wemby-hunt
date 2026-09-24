#!/usr/bin/env python3
"""SHOP DISCOVERY — découvrir les boutiques que nous ne connaissons pas encore.

LE PROBLÈME QUE CELA RÉSOUT
---------------------------
Notre crawler cherche bien dans les 58 boutiques qu'il connaît. Le plafond n'est plus la
qualité du balayage, c'est la COUVERTURE. CardVault by Tom Brady l'a démontré : vrai
e-commerce, Shopify, scellé NBA, absente du registre — et trouvée par une simple recherche
géographique.

LE CANAL, ET POURQUOI CELUI-LÀ
------------------------------
Les moteurs de recherche généralistes nous sont fermés (Brave 429, Mojeek et DuckDuckGo
bloqués, Bing rend des résultats sans rapport). La découverte géographique passe donc par un
annuaire : cardshopmap.com, 3 842 fiches, dont le robots.txt NOMME ClaudeBot et l'autorise
explicitement. On respecte ses interdits — /admin/, /api/, /go/ — et on ne suit jamais ses
redirections sortantes : le domaine marchand se lit dans la page.

LE FUNNEL, ET CE QU'IL REFUSE
-----------------------------
Un annuaire ne qualifie personne. Il ne fournit qu'un CANDIDAT. Entrent ensuite dans
sources.yaml les seules boutiques qui passent tout : site vivant → e-commerce réel →
basketball au catalogue → basketball SCELLÉ → catalogue lisible automatiquement.

Une boutique Pokémon, un magasin physique sans boutique en ligne, un vendeur de singles : ce
sont des rejets, et ils sont CONSIGNÉS pour ne jamais être réexaminés. Cinquante bonnes
sources valent mieux que trois cents lignes qui gonflent le registre sans rien apporter.
"""
from __future__ import annotations
import json, re, sys, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import yaml
import external_engine as xe

ROOT = Path(__file__).parent
CANDIDATS = ROOT / "discovered" / "shop_candidates.json"
ANNUAIRE = "https://cardshopmap.com"

QUALIFIED = "QUALIFIED"
R_ECOM = "REJECTED_NO_ECOMMERCE"
R_BASKET = "REJECTED_NO_BASKETBALL"
R_SEALED = "REJECTED_NO_SEALED"
R_CRAWL = "REJECTED_NOT_CRAWLABLE"
R_MARKET = "REJECTED_MARKETPLACE_ONLY"
R_AUTRE = "REJECTED_OTHER"

# Un domaine de place de marché n'est pas une boutique : on ne peut ni le crawler proprement
# ni le tenir pour un vendeur identifié.
MARKETPLACES = re.compile(r"ebay\.|etsy\.|amazon\.|facebook\.|instagram\.|whatnot\.|mercari\.|"
                          r"tiktok\.|linktr\.ee|square\.site|shopmy|bigcartel\.com$", re.I)
# Panini décline Prizm, Donruss, Select et Mosaic sur TOUS ses sports. « Prizm » seul a
# qualifié un « 2025 Panini Prizm Football Blaster Box » comme preuve de basket. Le sport doit
# être nommé — ou la gamme doit être exclusivement basket (Hoops, Court Kings).
AUTRE_SPORT = re.compile(r"football|\bnfl\b|soccer|fifa|world\s*cup|premier\s*league|la\s*liga|"
                         r"bundesliga|serie\s*a\b|\buefa\b|baseball|\bmlb\b|hockey|\bnhl\b|"
                         r"\bufc\b|\bwwe\b|golf|nascar|racing|tennis|cricket|rugby|wnba|"
                         r"pokemon|magic|yu-?gi-?oh|lorcana|one\s*piece|digimon|marvel|star\s*wars",
                         re.I)
_BASKET_MOT = re.compile(r"basketball|\bnba\b|\bhoops\b|court\s*kings|\bnbl\b", re.I)


class _Basket:
    """Basket = le sport est nommé ET aucun autre sport ne l'est."""
    def search(self, t):
        return _BASKET_MOT.search(t) if not AUTRE_SPORT.search(t) else None


BASKET = _Basket()
# « Jumbo » seul a qualifié un Funko Pop « Vinyl Jumbo 10\" » comme du basket scellé. Un mot
# de format doit être accolé à un contenant : c'est « Jumbo Box », pas « Jumbo » tout court.
SCELLE = re.compile(r"hobby\s*box|blaster|mega\s*box|retail\s*box|booster\s*box|"
                    r"\bhobby\s*case\b|\d{1,2}[\s-]*box\s*case|hanger\s*(?:box|pack)?|"
                    r"fat\s*pack|jumbo\s*(?:box|pack)|sealed\s*(?:box|case|pack|wax)|"
                    r"\bwax\s*box\b|\bcello\b|value\s*box|\bh2\b", re.I)
# Ce qui porte un nom de sport sans être une carte : figurines, maillots, ballons.
PAS_DES_CARTES = re.compile(r"funko|\bpop!|vinyl|bobblehead|jersey|\bball\b|sneaker|poster|"
                            r"t-?shirt|mug|\bhat\b|figure|statue", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def domaine(url: str) -> str:
    h = urllib.parse.urlsplit(url if "//" in url else "https://" + url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def charge() -> dict:
    if CANDIDATS.exists():
        return json.loads(CANDIDATS.read_text(encoding="utf-8"))
    return {"generated_at": None, "candidates": []}


def sauve(d: dict):
    d["generated_at"] = now()
    d["note"] = ("Journal des candidats examinés. Un REJETÉ y reste pour ne plus jamais être "
                 "réexaminé : c'est le but du fichier. Seuls les QUALIFIED entrent dans "
                 "sources.yaml — un annuaire ne qualifie personne, il fournit un candidat.")
    CANDIDATS.parent.mkdir(exist_ok=True)
    CANDIDATS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def fiches_etat(etat: str, sitemap_urls: list) -> list:
    """Les fiches boutique d'un État, depuis le sitemap (aucune exploration à l'aveugle)."""
    pref = f"{ANNUAIRE}/card-shops/{etat}/"
    return [u for u in sitemap_urls
            if u.startswith(pref) and u.rstrip("/").count("/") >= 6]


def lis_fiche(url: str) -> dict | None:
    """Nom, ville, site marchand, téléphone — tels que l'annuaire les publie."""
    st, b, _ = xe.fetch(url, timeout=18)
    if st != 200 or not b:
        return None
    nom = re.search(r'"@type":\s*"WebPage".*?"name":\s*"([^"]+)"', b, re.S)
    ville = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', b)
    tel = re.search(r'"telephone"\s*:\s*"([^"]+)"', b)
    sortants = [u for u in re.findall(r'href="(https?://[^"]+)"', b)
                if not re.search(r"cardshopmap|maps\.google|overturemaps|google\.com|"
                                 r"apple\.com|schema\.org|openstreetmap|osm\.org|"
                                 r"bing\.com/maps|waze\.com|yelp\.com|mapquest", u, re.I)]
    site = next((u for u in sortants if not MARKETPLACES.search(u)), None)
    desc = re.search(r'"description":\s*"([^"]{20,400})"', b)
    return {"annuaire_url": url, "nom": nom.group(1) if nom else None,
            "ville": ville.group(1) if ville else None,
            "telephone": tel.group(1) if tel else None,
            "site": site, "sortants": sortants[:6],
            "description": desc.group(1) if desc else None}


def qualifie(dom: str) -> dict:
    """Le funnel, dans l'ordre, et il s'arrête au premier refus.

    Chaque étape doit être PROUVÉE, pas supposée. « Le site répond » ne veut pas dire
    « e-commerce », et « e-commerce » ne veut pas dire « vend du basket scellé ».
    """
    r = {"domain": dom, "checked_at": now(), "website_accessible": False, "platform": "unknown",
         "ecommerce": False, "cart_available": False, "basketball": False,
         "sealed_basketball": False, "crawlable": False, "robots_status": None,
         "evidence": None, "status": None, "reason": None, "discovery_score": 0}

    if MARKETPLACES.search(dom):
        r.update(status=R_MARKET, reason="domaine de place de marché, pas une boutique propre")
        return r

    base = f"https://{dom}"
    r["robots_status"] = "allowed" if xe.robots_ok(base + "/") else "disallowed"
    if r["robots_status"] == "disallowed":
        r.update(status=R_CRAWL, reason="robots.txt nous interdit ce site — nous ne le crawlons pas")
        return r

    st, b, why = xe.fetch(base, timeout=16)
    if st != 200 or not b:
        r.update(status=R_AUTRE, reason=f"site injoignable ({why or 'HTTP ' + str(st)})")
        return r
    r["website_accessible"] = True

    low = b.lower()
    r["platform"] = ("shopify" if "cdn.shopify" in low else
                     "woocommerce" if ("woocommerce" in low or "wp-content" in low) else
                     "bigcommerce" if "bigcommerce" in low else
                     "squarespace" if "squarespace" in low else
                     "wix" if "wixstatic" in low or "parastorage" in low else "custom")
    r["cart_available"] = bool(re.search(r"add to cart|/cart|add-to-cart|checkout", low))
    r["ecommerce"] = r["cart_available"] or r["platform"] in ("shopify", "woocommerce", "bigcommerce")
    if not r["ecommerce"]:
        r.update(status=R_ECOM, reason=f"aucun signal d'e-commerce (plateforme {r['platform']})")
        return r

    # basketball ET scellé doivent être PROUVÉS par une vraie fiche produit
    fiches, api = catalogue(base, r["platform"])
    if not api:
        r.update(status=R_CRAWL, reason="aucune API de catalogue lisible")
        return r
    r["crawlable"] = True
    if not fiches:
        r.update(status=R_BASKET, reason="catalogue lisible, aucun produit correspondant")
        return r
    basket = [p for p in fiches if BASKET.search(p["titre"])]
    r["basketball"] = bool(basket)
    if not basket:
        r.update(status=R_BASKET, reason=f"{len(fiches)} fiches lues, aucun basketball")
        return r
    scelle = [p for p in basket
              if SCELLE.search(p["titre"]) and not PAS_DES_CARTES.search(p["titre"])]
    r["sealed_basketball"] = bool(scelle)
    if not scelle:
        r.update(status=R_SEALED,
                 reason=f"{len(basket)} fiche(s) basketball, mais aucune scellée (singles/slabs)")
        return r

    t = scelle[0]
    r["evidence"] = {"product_name": t["titre"], "product_url": t["url"],
                     "price": t.get("prix"),
                     "availability": "IN_STOCK" if t.get("dispo") else "OUT_OF_STOCK"}
    blob = " ".join(p["titre"] for p in scelle)
    r["discovery_score"] = (5 + (4 if re.search(r"panini", blob, re.I) else 0)
                            + (3 if re.search(r"prizm", blob, re.I) else 0)
                            + (3 if re.search(r"\bselect\b", blob, re.I) else 0)
                            + (3 if re.search(r"2023[-/ ]?24|23[-/]24", blob) else 0)
                            + (2 if r["platform"] in ("shopify", "woocommerce", "bigcommerce") else 0))
    r.update(status=QUALIFIED, reason=f"{len(scelle)} fiche(s) de basket scellé lues")
    return r


def catalogue(base: str, plat: str, limite: int = 25):
    """(fiches, api_repond). Aucune protection n'est contournée.

    LES DEUX SONT DISTINCTS, et les confondre fausse tout le diagnostic : une API qui répond
    « zéro résultat pour basketball » dit que la boutique N'A PAS DE BASKETBALL. Une API qui
    ne répond pas dit que nous ne savons pas lire son catalogue. Le premier est une info sur
    le marchand, le second une info sur nous — les ranger ensemble sous NOT_CRAWLABLE gonflait
    ce motif de seize boutiques et masquait le vrai signal.
    """
    out, repond = [], False
    for q in ("basketball", "panini basketball", "prizm", "hobby box"):
        st, b, _ = xe.fetch(f"{base}/search/suggest.json?q={urllib.parse.quote(q)}"
                            f"&resources[type]=product&resources[limit]={limite}", timeout=12)
        if st == 200 and (b or "").strip().startswith("{"):
            repond = True
            try:
                for p in json.loads(b)["resources"]["results"]["products"]:
                    out.append({"titre": p.get("title", ""), "url": base + (p.get("url") or ""),
                                "prix": p.get("price"), "dispo": bool(p.get("available"))})
            except Exception:
                pass
        if out:
            return out, True
    for q in ("basketball", "prizm"):
        st, b, _ = xe.fetch(f"{base}/wp-json/wc/store/v1/products?search={urllib.parse.quote(q)}"
                            f"&per_page={limite}", timeout=12)
        if st == 200 and (b or "").strip().startswith("["):
            repond = True
            try:
                for p in json.loads(b):
                    pr = p.get("prices") or {}
                    mn = int(pr.get("currency_minor_unit", 2) or 2)
                    out.append({"titre": p.get("name", ""), "url": p.get("permalink", ""),
                                "prix": (float(pr.get("price") or 0) / (10 ** mn)) or None,
                                "dispo": bool(p.get("is_in_stock"))})
            except Exception:
                pass
        if out:
            return out, True
    # dernier recours Shopify : le catalogue complet, quand la recherche interne est muette
    st, b, _ = xe.fetch(f"{base}/products.json?limit=250", timeout=14)
    if st == 200 and (b or "").strip().startswith("{"):
        repond = True
        try:
            for p in json.loads(b).get("products", []):
                v = (p.get("variants") or [{}])[0]
                out.append({"titre": p.get("title", ""),
                            "url": f"{base}/products/{p.get('handle','')}",
                            "prix": v.get("price"), "dispo": bool(v.get("available"))})
        except Exception:
            pass
    return out, repond


ETATS = ["idaho", "iowa", "nebraska", "oklahoma"]


def main():
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]
    connus = {domaine(s["base_url"]) for s in src}
    d = charge()
    deja_vus = {c["domain"] for c in d["candidates"]}

    st, sm, _ = xe.fetch(f"{ANNUAIRE}/sitemap.xml", timeout=30)
    urls = re.findall(r"<loc>([^<]+)</loc>", sm or "")
    print(f"annuaire : {len(urls)} URLs\n")

    metriques = {}
    for etat in ETATS:
        fiches = fiches_etat(etat, urls)
        villes = sorted({p for p in (u.rstrip("/").split("/") for u in fiches)
                         if len(p) > 5 for p in [p[5]]})
        m = {"cities_examined": len(villes), "search_queries_executed": 0,
             "candidate_domains": 0, "candidate_shops": len(fiches),
             "qualified_shops": 0, "rejected_shops": 0, "existing_shops": 0,
             "new_shops": 0, "rejets": {}}
        print(f"=== {etat.upper()} — {len(fiches)} fiche(s), {len(villes)} ville(s)")
        domaines_etat = {}
        for u in fiches:
            f = lis_fiche(u)
            m["search_queries_executed"] += 1
            if not f or not f.get("site"):
                continue
            dom = domaine(f["site"])
            if not dom or dom in domaines_etat:
                continue
            domaines_etat[dom] = f
        m["candidate_domains"] = len(domaines_etat)
        print(f"    {len(domaines_etat)} domaine(s) marchand(s) distinct(s)")

        for dom, f in domaines_etat.items():
            if dom in connus:
                m["existing_shops"] += 1
                continue
            if dom in deja_vus:
                continue
            q = qualifie(dom)
            q.update({"name": f.get("nom"), "city": f.get("ville"), "state": etat,
                      "phone": f.get("telephone"), "discovered_via": "cardshopmap.com",
                      "directory_url": f.get("annuaire_url")})
            d["candidates"].append(q)
            deja_vus.add(dom)
            if q["status"] == QUALIFIED:
                m["qualified_shops"] += 1
                m["new_shops"] += 1
                print(f"    ✅ {dom:<34} score {q['discovery_score']:>2} · {f.get('ville')}"
                      f" · {(q.get('evidence') or {}).get('product_name','')[:40]}")
            else:
                m["rejected_shops"] += 1
                m["rejets"][q["status"]] = m["rejets"].get(q["status"], 0) + 1
            sauve(d)
        metriques[etat] = m
        print(f"    → {m['qualified_shops']} qualifiée(s), {m['rejected_shops']} rejetée(s), "
              f"{m['existing_shops']} déjà connue(s)\n")

    d["metriques"] = metriques
    sauve(d)
    q = [c for c in d["candidates"] if c["status"] == QUALIFIED]
    print(f"=== {len(q)} boutique(s) QUALIFIÉE(S) au total")
    for c in sorted(q, key=lambda x: -x["discovery_score"]):
        print(f"  {c['discovery_score']:>2}  {c['domain']:<34} {c.get('city') or '?':<16} "
              f"{c['state']:<10} {c['platform']}")


if __name__ == "__main__":
    main()
