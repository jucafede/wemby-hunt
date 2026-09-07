#!/usr/bin/env python3
"""EXTERNAL WEB + MARKETPLACE — recherche et revalidation automatiques du noyau Prizm.

POURQUOI CE MODULE EXISTE
-------------------------
Jusqu'au 07/09, `external_prizm.json` était écrit à la main. Douze annonces relevées un soir
dans un navigateur, figées, et un tableau public qui affichait « 3 live » deux jours plus tard
sans que personne ait revérifié quoi que ce soit. Une donnée qu'on ne peut pas rafraîchir seul
n'est pas une donnée de production : c'est une capture d'écran avec des prétentions.

LES DEUX ÉTAPES, QUI NE SE CONFONDENT PAS
-----------------------------------------
KNOWN URL REFRESH  — revérifier les annonces déjà connues. Répond à « celle-ci tient-elle ? »
NEW LISTING DISCOVERY — chercher ce que nous ne connaissons pas. Répond à « qu'avons-nous raté ? »

Un moteur qui ne fait que la première ne trouvera jamais la treizième annonce. C'est exactement
le défaut qu'avait la version manuelle : elle vérifiait bien ce qu'on lui avait donné.

CE QUE NOUS POUVONS ET NE POUVONS PAS LIRE
------------------------------------------
eBay, StockX, SportsCardsPro et 130point répondent 403 à toute lecture automatisée depuis un
serveur. Ce sont des protections anti-robot : on ne les contourne pas. Conséquence assumée et
visible dans les données — une annonce eBay ou StockX ne peut PAS être confirmée par ce module,
donc elle ne peut pas être BEST LIVE. Elle reste affichée, datée, avec son statut réel.

Les moteurs de recherche HTML (DuckDuckGo, Bing) répondent, eux. Ils sont notre seul accès à
« ce que nous ne connaissons pas encore », et chaque interrogation est journalisée avec son
résultat — OK, VIDE ou BLOQUÉ. Un moteur bloqué doit se voir dans le rapport, pas se traduire
par un zéro silencieux.

LA RÈGLE DE FRAÎCHEUR
---------------------
Une annonce non VÉRIFIÉE depuis plus de 24 h devient STALE. Elle reste visible — la faire
disparaître effacerait ce que nous savons — mais elle ne compte plus comme live, ne peut pas
être le meilleur prix, et ne déclenche aucun BUY. Un prix de mardi n'achète rien le jeudi.
"""
from __future__ import annotations
import base64
import gzip
import html as _html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "discovered"
STORE = OUT / "external_prizm.json"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HDR = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
       "Accept-Encoding": "gzip"}
DELAY_S = 1.0          # une requête par seconde et par hôte, jamais plus
STALE_H = 24           # au-delà, une observation non vérifiée n'est plus live

# ---------------------------------------------------------------- états
CONFIRMED_LIVE = "CONFIRMED_LIVE"   # la page dit disponible, nous l'avons lue
PROBABLE_LIVE  = "PROBABLE_LIVE"    # indices de disponibilité, pas de donnée structurée
OOS            = "OOS"              # la page dit rupture
STALE          = "STALE"            # non vérifiable, et le dernier live remonte à > 24 h
LOST           = "LOST"             # 404/410 : la page n'existe plus
AMBIGUOUS      = "AMBIGUOUS"        # lecture refusée ou illisible, mais vue live récemment
STATES = (CONFIRMED_LIVE, PROBABLE_LIVE, OOS, STALE, LOST, AMBIGUOUS)

# Un seul endroit décide de ce qui compte comme disponible. Le reste du moteur s'y réfère.
LIVE_STATES = (CONFIRMED_LIVE, PROBABLE_LIVE)


def counts_as_live(st: str) -> bool:
    return st in LIVE_STATES


def can_be_best_live(st: str) -> bool:
    """STALE, LOST, OOS et AMBIGUOUS ne portent aucun meilleur prix. Une annonce qu'on n'a pas
    su revérifier ne devient pas la référence du tableau sous prétexte qu'elle est basse."""
    return st in LIVE_STATES


def can_trigger_buy(st: str) -> bool:
    return st in LIVE_STATES


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_h(ts: str | None, ref: datetime | None = None) -> float | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts)
    except ValueError:
        try:
            d = datetime.fromisoformat(ts + "T00:00:00+00:00")
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return ((ref or datetime.now(timezone.utc)) - d).total_seconds() / 3600.0


def effective_status(probe: str, last_seen_live: str | None, ref=None) -> str:
    """Le statut retenu après une sonde.

    Une sonde concluante fait foi. Une sonde refusée (403, défi anti-robot, réseau) ne fait
    PAS foi : on retombe sur l'âge du dernier live constaté. Moins de 24 h, l'annonce reste
    plausible ; au-delà, elle devient STALE. C'est la règle qui empêche une capture d'écran
    de mardi de tenir lieu de disponibilité le jeudi.
    """
    if probe in (CONFIRMED_LIVE, PROBABLE_LIVE, OOS, LOST):
        return probe
    # Sonde non concluante : c'est l'âge du dernier live CONSTATÉ qui tranche.
    age = _age_h(last_seen_live, ref)
    return AMBIGUOUS if (age is not None and age <= STALE_H) else STALE


# ---------------------------------------------------------------- lecture HTTP
_last_hit: dict[str, float] = {}


def fetch(url: str, timeout: int = 12):
    """Rend (status, texte, motif). status None = pas de réponse exploitable."""
    host = urllib.parse.urlsplit(url).netloc
    wait = DELAY_S - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=HDR),
                                   timeout=timeout, context=CTX)
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


# ---------------------------------------------------------------- robots.txt
# Ce projet ne lit pas ce qu'un site lui interdit de lire. Blowout nomme ClaudeBot avec
# `Disallow: /` et n'est donc pas crawlé, alors même que son catalogue nous intéresserait.
# La règle vaut pour la découverte comme pour le crawl : sonder une fiche produit reste une
# lecture automatisée. Un refus n'est pas un obstacle à contourner, c'est une réponse.
_robots: dict = {}


def robots_ok(url: str) -> bool:
    import urllib.robotparser
    parts = urllib.parse.urlsplit(url)
    origine = f"{parts.scheme}://{parts.netloc}"
    if origine not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(origine + "/robots.txt")
        try:
            rp.read()
        except Exception:
            # robots.txt illisible : on ne présume pas d'une interdiction qui n'est pas écrite
            rp = None
        _robots[origine] = rp
    rp = _robots[origine]
    if rp is None:
        return True
    return rp.can_fetch(UA, url) or rp.can_fetch("*", url)


CHALLENGE = re.compile(r"just a moment|cf-browser-verification|captcha|are you a human|"
                       r"robot or human|enable javascript and cookies|access denied|"
                       r"unusual traffic|verify you are a human", re.I)


# ---------------------------------------------------------------- lecture d'une fiche
JSONLD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
OG_PRICE = re.compile(r'<meta[^>]+property="(?:product:price:amount|og:price:amount)"[^>]+content="([^"]+)"', re.I)
OG_CUR = re.compile(r'<meta[^>]+property="(?:product:price:currency|og:price:currency)"[^>]+content="([^"]+)"', re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
SOLDOUT = re.compile(r"sold\s*out|out\s*of\s*stock|rupture|épuisé|indisponible|no longer available", re.I)
ADDCART = re.compile(r"add to (?:cart|bag|basket)|ajouter au panier|buy it now|acheter", re.I)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def read_offer(body: str):
    """Extrait (titre, prix, devise, disponibilité) d'une fiche produit.

    JSON-LD d'abord — c'est ce que les marchands publient pour Google, donc ce qu'ils tiennent
    à jour. Les balises OpenGraph ensuite. Le texte de la page en dernier recours, et seulement
    pour trancher disponible/rupture : un prix lu dans du texte libre est un prix inventé.
    """
    title = None
    m = TITLE.search(body)
    if m:
        title = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    price = cur = avail = None
    for blob in JSONLD.findall(body):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        for node in _walk(data):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Product" in types and node.get("name"):
                title = title or _html.unescape(str(node["name"]))
            if "Offer" in types or "AggregateOffer" in types:
                p = node.get("price") or node.get("lowPrice")
                if p is not None and price is None:
                    try:
                        price = float(str(p).replace(",", "").replace("$", "").strip())
                    except ValueError:
                        pass
                cur = cur or node.get("priceCurrency")
                a = str(node.get("availability") or "")
                if a:
                    avail = "InStock" in a or "LimitedAvailability" in a or "PreOrder" in a
    if price is None:
        m = OG_PRICE.search(body)
        if m:
            try:
                price = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        mc = OG_CUR.search(body)
        cur = cur or (mc.group(1) if mc else None)
    return title, price, cur, avail


def probe(url: str):
    """Sonde une annonce. Rend (statut_brut, prix, devise, titre, motif)."""
    if not robots_ok(url):
        return AMBIGUOUS, None, None, None, "robots.txt interdit la lecture"
    st, body, why = fetch(url)
    if st in (404, 410):
        return LOST, None, None, None, why
    if st is None or st >= 400 or not body:
        return AMBIGUOUS, None, None, None, why or f"HTTP {st}"
    if CHALLENGE.search(body[:4000]):
        return AMBIGUOUS, None, None, None, "défi anti-robot"
    title, price, cur, avail = read_offer(body)
    if avail is True:
        return CONFIRMED_LIVE, price, cur, title, None
    if avail is False:
        return OOS, price, cur, title, None
    if layer_of(url) == "marketplace":
        # Sur une place de marché, le texte de la page ne dit RIEN de l'annonce.
        # « Buy It Now » figure en dur sur une fiche catalogue eBay, qu'un vendeur propose
        # l'objet ou non : s'y fier fabrique un live qui n'existe pas. Seule une donnée
        # structurée de disponibilité fait foi ici, et à défaut on reste dans le doute.
        return AMBIGUOUS, price, cur, title, "place de marché : aucun stock structuré"
    txt = re.sub(r"<[^>]+>", " ", body)
    if SOLDOUT.search(txt):
        return OOS, price, cur, title, "texte de page"
    if ADDCART.search(txt):
        return PROBABLE_LIVE, price, cur, title, "texte de page"
    return AMBIGUOUS, price, cur, title, "aucun signal de stock"


# ---------------------------------------------------------------- moteurs de recherche
# Aucun moteur ne nous doit un service. Brave rend d'excellents résultats marchands mais
# répond 429 dès la deuxième requête rapprochée ; Bing sert une page dégradée aux clients
# automatisés (il cherche « 2023 » quand on lui demande « 2023-24 Panini Prizm ») ; DuckDuckGo
# bascule en page « anomaly » au bout de quelques appels. D'où trois décisions :
#   · plusieurs moteurs, essayés dans l'ordre jusqu'à ce que l'un réponde ;
#   · un délai généreux entre deux interrogations d'un même moteur — nous ne sommes pas pressés ;
#   · chaque tentative est journalisée avec son issue, pour qu'un « 0 trouvé » ne puisse jamais
#     se confondre avec un « 0 cherché ».
SEARCH_DELAY_S = 6.0

ENGINES = (
    ("brave",      "https://search.brave.com/search?q="),
    ("mojeek",     "https://www.mojeek.com/search?q="),
    ("duckduckgo", "https://html.duckduckgo.com/html/?q="),
    ("bing",       "https://www.bing.com/search?q="),
)

# Hôtes qui ne sont jamais une annonce : les moteurs eux-mêmes, et le bruit social.
ENGINE_HOSTS = re.compile(r"(?:^|\.)(?:brave|mojeek|duckduckgo|bing|google|msn|yahoo|ecosia|"
                          r"startpage|searx)\.", re.I)
NOISE = re.compile(r"(?:^|\.)(?:youtube|youtu|facebook|instagram|tiktok|twitter|x|reddit|"
                   r"pinterest|wikipedia|wikimedia|blogspot|medium|quora|linkedin|"
                   r"spotify|apple|imdb|onthisday|calendar-365|thefactsite)\.", re.I)
ADS = re.compile(r"duckduckgo\.com/y\.js|bing\.com/aclick|googleadservices|/aclk\?", re.I)
RELEVANT = re.compile(r"prizm|panini", re.I)


def _unwrap(u: str) -> str | None:
    """Rend l'URL de destination derrière l'emballage d'un moteur.

    DuckDuckGo redirige par `/l/?uddg=<url encodée>`, Bing par `/ck/a?...&u=a1<base64url>`.
    Une URL d'emballage sondée ne mène nulle part : c'est le moteur qu'on interroge, pas le
    marchand — le défaut qui a fait sonder bing.com cinquante-neuf fois de suite.
    """
    u = _html.unescape(u)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
    if "uddg" in q:
        return q["uddg"][0]
    raw = (q.get("u") or [""])[0]
    if raw.startswith("a1"):
        b = raw[2:] + "=" * (-len(raw[2:]) % 4)
        try:
            return base64.urlsafe_b64decode(b).decode("utf-8", "replace")
        except Exception:
            return None
    return u


def links_from(body: str) -> list[str]:
    """Extraction générique : tous les liens sortants, dans l'ordre de la page.

    Volontairement indépendante du balisage de chaque moteur. Un sélecteur CSS taillé pour
    la maquette du jour se casse en silence à la première refonte, et un moteur qui rend
    zéro résultat ressemble alors à un marché vide — la pire panne possible ici.
    """
    out, vus = [], set()
    for href in re.findall(r'href="(https?://[^"\s]+)"', body):
        u = _unwrap(href)
        if not u or not u.startswith("http"):
            continue
        u = u.split("#")[0]
        host = urllib.parse.urlsplit(u).netloc
        if not host or ENGINE_HOSTS.search(host) or NOISE.search(host) or ADS.search(u):
            continue
        if u not in vus:
            vus.add(u)
            out.append(u)
    return out


def _brave_api(query: str):
    """Brave Search API — le seul canal de recherche VRAIMENT fiable depuis un serveur.

    L'interface HTML de Brave rend d'excellents résultats marchands puis bloque l'adresse IP
    dès la deuxième requête rapprochée. Son API, elle, tient ce qu'elle promet et son palier
    gratuit couvre largement nos quelques dizaines de requêtes par passage. Poser
    `BRAVE_API_KEY` dans les secrets du dépôt fait passer la découverte de « ce que les moteurs
    veulent bien nous laisser voir » à « ce que nous avons décidé de chercher ».
    """
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        return None, "BRAVE_API_KEY absent"
    try:
        req = urllib.request.Request(
            "https://api.search.brave.com/res/v1/web/search?count=20&q="
            + urllib.parse.quote_plus(query),
            headers={"Accept": "application/json", "X-Subscription-Token": key})
        data = json.load(urllib.request.urlopen(req, timeout=25, context=CTX))
    except Exception as e:
        return None, f"{e.__class__.__name__}"
    urls = [r.get("url") for r in ((data.get("web") or {}).get("results") or []) if r.get("url")]
    return [u for u in urls if not NOISE.search(urllib.parse.urlsplit(u).netloc)], None


_last_search = 0.0
# Un moteur qui nous a fermé la porte au début du passage nous la fermera aussi à la fin :
# le blocage vise l'adresse IP, pas la requête. On l'écarte pour le reste du run au lieu de
# payer six secondes d'attente par requête pour se faire refuser trente fois de suite.
_disabled: set = set()


def search(query: str, log=print):
    """Interroge les moteurs jusqu'à obtenir des résultats. Journalise CHAQUE tentative."""
    global _last_search
    attempts = []
    # L'API passe avant tout le reste quand la clé est là : elle est fiable, et une découverte
    # fiable vaut mieux qu'une découverte qui dépend de l'humeur d'un moteur gratuit.
    api_urls, api_why = _brave_api(query)
    if api_urls is not None:
        attempts.append({"engine": "brave-api", "outcome": "OK" if api_urls else "VIDE",
                         "n": len(api_urls)})
        if api_urls:
            return api_urls, attempts
    else:
        attempts.append({"engine": "brave-api", "outcome": "SANS_CLÉ" if "absent" in (api_why or "")
                         else "BLOQUÉ", "why": api_why, "n": 0})
    for name, base in ENGINES:
        if name in _disabled:
            attempts.append({"engine": name, "outcome": "ÉCARTÉ",
                             "why": "bloqué plus tôt dans ce passage", "n": 0})
            continue
        wait = SEARCH_DELAY_S - (time.monotonic() - _last_search)
        if wait > 0:
            time.sleep(wait)
        _last_search = time.monotonic()
        st, body, why = fetch(base + urllib.parse.quote_plus(query))
        if st is None or st >= 400 or not body:
            attempts.append({"engine": name, "outcome": "BLOQUÉ", "why": why or f"HTTP {st}", "n": 0})
            _disabled.add(name)
            continue
        if CHALLENGE.search(body[:4000]) or "anomaly" in body[:6000].lower():
            attempts.append({"engine": name, "outcome": "BLOQUÉ", "why": "défi anti-robot", "n": 0})
            _disabled.add(name)
            continue
        urls = links_from(body)
        attempts.append({"engine": name, "outcome": "OK" if urls else "VIDE", "n": len(urls)})
        if urls:
            return urls, attempts
    return [], attempts


# ---------------------------------------------------------------- requêtes par format
def queries_for(fmt: str, upc: str | None) -> list[str]:
    """Nom exact, variantes de rédaction, puis UPC.

    Les variantes ne sont pas cosmétiques : un marchand écrit « 2023/24 », un autre « 23-24 »,
    un troisième met « NBA » à la place de « Basketball ». Chercher une seule graphie revient
    à ne chercher que chez ceux qui écrivent comme nous.
    """
    base = "2023-24 Panini Prizm Basketball"
    qs = [f"{base} {fmt} Box buy",
          f"2023/24 Panini Prizm {fmt} basketball box in stock"]
    if upc:
        qs.append(f'"{upc}" Panini Prizm {fmt}')
    return qs


def marketplace_queries(fmt: str) -> list[str]:
    """Les mêmes produits, cherchés explicitement sur les places de marché.

    Elles ne se laissent pas relire (403), donc rien de ce qu'on y trouve ne pourra être
    confirmé. Ce n'est pas une raison de ne pas chercher : savoir qu'une annonce eBay existe,
    à quel prix affiché et depuis quand, reste une information de marché — elle entre STALE,
    elle ne ment sur rien.
    """
    return [f"site:ebay.com 2023-24 Panini Prizm Basketball {fmt} Box",
            f"site:stockx.com 2023-24 Panini Prizm Basketball {fmt}"]


# Une URL de place de marché n'est retenue que si c'est une FICHE : une page de résultats de
# recherche n'est pas une annonce, et son contenu change à chaque visite.
MARKETPLACE_ITEM = re.compile(r"ebay\.[a-z.]+/(?:itm|p)/\d+|stockx\.com/[a-z0-9-]{8,}$", re.I)


MARKETPLACES = ("ebay.", "stockx.", "goldin.", "pwccmarketplace.", "comc.", "mercari.",
                "whatnot.", "alt.xyz", "amazon.", "walmart.")


def layer_of(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return "marketplace" if any(m in host for m in MARKETPLACES) else "web"


def seller_of(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def seller_type_of(url: str) -> str:
    return "MARKETPLACE" if layer_of(url) == "marketplace" else "RETAILER_EXTERNE"


# ---------------------------------------------------------------- balayage de domaines
# LE SECOND CANAL DE DÉCOUVERTE, ET LE PLUS SÛR
# ---------------------------------------------
# Aucun moteur de recherche généraliste ne nous est acquis : Brave rend d'excellents résultats
# puis bloque l'IP, Bing sert une page dégradée, DuckDuckGo et Mojeek opposent un défi. Faire
# reposer la découverte sur eux seuls, c'est accepter que « rien de nouveau » veuille dire
# « le moteur nous a fermé la porte » un jour sur deux.
#
# Ce canal-ci ne dépend d'aucun tiers : on tient un registre de domaines marchands connus mais
# NON enregistrés comme sources, et on lit leur catalogue par les mêmes API publiques que le
# crawler principal. La disponibilité y est une donnée structurée, pas une phrase devinée dans
# du HTML — donc CONFIRMED_LIVE y veut vraiment dire quelque chose.
#
# Un domaine n'entre au registre que PROUVÉ : découvert par une recherche qui a rendu une vraie
# fiche produit, ou déjà sondé et joignable. Le 05/09, quarante-quatre domaines européens ont
# été inventés et trente-huit n'existaient pas ; ce registre est la réponse à cet épisode —
# il porte la provenance et la date de chaque entrée, et un domaine injoignable y reste marqué
# injoignable au lieu de disparaître.
REGISTRY = OUT / "candidate_domains.json"


def load_registry(path: Path = REGISTRY) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"generated_at": None, "domains": []}


SWEEP_BUDGET_S = 45     # par domaine candidat : au-delà, on prend ce qu'on a et on avance


def read_catalog(base: str, budget_s: float = SWEEP_BUDGET_S):
    """Catalogue d'une boutique par ses API publiques. Shopify puis WooCommerce, jamais l'un
    ou l'autre : c'est la leçon Kutogo, appliquée ici comme dans le crawler principal.

    Chaque domaine a un budget de temps. Un catalogue de sept mille fiches ne doit pas pouvoir
    retarder les vingt autres — le passage entier a une durée à tenir, et un balayage partiel
    reste très supérieur à un balayage qu'on a dû interrompre en bloc.
    """
    import requests
    import hunt
    if not robots_ok(base + "/products.json"):
        return [], "robots.txt"
    s = requests.Session()
    s.headers["User-Agent"] = UA
    fin = time.monotonic() + budget_s
    for lecture, nom in ((hunt.shopify_products, "shopify"),
                         (hunt.woocommerce_products, "woocommerce")):
        try:
            prods, _ = lecture(base, s, fin)
        except hunt.ShopTimeout:
            return [], f"{nom} (budget épuisé)"
        except Exception:
            continue
        if prods:
            return prods, nom
        if time.monotonic() > fin:
            break
    return [], None


_SKUS = None


def identify(title: str):
    """Format et quantité d'un titre, par le matcher du moteur — pas par un second matcher.

    Deux pièges que la lecture naïve du titre ne voit pas, et qui mentent tous les deux sans
    rien casser :
      · « Hobby 12 Box Case » à 13 549 $ n'est pas une boîte Hobby à comparer aux 874 $ du
        marché — c'est douze boîtes, soit 1 129 $ l'unité ;
      · « Prizm NBA sealed pack. Retail Box. » à 8,99 $ est un sachet, pas une Retail Box.
    `hunt.match_title` et `hunt.parse_quantity` savent déjà tout cela, et sont testés pour.
    Réécrire ici une seconde logique d'identité garantirait seulement qu'elles divergent.
    """
    import hunt
    import yaml
    global _SKUS
    if _SKUS is None:
        _SKUS = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))["skus"]
    m = hunt.match_title(title, _SKUS)
    tn = hunt.norm(title)
    qty = max(1, hunt.parse_quantity(tn) or 1)
    fmt = None
    if m.sku_id:
        sku = next((x for x in _SKUS if x["id"] == m.sku_id), None)
        fmt = (sku or {}).get("format")
    return (fmt or fmt_of(title)), qty, m.sku_id


SWEEP_PAR_PASSAGE = 8   # domaines balayés par passage, les plus anciennement vus d'abord


def registered_hosts() -> set:
    """Les domaines déjà crawlés par hunt.py. Le balayage ne doit JAMAIS les rouvrir."""
    import yaml
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    return {seller_of(sh.get("base_url", "")) for sh in src["shops"]}


def sweep_domains(registry: dict, log=print, limit: int | None = SWEEP_PAR_PASSAGE,
                  deja_crawles: set | None = None):
    """DOMAIN SWEEP — lire le catalogue des marchands connus mais non enregistrés.

    Par ROTATION, du domaine vu il y a le plus longtemps au plus récent. Lire vingt et un
    catalogues complets coûte dix minutes ; en balayer huit en coûte quatre, et comme le run
    tourne toutes les six heures, chaque domaine est revu dans la journée. Un passage qui
    dépasse son budget finit coupé, et un balayage coupé ne couvre rien du tout.
    """
    import prizm_core
    # LA GARANTIE « UNE SEULE VISITE PAR PASSAGE », appliquée ici et pas seulement promise.
    # Un domaine peut entrer au registre un jour et devenir une source enregistrée le
    # lendemain ; sans ce filtre relu à chaque passage, il serait alors lu deux fois — par
    # hunt.py puis par le balayage — et la mission serait défaite en silence par une simple
    # ligne ajoutée à sources.yaml.
    deja = deja_crawles if deja_crawles is not None else registered_hosts()
    # Un domaine injoignable est mis de côté, PAS radié : on le réessaie une fois par semaine.
    # Une boutique en maintenance le jour du balayage ne doit pas disparaître pour toujours du
    # champ de recherche — c'est ainsi qu'on perd une source sans jamais s'en apercevoir.
    doms = [d for d in registry.get("domains", [])
            if d["domain"] not in deja
            and (d.get("reachable") is not False
                 or (_age_h(d.get("last_checked")) or 1e9) > 24 * 7)]
    doms.sort(key=lambda d: d.get("last_checked") or "")
    if limit:
        doms = doms[:limit]
    found, stats = [], {"domains_swept": 0, "domains_reachable": 0, "catalog_items": 0,
                        "hits": 0, "unreachable": [],
                        "ecartes_deja_crawles": sorted(
                            d["domain"] for d in registry.get("domains", []) if d["domain"] in deja)}
    for d in doms:
        base = d.get("base_url") or f"https://{d['domain']}"
        items, plat = read_catalog(base)
        stats["domains_swept"] += 1
        d["last_checked"] = now_iso()
        d["platform"] = plat or d.get("platform")
        d["n_catalog"] = len(items)
        d["reachable"] = bool(items)
        if not items:
            stats["unreachable"].append(d["domain"])
            log(f"  · {d['domain']:<30} aucun catalogue lisible")
            continue
        stats["domains_reachable"] += 1
        stats["catalog_items"] += len(items)
        n = 0
        for it in items:
            title = it.get("title", "")
            v = (it.get("variants") or [{}])[0]
            if not prizm_core.is_core(title, it.get("vendor_sku")):
                continue
            url = it.get("url") or f"{base}/products/{it.get('handle','')}"
            avail = bool(v.get("available"))
            fmt, qty, sku_id = identify(title)
            prix = float(v.get("price") or 0) or None
            raw = CONFIRMED_LIVE if avail else OOS
            found.append({"format": fmt, "first_seen": now_iso(), "last_checked": now_iso(),
                          "last_seen_live": now_iso() if avail else None,
                          # le prix affiché est TOUJOURS le total de l'offre ; l'unitaire en dérive
                          "quantity": qty, "sku_id": sku_id,
                          "unit_price": round(prix / qty, 2) if prix else None,
                          "price": prix,
                          "currency": d.get("currency", "USD"),
                          "seller": d["domain"], "seller_type": "RETAILER_EXTERNE",
                          "url": url,
                          "discovery_method": f"balayage catalogue · {plat}",
                          "stock_status": raw, "confidence": confidence_of(raw, None),
                          "layer": "web", "title_lu": title[:140],
                          "probe": {"raw": raw, "why": "disponibilité structurée de l'API"}})
            n += 1
        d["prizm_core_hits"] = n
        stats["hits"] += n
        log(f"  · {d['domain']:<30} {len(items):>5} fiches · {n:>2} Prizm core · {plat}")
    return found, stats


def fmt_of(title: str) -> str:
    """Le format porté par un titre, dans l'ordre du plus spécifique au plus générique.

    « Hobby » figure dans « International Hobby Box » : tester Hobby d'abord classerait toutes
    les boîtes internationales comme Hobby et mélangerait deux marchés dont les prix n'ont
    rien à voir — 334 $ contre 874 $.
    """
    t = title.lower()
    for f in ("FOTL", "First Off The Line", "International", "Fast Break", "Choice",
              "Retail Box", "Hanger", "Blaster", "Mega", "Hobby", "Pack"):
        if f.lower() in t:
            return "FOTL" if f != "FOTL" and "off the line" in f.lower() else f
    return "Inconnu"


def remember_domain(registry: dict, domain: str, base_url: str, why: str):
    """Ajoute un domaine PROUVÉ au registre, ou met à jour sa provenance."""
    for d in registry.setdefault("domains", []):
        if d["domain"] == domain:
            return d
    d = {"domain": domain, "base_url": base_url, "first_seen": now_iso(),
         "last_checked": None, "platform": None, "reachable": None,
         "n_catalog": None, "prizm_core_hits": None, "discovered_by": why}
    registry["domains"].append(d)
    return d


# ---------------------------------------------------------------- persistance
FIELDS = ("format", "first_seen", "last_checked", "last_seen_live", "price", "currency",
          "seller", "seller_type", "url", "discovery_method", "stock_status", "confidence")


def load_store(path: Path = STORE) -> dict:
    if not path.exists():
        return {"listings": []}
    return json.loads(path.read_text(encoding="utf-8"))


def migrate(rec: dict, seen_default: str) -> dict:
    """Amène une ligne de l'ancien schéma manuel au schéma d'observation.

    Les relevés du 06/09 n'avaient ni `first_seen` ni `last_checked` : ils portaient une date
    de constat et une disponibilité déclarée. On la lit comme un dernier live constaté — c'est
    ce qu'elle était — et la règle des 24 h fera le reste toute seule.
    """
    if "stock_status" in rec and "first_seen" in rec:
        return rec
    seen = rec.get("seen_at") or seen_default
    live = bool(rec.get("available"))
    return {"format": rec.get("format"),
            "first_seen": seen,
            "last_checked": rec.get("last_checked") or seen,
            "last_seen_live": seen if live else None,
            "price": rec.get("price"),
            "currency": rec.get("currency", "USD"),
            "seller": rec.get("seller") or seller_of(rec.get("url", "")),
            "seller_type": rec.get("seller_type") or seller_type_of(rec.get("url", "")),
            "url": rec.get("url"),
            "discovery_method": rec.get("discovery_method", "relevé manuel 06/09"),
            "stock_status": AMBIGUOUS,
            "confidence": "LOW",
            "layer": rec.get("layer") or layer_of(rec.get("url", "")),
            "country": rec.get("country"),
            "note": rec.get("note")}


def confidence_of(status: str, why: str | None) -> str:
    if status == CONFIRMED_LIVE:
        return "HIGH"
    if status in (OOS, LOST):
        return "HIGH" if not why else "MEDIUM"
    if status == PROBABLE_LIVE:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------- étape 1 : revalidation
def refresh_known(listings: list[dict], log=print) -> dict:
    """KNOWN URL REFRESH. Chaque URL connue est resondée, aucune n'est supprimée.

    Une annonce qui disparaît reste dans le fichier avec le statut LOST. L'effacer ferait
    perdre ce que nous savons d'un vendeur et d'un prix pratiqué — et une annonce disparue
    est une information de marché, pas un vide à balayer.
    """
    stats = {"checked": 0, "live_to_oos": [], "oos_to_live": [], "price_changes": [],
             "became_stale": [], "lost": [], "unreadable": 0}
    for rec in listings:
        url = rec.get("url")
        if not url:
            continue
        before = rec.get("stock_status") or AMBIGUOUS
        before_live = counts_as_live(before)
        raw, price, cur, title, why = probe(url)
        stats["checked"] += 1
        if raw == AMBIGUOUS:
            stats["unreadable"] += 1
        if raw in LIVE_STATES:
            rec["last_seen_live"] = now_iso()
        st = effective_status(raw, rec.get("last_seen_live"))
        old_price = rec.get("price")
        if price is not None and old_price is not None and abs(price - old_price) > 0.005:
            stats["price_changes"].append({"url": url, "de": old_price, "à": price,
                                           "format": rec.get("format")})
        if price is not None:
            rec["price"] = price
        if cur:
            rec["currency"] = cur
        rec["last_checked"] = now_iso()
        rec["stock_status"] = st
        rec["confidence"] = confidence_of(st, why)
        rec["probe"] = {"raw": raw, "why": why}
        after_live = counts_as_live(st)
        if before_live and not after_live and st != STALE:
            stats["live_to_oos"].append({"url": url, "statut": st, "format": rec.get("format")})
        if not before_live and after_live:
            stats["oos_to_live"].append({"url": url, "format": rec.get("format")})
        if st == STALE:
            stats["became_stale"].append({"url": url, "format": rec.get("format")})
        if st == LOST:
            stats["lost"].append({"url": url, "format": rec.get("format")})
        log(f"  {st:<15} {(rec.get('format') or '?'):<14} {seller_of(url):<28} "
            f"{('%.2f' % rec['price']) if rec.get('price') else '—':>9} {why or ''}")
    return stats


# ---------------------------------------------------------------- étape 2 : découverte
def discover(formats: dict, upc: dict, known_urls: set, skip_hosts: set, log=print,
             max_probe_per_format: int = 4, registry: dict | None = None) -> tuple[list[dict], dict]:
    """NEW LISTING DISCOVERY. Chercher ce que nous ne connaissons pas encore.

    Une URL trouvée n'est PAS une annonce : elle est sondée, et elle n'entre que si la fiche
    lue parle bien du produit. Le filtre d'identité est celui du moteur — `prizm_core.is_core`,
    le même que pour les boutiques enregistrées. Deux filtres différents pour un même produit
    finiraient par se contredire, et c'est toujours la production qui tranche mal.
    """
    import prizm_core
    news, stats = [], {"web_searches": 0, "marketplace_searches": 0, "engine_attempts": [],
                       "urls_seen": 0, "urls_probed": 0, "new_domains": [], "rejected": 0}
    for fmt in formats:
        cands = []
        log(f"  … {fmt}")
        requetes = ([(q, "web") for q in queries_for(fmt, upc.get(fmt))]
                    + [(q, "marketplace") for q in marketplace_queries(fmt)])
        for q, canal in requetes:
            urls, attempts = search(q, log=log)
            stats["engine_attempts"].append({"query": q, "format": fmt, "canal": canal,
                                             "attempts": attempts})
            stats["web_searches" if canal == "web" else "marketplace_searches"] += 1
            for u in urls:
                u = u.split("#")[0]
                host = seller_of(u)
                stats["urls_seen"] += 1
                if u in known_urls or host in skip_hosts:
                    continue
                # Un moteur dégradé rend n'importe quoi — Bing a servi des calendriers 2023
                # parce qu'il lit le tiret de « 2023-24 » comme un opérateur d'exclusion.
                # Le nom du produit doit figurer dans l'URL : le budget de sondage est court,
                # il va aux pages qui ont une chance d'être des fiches.
                if not RELEVANT.search(u):
                    continue
                if u not in [c[0] for c in cands]:
                    cands.append((u, q))
        for u, q in cands[:max_probe_per_format]:
            raw, price, cur, title, why = probe(u)
            stats["urls_probed"] += 1
            if layer_of(u) == "marketplace":
                # illisible par construction : on la garde si c'est une fiche identifiable,
                # et elle entre STALE — connue, datée, jamais comptée comme disponible
                if not MARKETPLACE_ITEM.search(u):
                    stats["rejected"] += 1
                    continue
                news.append({"format": fmt, "first_seen": now_iso(), "last_checked": now_iso(),
                             "last_seen_live": None, "price": price, "currency": cur or "USD",
                             "seller": seller_of(u), "seller_type": seller_type_of(u), "url": u,
                             "discovery_method": f"recherche marketplace · {q}",
                             "stock_status": STALE, "confidence": "LOW", "layer": "marketplace",
                             "probe": {"raw": raw, "why": why or "lecture refusée par le site"},
                             "title_lu": (title or "")[:140]})
                known_urls.add(u)
                log(f"  ✚ {STALE:<15} {fmt:<14} {seller_of(u):<28} (place de marché, non vérifiable)")
                continue
            if raw == LOST or not title:
                stats["rejected"] += 1
                continue
            if not prizm_core.is_core(title, None) or fmt.lower() not in title.lower():
                stats["rejected"] += 1
                continue
            st = effective_status(raw, now_iso() if raw in LIVE_STATES else None)
            rec = {"format": fmt, "first_seen": now_iso(), "last_checked": now_iso(),
                   "last_seen_live": now_iso() if raw in LIVE_STATES else None,
                   "price": price, "currency": cur or "USD",
                   "seller": seller_of(u), "seller_type": seller_type_of(u),
                   "url": u, "discovery_method": f"recherche web · {q}",
                   "stock_status": st, "confidence": confidence_of(st, why),
                   "layer": layer_of(u), "probe": {"raw": raw, "why": why},
                   "title_lu": title[:140]}
            news.append(rec)
            known_urls.add(u)
            if seller_of(u) not in skip_hosts:
                stats["new_domains"].append(seller_of(u))
                # un domaine qui vient de rendre une VRAIE fiche produit est prouvé : il entre
                # au registre et sera balayé à chaque passage, moteur de recherche ou non
                if registry is not None and layer_of(u) == "web":
                    remember_domain(registry, seller_of(u),
                                    f"https://{seller_of(u)}", f"recherche web · {q}")
            log(f"  ✚ {st:<15} {fmt:<14} {seller_of(u):<28} "
                f"{('%.2f' % price) if price else '—':>9} {title[:50]}")
    stats["new_domains"] = sorted(set(stats["new_domains"]))
    return news, stats


# ---------------------------------------------------------------- orchestration
def dedupe(listings: list[dict]) -> list[dict]:
    """Une URL = une annonce. Le balayage retrouve à chaque passage ce que la recherche avait
    trouvé la veille : sans cette fusion, le fichier grossirait de doublons et le compte de
    « live » serait faux du seul fait qu'on a cherché deux fois au même endroit."""
    par_url = {}
    for r in listings:
        u = (r.get("url") or "").split("#")[0]
        if not u:
            continue
        old = par_url.get(u)
        if not old:
            par_url[u] = r
            continue
        # on garde la plus ancienne première apparition et la vérification la plus récente
        fusion = dict(old)
        fusion.update({k: v for k, v in r.items() if v is not None})
        fusion["first_seen"] = min(x for x in (old.get("first_seen"), r.get("first_seen")) if x)
        for k in ("last_checked", "last_seen_live"):
            xs = [x for x in (old.get(k), r.get(k)) if x]
            fusion[k] = max(xs) if xs else None
        par_url[u] = fusion
    return list(par_url.values())


def main(argv=None):
    import yaml
    import prizm_core
    import hunt
    args = set(argv or sys.argv[1:])
    OUT.mkdir(exist_ok=True)
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    hunt.load_blocklist(src)
    # Les boutiques enregistrées sont déjà crawlées par hunt.py : les redécouvrir ici serait
    # exactement la deuxième visite que cette mission supprime.
    skip = {seller_of(sh.get("base_url", "")) for sh in src["shops"]}
    skip |= set(hunt.BLOCKLIST)

    store = load_store()
    listings = [migrate(r, store.get("generated_at", "2026-09-06")) for r in store.get("listings", [])]
    registry = load_registry()

    print("EXTERNAL WEB + MARKETPLACE — Prizm 2023-24\n")
    print(f"ÉTAPE 1 · KNOWN URL REFRESH — {len(listings)} annonce(s) connue(s)")
    rstats = refresh_known(listings)

    vide = {"web_searches": 0, "marketplace_searches": 0, "engine_attempts": [], "urls_seen": 0,
            "urls_probed": 0, "new_domains": [], "rejected": 0}
    news, dstats = [], dict(vide)
    swept, sstats = [], {"domains_swept": 0, "domains_reachable": 0, "catalog_items": 0,
                         "hits": 0, "unreachable": []}

    if "--refresh-only" not in args:
        print(f"\nÉTAPE 2 · NEW LISTING DISCOVERY (recherche) — {len(prizm_core.FORMATS)} format(s)")
        known = {r["url"] for r in listings if r.get("url")}
        news, dstats = discover(prizm_core.FORMATS, prizm_core.UPC, known, skip, registry=registry)

        print(f"\nÉTAPE 3 · NEW LISTING DISCOVERY (balayage catalogue) — "
              f"{SWEEP_PAR_PASSAGE} sur {len(registry.get('domains', []))} domaine(s) candidat(s), "
              f"par rotation")
        swept, sstats = sweep_domains(registry, deja_crawles=skip)

    listings = dedupe(listings + news + swept)
    registry["generated_at"] = now_iso()
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    par_etat = {st: sum(1 for r in listings if r["stock_status"] == st) for st in STATES}
    payload = {
        "generated_at": now_iso(),
        "method": ("automatique · KNOWN URL REFRESH, puis NEW LISTING DISCOVERY par recherche "
                   "web ET par balayage des catalogues candidats"),
        "stale_after_hours": STALE_H,
        "note": ("Une annonce non VÉRIFIÉE depuis plus de 24 h passe STALE : visible, datée, "
                 "mais ni live, ni meilleur prix, ni déclencheur d'achat. eBay, StockX et les "
                 "sites de cotation refusent toute lecture automatisée (403) — leurs annonces "
                 "ne peuvent donc pas être confirmées ici, et ne le prétendent pas."),
        "states": par_etat,
        "run": {"known_urls_checked": rstats["checked"],
                "unreadable": rstats["unreadable"],
                "web_searches": dstats["web_searches"],
                "marketplace_searches": dstats["marketplace_searches"],
                "domains_swept": sstats["domains_swept"],
                "ecartes_deja_crawles": sstats.get("ecartes_deja_crawles", []),
                "domains_reachable": sstats["domains_reachable"],
                "catalog_items_read": sstats["catalog_items"],
                "new_domains": dstats["new_domains"],
                "new_listings": len(news) + len(swept),
                "new_by_search": len(news),
                "new_by_sweep": len(swept),
                "price_changes": rstats["price_changes"],
                "live_to_oos": rstats["live_to_oos"],
                "oos_to_live": rstats["oos_to_live"],
                "became_stale": rstats["became_stale"],
                "lost": rstats["lost"],
                "urls_seen": dstats["urls_seen"],
                "urls_probed": dstats["urls_probed"],
                "rejected": dstats["rejected"],
                "engine_attempts": dstats["engine_attempts"]},
        "listings": listings,
    }
    STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    live = [r for r in listings if counts_as_live(r["stock_status"])]
    print(f"\n{len(listings)} annonce(s) · {len(live)} live · "
          f"{par_etat[STALE]} STALE · {par_etat[LOST]} LOST · {par_etat[OOS]} OOS")
    print(f"{rstats['checked']} URL revérifiées · {dstats['web_searches']} recherche(s) · "
          f"{sstats['domains_swept']} domaine(s) balayé(s) · "
          f"{len(news) + len(swept)} nouvelle(s) annonce(s) → {STORE}")
    return payload


if __name__ == "__main__":
    main()
