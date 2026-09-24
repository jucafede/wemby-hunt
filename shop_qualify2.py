#!/usr/bin/env python3
"""SECONDE PASSE — qualifier sans API propriétaire.

CE QUE LA PREMIÈRE PASSE A CONFONDU
-----------------------------------
« Pas d'API lisible » a été traité comme un rejet commercial. C'est faux : une boutique dont
le catalogue n'expose pas de JSON reste une boutique, et peut très bien vendre du basket
scellé sur des pages HTML parfaitement publiques. Quarante candidats ont été écartés sur ce
malentendu.

Pire, le rejet mélangeait deux axes qui n'ont rien à voir :
  LÉGITIMITÉ    — ce marchand est-il réel et sérieux ?
  CRAWLABILITÉ  — savons-nous lire son catalogue automatiquement ?
Une boutique TRUSTED + MANUAL_ONLY est parfaitement exploitable : elle demande un relevé
humain, pas un renoncement. Le vieux LCS qui publie son « Box Inventory » en tableau HTML et
prend les commandes par e-mail en est l'exemple même — et c'est précisément le profil qui
garde du stock 2023-24 à son ancien prix.

CE MODULE NE CONTOURNE RIEN
---------------------------
robots.txt reste souverain. On lit ce qui est autorisé : page d'accueil, sitemap, pages de
catégories, fiches produit publiques, JSON-LD. Un site qui nous interdit reste BLOCKED.
"""
from __future__ import annotations
import json, re, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import external_engine as xe
from shop_discovery import BASKET, SCELLE, PAS_DES_CARTES, domaine

ROOT = Path(__file__).parent

# --- axe 1 : légitimité du marchand
TRUSTED, LIKELY_LEGIT, UNVERIFIED, SUSPICIOUS = "TRUSTED", "LIKELY_LEGIT", "UNVERIFIED", "SUSPICIOUS"
# --- axe 2 : ce que nous savons lire
FULL, PARTIAL, MANUAL_ONLY, BLOCKED = "FULL", "PARTIAL", "MANUAL_ONLY", "BLOCKED"
# --- comment on achète réellement
ONLINE_CART, MAIL_ORDER, PHONE_ORDER, IN_STORE_ONLY = ("ONLINE_CART", "MAIL_ORDER",
                                                       "PHONE_ORDER", "IN_STORE_ONLY")
UNVERIFIED_NOT_CRAWLABLE = "UNVERIFIED_NOT_CRAWLABLE"
# Le marchand n'a rien répondu que nous ayons pu lire : 429, 503, timeout, page vide. Ce
# n'est ni un refus (robots l'aurait dit) ni une absence de basket — c'est une ignorance, et
# elle doit porter un nom à elle. Sans ce statut, « rien lu » retombait dans
# REJECTED_NO_BASKETBALL, et sandssportscards — prouvée par son API la veille — ressortait
# comme une boutique qui ne vend pas de basketball.
UNKNOWN_NOT_READ = "UNKNOWN_NOT_READ"

# Les signatures du vieux LCS en vente par correspondance — le profil « RK Collectibles ».
MAIL = re.compile(r"box\s*inventory|boxes?\s*(?:&|and)\s*cases?|wax\s*inventory|sealed\s*wax|"
                  r"mail\s*order|basketball\s*boxes|basketball\s*wax|boxes?\s*in\s*stock|"
                  r"call\s*to\s*order|e-?mail\s*to\s*order|call\s*for\s*(?:price|availability)|"
                  r"shipping\s*available|we\s*ship", re.I)
PANIER = re.compile(r"add\s*to\s*cart|add-to-cart|/cart\b|checkout|buy\s*now|shop\s*pay", re.I)
TEL = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
MAILTO = re.compile(r"mailto:([^\"'?\s]+)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pages_publiques(base: str, limite: int = 8) -> list:
    """Les surfaces PUBLIQUES et autorisées : accueil, sitemap, catégories plausibles."""
    vues, pages = set(), []
    st, b, _ = xe.fetch(base, timeout=14)
    if st == 200 and b:
        pages.append((base, b)); vues.add(base)
    # le sitemap dit ce que le marchand veut voir indexé : c'est la meilleure porte d'entrée
    for smu in (f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"):
        st2, s2, _ = xe.fetch(smu, timeout=14)
        if st2 == 200 and s2 and "<loc>" in s2:
            locs = re.findall(r"<loc>([^<]+)</loc>", s2)
            # d'abord les URLs qui sentent le basket ou le scellé
            pri = [u for u in locs if re.search(r"basketball|panini|prizm|box|wax|sealed|nba", u, re.I)]
            for u in (pri or locs)[:limite]:
                if u in vues or u.endswith((".jpg", ".png", ".webp", ".pdf", ".xml")):
                    continue
                st3, b3, _ = xe.fetch(u, timeout=12)
                if st3 == 200 and b3:
                    pages.append((u, b3)); vues.add(u)
                if len(pages) >= limite:
                    break
            break
    return pages


def qualifie2(dom: str) -> dict:
    """Seconde passe : légitimité, mode d'achat et crawlabilité, sur surfaces publiques."""
    base = f"https://{dom}"
    r = {"domain": dom, "checked_at": now(), "legitimacy": UNVERIFIED,
         "crawlability": None, "purchase_mode": None, "basketball": False,
         "sealed_basketball": False, "saison_2023_24": False, "evidence": None,
         "hunt_enabled": False, "status": None, "reason": None, "signaux": []}

    if not xe.robots_ok(base + "/"):
        r.update(crawlability=BLOCKED, status="BLOCKED", robots_forbids=True,
                 reason="robots.txt nous interdit ce site — respecté, non contourné")
        return r
    r["robots_forbids"] = False

    pages = pages_publiques(base)
    if not pages:
        # NE PAS confondre « le site nous interdit » et « nous n'avons rien su lire ». Le
        # premier est un veto, le second une ignorance — et traiter le second comme un veto
        # a fait retomber sandssportscards, pourtant prouvée par son API, en non vérifiée.
        r.update(crawlability=MANUAL_ONLY, status="UNREADABLE_HTML", pages_lues=0,
                 reason="aucune page publique lisible — la passe API reste seule juge")
        return r
    r["pages_lues"] = len(pages)

    blob = " ".join(b for _, b in pages)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", blob))

    # --- légitimité : ce qui prouve un vrai commerçant
    sig = []
    if TEL.search(txt): sig.append("téléphone")
    if MAILTO.search(blob): sig.append("e-mail")
    if re.search(r"\b[A-Z]{2}\s*\d{5}\b", txt): sig.append("adresse postale")
    if re.search(r"about\s*us|our\s*store|since\s*(19|20)\d{2}|family\s*owned", txt, re.I):
        sig.append("page à propos")
    if re.search(r"return\s*polic|refund|terms\s*(?:of|&)\s*(?:service|conditions)|privacy", txt, re.I):
        sig.append("CGV/retours")
    r["signaux"] = sig
    r["legitimacy"] = (TRUSTED if len(sig) >= 4 else LIKELY_LEGIT if len(sig) >= 2 else UNVERIFIED)

    # --- comment on achète
    if PANIER.search(blob):
        r["purchase_mode"] = ONLINE_CART
    elif MAIL.search(txt) and MAILTO.search(blob):
        r["purchase_mode"] = MAIL_ORDER
    elif MAIL.search(txt) and TEL.search(txt):
        r["purchase_mode"] = PHONE_ORDER
    else:
        r["purchase_mode"] = IN_STORE_ONLY

    # --- le produit : basket ET scellé, prouvés sur une page publique
    prod = []

    def garde(t, u):
        t = re.sub(r"\s+", " ", t).strip()
        if BASKET.search(t) and SCELLE.search(t) and not PAS_DES_CARTES.search(t):
            prod.append({"titre": t[:140], "page": u})

    for u, b in pages:
        # HTML : titres, liens, intitulés
        for m in re.finditer(r"<(?:h[1-4]|a|title|span|li|td)[^>]*>([^<]{12,140})</", b):
            garde(m.group(1), u)
        # JSON-LD : ce que le marchand publie pour Google
        for nm in re.findall(r'"name"\s*:\s*"([^"]{12,140})"', b):
            garde(nm, u)
        # SITEMAP PRODUITS : le catalogue COMPLET, et c'est souvent la seule surface
        # exploitable d'une boutique sans API. Le titre y vit dans <image:title>, et à
        # défaut dans le slug de l'URL.
        for nm in re.findall(r"<image:title>(?:<!\[CDATA\[)?([^<\]]{12,140})", b):
            garde(nm, u)
        for loc in re.findall(r"<loc>([^<]*/products?/[^<]+)</loc>", b):
            slug = loc.rstrip("/").split("/")[-1].replace("-", " ")
            garde(slug, loc)
    # BASKET exclut dès qu'un AUTRE sport est nommé — c'est juste sur le titre d'un produit,
    # mais faux sur le texte entier d'une page : chez un multi-sports, « football » figure
    # toujours quelque part, et le basket disparaissait. La présence du sport se mesure donc
    # sur un mot de basket, pas sur la règle d'exclusion réservée aux titres.
    from shop_discovery import _BASKET_MOT
    r["basketball"] = bool(prod) or bool(_BASKET_MOT.search(txt))
    if prod:
        r["sealed_basketball"] = True
        r["evidence"] = {"product_name": prod[0]["titre"][:120], "product_url": prod[0]["page"],
                         "source": "page HTML publique / JSON-LD"}
        r["saison_2023_24"] = any(re.search(r"2023[-/ ]?24|23[-/]24", p["titre"]) for p in prod)

    r["crawlability"] = (FULL if r["purchase_mode"] == ONLINE_CART and prod else
                         PARTIAL if prod else MANUAL_ONLY)

    if not r["basketball"]:
        r.update(status="REJECTED_NO_BASKETBALL", reason="aucun basketball sur les pages publiques")
    elif not r["sealed_basketball"]:
        r.update(status="REJECTED_NO_SEALED",
                 reason="basketball présent, aucun scellé prouvé sur page publique")
    elif r["purchase_mode"] == IN_STORE_ONLY:
        r.update(status="IN_STORE_ONLY",
                 reason="basket scellé présent mais aucune vente à distance identifiable")
    else:
        r.update(status="QUALIFIED", hunt_enabled=True,
                 reason=f"basket scellé prouvé · achat {r['purchase_mode']} · lecture {r['crawlability']}")
    return r


def fusionne(pass1: dict, pass2: dict) -> dict:
    """Le verdict final prend le MEILLEUR des deux passes, jamais le dernier en date.

    Une boutique prouvée par son API ne cesse pas de vendre du basket scellé parce que ses
    pages HTML sont avares. Écraser la première passe par la seconde a fait retomber
    sandssportscards — dont l'API avait pourtant rendu une Prizm Basketball Blaster Box — dans
    les rejets. Les deux passes sont deux fenêtres sur le même marchand : on garde ce que
    l'une OU l'autre a établi.
    """
    scelle = bool(pass1.get("sealed_basketball")) or bool(pass2.get("sealed_basketball"))
    basket = bool(pass1.get("basketball")) or bool(pass2.get("basketball"))
    preuve = pass1.get("evidence") or pass2.get("evidence")
    api = bool(pass1.get("crawlable"))
    craw = (FULL if api and scelle else
            pass2.get("crawlability") or (MANUAL_ONLY if scelle else None))
    if pass2.get("crawlability") == BLOCKED and not api:
        craw = BLOCKED
    achat = pass2.get("purchase_mode")
    if api and pass1.get("ecommerce") and achat in (None, IN_STORE_ONLY):
        achat = ONLINE_CART      # une API de panier EST une vente à distance

    # A-t-on seulement LU quelque chose ? Un verdict produit suppose une lecture ; sans elle,
    # « pas de basket » ne décrit pas le marchand, il décrit notre échec.
    lu = bool(pass1.get("website_accessible") or pass1.get("crawlable")
              or pass2.get("pages_lues"))
    if pass2.get("robots_forbids") and not api:
        st, why = UNVERIFIED_NOT_CRAWLABLE, "robots.txt nous interdit — candidate non vérifiée"
    elif not lu:
        st = UNKNOWN_NOT_READ
        why = ("aucune lecture aboutie — " + (pass1.get("reason") or "site sans réponse")
               + " · ni basket ni scellé ne sont JUGÉS : ils sont INCONNUS")
    elif not basket:
        st, why = "REJECTED_NO_BASKETBALL", "aucun basketball sur aucune des deux passes"
    elif not scelle:
        st, why = "REJECTED_NO_SEALED", "basketball présent, aucun scellé prouvé"
    elif achat == IN_STORE_ONLY:
        st, why = "IN_STORE_ONLY", "scellé présent mais aucune vente à distance identifiable"
    else:
        st, why = QUALIFIED_S, f"basket scellé prouvé · achat {achat} · lecture {craw}"
    return {"status": st, "reason": why, "legitimacy": pass2.get("legitimacy", UNVERIFIED),
            "crawlability": craw, "purchase_mode": achat, "lu": lu,
            # Sans lecture, on ne renvoie pas False — on renvoie None. False dirait « non ».
            "basketball": basket if lu else None,
            "sealed_basketball": scelle if lu else None, "evidence": preuve,
            "saison_2023_24": bool(pass2.get("saison_2023_24")),
            "hunt_enabled": st in (QUALIFIED_S,),
            "prouve_par": ("api" if pass1.get("sealed_basketball") else
                           "html_public" if pass2.get("sealed_basketball") else None)}


QUALIFIED_S = "QUALIFIED"
