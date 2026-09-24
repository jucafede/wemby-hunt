#!/usr/bin/env python3
"""OFFRES — la relation produit × boutique, et son histoire.

TROIS OBJETS, TROIS RESPONSABILITÉS
-----------------------------------
PRODUCT  `mega_targets.py`  — l'identité canonique. Cinq références, leurs UPC, leurs
                              configurations. Elle ne bouge pas.
SHOP     `sources.yaml`     — l'identité du vendeur : pays, devise, plateforme, confiance,
                              conformité robots. Une boutique existe indépendamment de ce
                              qu'elle vend.
OFFER    ce fichier          — ce qu'UNE boutique propose d'UN produit, à un moment. C'est le
                              seul des trois qui change tout le temps, et le seul qui a une
                              histoire.

Avant cette séparation, `mega_targets_watch.json` recopiait l'UPC et la configuration dans
chaque offre : cinq produits × N boutiques, et autant d'occasions qu'une correction d'UPC ne
soit appliquée qu'à moitié.

POURQUOI LES RUPTURES SONT CONSERVÉES
-------------------------------------
Une fiche épuisée n'est pas un échec de collecte, c'est une connaissance : elle dit qu'une
boutique RÉFÉRENCE ce produit, à quel prix elle l'a proposé, et elle permet de détecter le
restock. e5sports à 82 € rendu est en rupture aujourd'hui — c'est pourtant l'offre qu'il faudra
prendre le jour où elle revient, 36 % sous la seule disponible.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
OFFERS = ROOT / "discovered" / "offers.json"

CHAMPS = ("product_id", "shop_id", "url", "price", "currency", "stock_status", "stock_qty",
          "shipping_france", "shipping_cost", "landed_price_france", "match_method",
          "confidence", "first_seen", "last_seen", "last_in_stock", "last_price")

IN_STOCK, OUT_OF_STOCK, AMBIGU = "IN_STOCK", "OUT_OF_STOCK", "AMBIGU"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def charge() -> dict:
    if OFFERS.exists():
        return json.loads(OFFERS.read_text(encoding="utf-8"))
    return {"generated_at": None, "offers": []}


def sauve(d: dict):
    d["generated_at"] = now()
    d["note"] = ("OFFER = relation produit × boutique, datée. L'identité produit vit dans "
                 "mega_targets.py, l'identité boutique dans sources.yaml : rien n'est recopié "
                 "ici. Les ruptures sont CONSERVÉES — elles portent l'historique de prix et "
                 "permettent la détection de restock.")
    d["champs"] = list(CHAMPS)
    OFFERS.parent.mkdir(exist_ok=True)
    OFFERS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def cle(o: dict) -> tuple:
    return (o.get("product_id"), o.get("shop_id"), (o.get("url") or "").split("?")[0])


def upsert(d: dict, neuve: dict) -> str:
    """Insère ou met à jour une offre, en conservant son histoire.

    Rend l'événement observé : NEW, RESTOCK, SOLD_OUT, PRICE_DROP, PRICE_UP ou UNCHANGED.
    C'est cette valeur, et non le simple fait d'avoir vu la fiche, qui mérite une alerte.
    """
    t = now()
    neuve["url"] = (neuve.get("url") or "").split("?")[0]
    k = cle(neuve)
    for o in d["offers"]:
        if cle(o) == k:
            evt = "UNCHANGED"
            av_stock, av_prix = o.get("stock_status"), o.get("price")
            if neuve.get("stock_status") == IN_STOCK and av_stock != IN_STOCK:
                evt = "RESTOCK"
            elif neuve.get("stock_status") == OUT_OF_STOCK and av_stock == IN_STOCK:
                evt = "SOLD_OUT"
            elif (neuve.get("price") and av_prix and neuve["price"] < av_prix * 0.98):
                evt = "PRICE_DROP"
            elif (neuve.get("price") and av_prix and neuve["price"] > av_prix * 1.02):
                evt = "PRICE_UP"
            o["last_price"] = av_prix
            o.update({k2: v for k2, v in neuve.items() if v is not None})
            o["last_seen"] = t
            if neuve.get("stock_status") == IN_STOCK:
                o["last_in_stock"] = t
            o.setdefault("history", []).append(
                {"t": t, "price": neuve.get("price"), "stock_status": neuve.get("stock_status"),
                 "stock_qty": neuve.get("stock_qty"), "event": evt})
            return evt
    neuve.update({"first_seen": t, "last_seen": t, "last_price": None,
                  "last_in_stock": t if neuve.get("stock_status") == IN_STOCK else None,
                  "history": [{"t": t, "price": neuve.get("price"),
                               "stock_status": neuve.get("stock_status"),
                               "stock_qty": neuve.get("stock_qty"), "event": "NEW"}]})
    d["offers"].append(neuve)
    return "NEW"


def shops() -> dict:
    return {s["key"]: s for s in
            yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["shops"]}


def resume() -> dict:
    d = charge()
    par_etat = {}
    for o in d["offers"]:
        par_etat[o.get("stock_status")] = par_etat.get(o.get("stock_status"), 0) + 1
    return {"offres": len(d["offers"]), "par_etat": par_etat,
            "produits_couverts": len({o["product_id"] for o in d["offers"] if o.get("product_id")}),
            "boutiques": len({o["shop_id"] for o in d["offers"]})}


# ---------------------------------------------------------------- dire ce qu'on ne sait pas
def formule_absence(n_boutiques: int, canaux_bloques: list | None = None) -> str:
    """La seule phrase honnête quand une recherche ne rend rien.

    « Aucune fiche sur 55 boutiques : ce n'est pas un défaut de couverture » était faux, et
    d'une façon qui compte : nous ne POUVONS pas le savoir. CardVault by Tom Brady existait,
    vendait du scellé, et n'était dans aucun registre — sa découverte a démontré l'inverse le
    jour même.

    Un registre n'est pas un marché. « 0 résultat chez les vendeurs que nous interrogeons » ne
    devient jamais « introuvable » : la première phrase décrit notre outil, la seconde
    prétendrait décrire le monde.
    """
    txt = (f"Aucune offre trouvée dans le périmètre actuellement couvert "
           f"({n_boutiques} boutiques interrogées).")
    if canaux_bloques:
        txt += (" Canaux fermés à la lecture automatisée : "
                + ", ".join(canaux_bloques) + ".")
    txt += (" Notre couverture est incomplète par construction — ce résultat ne dit rien de "
            "la disponibilité réelle du produit sur le marché.")
    return txt


ABSENCE_INTERDITE = ("introuvable", "n'existe pas", "aucun vendeur ne", "indisponible partout",
                     "ce n'est pas un défaut de couverture", "nulle part")
