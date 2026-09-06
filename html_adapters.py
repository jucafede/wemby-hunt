#!/usr/bin/env python3
"""Collecteurs HTML — un adaptateur concret par boutique.

Pas de framework générique. Six boutiques, six adaptateurs, chacun écrit contre le HTML réel
de son site : c'est plus court à lire, plus facile à corriger quand un site change, et ça ne
prétend pas anticiper des structures qu'on n'a jamais vues.

Un adaptateur ne fait que DEUX choses :
  enumerate(fetch)  -> les URL de fiches produit à visiter, déjà filtrées sur le basket
  parse(html, url)  -> {"title", "price", "currency", "available"} ou None

Tout le reste — matching, sealed gate, garde-fous, cloisons, verdicts — reste le travail du
moteur, strictement inchangé. Un adaptateur qui rend un titre et un prix a fini son travail.

RÈGLES DE COLLECTE, valables pour tous :
  · robots.txt fait foi. Une boutique qui interdit notre agent n'est pas crawlée, point.
  · une requête par seconde et par boutique, jamais plus.
  · pas de contournement de protection anti-robot. Un site derrière un défi Cloudflare est
    considéré comme fermé : c'est un refus explicite, on ne le discute pas.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field

# Filtre de slug commun : on ne visite une fiche que si son URL promet du basket. Sur
# shopuscards, il ramène 271 fiches sur 513 — 4,5 min de collecte au lieu de 8,5.
BASKET_SLUG = re.compile(
    r"basketball|\bnba\b|prizm|mosaic|hoops|optic|donruss|select|contenders|revolution|"
    r"chrome|bowman|court-kings|phoenix|premium-stock|origins|immaculate|flawless|"
    r"national-treasures|obsidian|spectra|noir|crown-royale|recon|absolute|luminance|"
    r"signature-class|instant|monopoly|finest|topps", re.I)

# Les slugs qui promettent explicitement un AUTRE sport priment sur le filtre ci-dessus :
# « select-road-to-fifa-world-cup-soccer » contient « select » sans être du basket.
OTHER_SPORT_SLUG = re.compile(
    r"soccer|football|fifa|baseball|hockey|\bnfl\b|\bmlb\b|\bnhl\b|wnba|pokemon|ufc|"
    r"wrestling|\bwwe\b|f1|nascar|golf|tennis|marvel|harry-potter|star-wars|disney", re.I)


def basket_slug(url: str) -> bool:
    """Premier tamis, sur l'URL seule, avant toute requête. Volontairement large : il économise
    des requêtes, il ne décide rien. Le vrai tri reste le matcher, sur le titre complet."""
    return bool(BASKET_SLUG.search(url)) and not OTHER_SPORT_SLUG.search(url)


# ---------------------------------------------------------------- lecture du JSON-LD
def jsonld_products(html: str):
    """Rend les blocs schema.org Product d'une page. C'est de la donnée structurée publiée
    POUR les machines : quand elle existe, on la lit plutôt que de deviner des sélecteurs CSS
    qui casseront au prochain changement de thème."""
    out = []
    for m in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                        html, re.S | re.I):
        try:
            d = json.loads(m)
        except Exception:
            continue
        for node in (d if isinstance(d, list) else [d]):
            if isinstance(node, dict) and node.get("@type") == "Product":
                out.append(node)
    return out


def from_jsonld(html: str):
    """{"title","price","currency","available"} depuis le premier Product trouvé, sinon None.

    Un prix absent ou nul n'est PAS un prix : la fiche est rendue sans prix et le moteur la
    marquera NO_PRICE. On ne devine jamais un montant."""
    for p in jsonld_products(html):
        offers = p.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        name = (p.get("name") or "").strip()
        if not name:
            continue
        try:
            price = float(offers.get("price"))
        except (TypeError, ValueError):
            price = None
        avail = str(offers.get("availability") or "").lower()
        return {"title": name, "price": price,
                "currency": (offers.get("priceCurrency") or "USD").upper(),
                # « InStock » et « LimitedAvailability » sont achetables ; PreOrder ne l'est pas
                # au sens où nous l'entendons — c'est une promesse, pas une boîte.
                "available": ("instock" in avail or "limitedavailability" in avail)}
    return None


def sitemap_urls(xml: str):
    """URL d'un sitemap. C'est le point d'entrée le plus respectueux qui soit : un fichier que
    la boutique publie elle-même à l'intention des robots."""
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


# ---------------------------------------------------------------- adaptateurs
@dataclass
class Adapter:
    key: str
    name: str
    base_url: str
    currency: str = "USD"
    market_region: str = "US"
    # pages de départ : sitemap(s) ou pages de listing catégorie
    seeds: list = field(default_factory=list)
    seed_kind: str = "sitemap"          # "sitemap" | "listing"
    product_re: str = r"/products/"     # ce qui distingue une fiche produit d'une autre URL
    parse_fn: str = "jsonld"            # stratégie de lecture d'une fiche
    max_pages: int = 400                # plafond dur de fiches visitées par passage
    notes: str = ""

    def enumerate(self, fetch):
        """fetch(url) -> texte, ou None. Rend les URL de fiches à visiter, filtrées basket."""
        seen, out = set(), []
        for seed in self.seeds:
            body = fetch(seed)
            if not body:
                continue
            urls = (sitemap_urls(body) if self.seed_kind == "sitemap"
                    else re.findall(r'href="(https?://[^"]+)"', body))
            for u in urls:
                if not re.search(self.product_re, u):
                    continue
                u = u.split("?")[0].rstrip("/")
                if u in seen or not basket_slug(u):
                    continue
                seen.add(u)
                out.append(u)
        return out[:self.max_pages]

    def parse(self, html: str, url: str):
        if self.parse_fn == "jsonld":
            return from_jsonld(html)
        if self.parse_fn == "stickerpoint":
            return stickerpoint_listing(html)   # rend une LISTE : le listing porte les fiches
        raise ValueError(f"stratégie de lecture inconnue : {self.parse_fn}")


# --- (d) ShopUSCards — Ecwid / Lightspeed, boutique FR, alimente la couche FR --------------
# Les fiches portent un schema.org Product complet (nom, prix, devise, disponibilité). Le
# sitemap liste 513 produits ; le filtre de slug en retient 271, soit 4,5 min à 1 req/s.
SHOPUSCARDS = Adapter(
    key="shopuscards",
    name="ShopUSCards",
    base_url="https://shopuscards.eu",
    currency="EUR",
    market_region="FR",
    seeds=["https://shopuscards.eu/sitemap.xml"],
    seed_kind="sitemap",
    product_re=r"/products/",
    parse_fn="jsonld",
    notes="Ecwid (ec-instant-site), boutique id 32676041. robots.txt : aucune directive visant "
          "notre agent, seules les pages panier/compte/paiement sont interdites.",
)

# --- Stickerpoint — osCommerce, spécialiste stickers/albums FR/DE/CH -----------------------
# La boutique qui a déclenché la mission du 06/09 : 43 de ses 52 références NBA sont épuisées,
# et ce qui reste est du fond de rayon que personne ne surveillait.
#
# Ni JSON ni schema.org : du osCommerce classique. La fiche se lit dans la page de LISTING,
# ce qui évite une requête par produit — deux pages pour tout le rayon NBA.
#   lien + nom     <a class="prod_list" href="...-p-<id>.html">Nom</a>
#   prix normal    <span class="productPrice">3,50&nbsp;€</span>
#   prix barré     <span class="productSpecialPrice">   promotion en cours
#   rupture        le libellé « ÉPUISÉ » dans la carte produit
STICKERPOINT_CATS = [
    "https://www.stickerpoint.fr/panini-nba-stickers-cards-c-1_98.html",
    "https://www.stickerpoint.fr/panini-nba-top-class-c-1_251.html",
]

_SP_CARD = re.compile(r'class="[^"]*wrapper_prods[^"]*"(.*?)(?=class="[^"]*wrapper_prods|\Z)', re.S)
_SP_LINK = re.compile(r'<a[^>]+class="prod_list"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SP_PRICE = re.compile(r'class="(productPrice|productSpecialPrice)"[^>]*>\s*([0-9]+[.,][0-9]{2})')
_SP_OOS = re.compile(r"[ée]puis[ée]|ausverkauft|sold\s*out", re.I)


def stickerpoint_listing(html_text: str):
    """Toutes les fiches d'une page de listing osCommerce.

    Un prix barré signifie promotion : c'est le prix SPÉCIAL qui est payable, l'autre n'est
    qu'un tarif de référence. Les confondre ferait passer une promo pour un prix normal — et
    fabriquerait de faux plus-bas historiques."""
    import html as _h
    out = []
    for m in _SP_CARD.finditer(html_text):
        blk = m.group(1)
        lk = _SP_LINK.search(blk)
        if not lk:
            continue
        name = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", "", lk.group(2)))).strip()
        prices = _SP_PRICE.findall(blk)
        if not name or not prices:
            continue
        special = next((p for k, p in prices if k == "productSpecialPrice"), None)
        normal = next((p for k, p in prices if k == "productPrice"), None)
        payable = special or normal
        out.append({"title": name, "price": float(payable.replace(",", ".")),
                    "list_price": float(normal.replace(",", ".")) if (special and normal) else None,
                    "on_sale": bool(special), "currency": "EUR",
                    "available": not bool(_SP_OOS.search(blk)),
                    "url": lk.group(1).strip()})
    return out


STICKERPOINT = Adapter(
    key="stickerpoint", name="Stickerpoint", base_url="https://www.stickerpoint.fr",
    currency="EUR", market_region="FR",
    seeds=STICKERPOINT_CATS, seed_kind="listing",
    product_re=r"-p-\d+\.html", parse_fn="stickerpoint",
    notes="osCommerce, décliné en .fr/.de/.ch. Les fiches se lisent depuis le listing : deux "
          "pages suffisent pour tout le rayon NBA, au lieu d'une requête par produit.",
)

ADAPTERS = {a.key: a for a in (SHOPUSCARDS, STICKERPOINT)}


def adapter_for(shop_key: str):
    return ADAPTERS.get(shop_key)
