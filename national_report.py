#!/usr/bin/env python3
"""Le rapport de la phase nationale, dans l'ordre demandé.

Une règle tient toute la mise en forme : aucune ligne ne doit pouvoir se lire comme un
jugement que nous n'avons pas les moyens de porter. Un domaine non inspecté, un robots.txt
qui refuse, un rang au-delà de 100 : ce sont des lectures manquantes, et le rapport les
nomme comme telles au lieu de les taire ou de les convertir en rejets.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).parent
IDX = ROOT / "discovered" / "national_index.json"
PRI = ROOT / "discovered" / "national_priority.json"
TOP = ROOT / "discovered" / "national_top100.json"

# Ce qu'on ne peut pas écrire : des conclusions que la couverture ne soutient pas.
INTERDITS = ("introuvable", "aucun vendeur", "indisponible partout", "nulle part",
             "n'existe pas", "ce n'est pas un défaut de couverture")


def charge(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def ligne(*cols, w=None):
    return "  ".join(str(c)[:x].ljust(x) for c, x in zip(cols, w))


def rapport() -> str:
    idx, pri, top = charge(IDX), charge(PRI), charge(TOP)
    L = []
    A = L.append

    A("NATIONAL DISCOVERY")
    A("=" * 70)
    n = idx.get("compte_par_nature", {})
    A(f"CardShopMap shop listings : {idx.get('fiches_lues', 0)}")
    A(f"With website              : {idx.get('fiches_avec_site', 0)}")
    A(f"Unique merchant domains   : {idx.get('domaines_uniques', 0)}")
    A(f"Sans site publié          : {idx.get('fiches_sans_site', 0)}"
      "   (l'annuaire n'en publie pas — pas « n'a pas de site »)")
    A(f"Fiches illisibles         : {idx.get('fiches_illisibles', 0)}")
    A("")
    A("Exclus de l'index (et pourquoi) :")
    A(f"  événements / card shows : {n.get('evenements', 0)}")
    A(f"  pages d'État            : {n.get('pages_etat', 0)}")
    A(f"  pages de ville          : {n.get('pages_ville', 0)}")
    A(f"  pages de rubrique       : {n.get('categories', 0)}")
    A(f"  autres pages du site    : {n.get('autres', 0)}")
    A("  marketplaces, réseaux sociaux, cartographie : écartés comme sites non marchands")
    A("")
    A("cardshopmap est une SOURCE de découverte, pas l'univers du marché : une boutique")
    A("absente de cet index n'est pas une boutique inexistante.")
    A("")

    # ------------------------------------------------ TOP 20 STATES
    A("TOP 20 STATES")
    A("=" * 70)
    par_etat = idx.get("par_etat", {})
    listings: dict[str, int] = {}
    for f in idx.get("listings", []):
        listings[f["state"]] = listings.get(f["state"], 0) + 1
    sc: dict[str, int] = {}
    for r in pri.get("ranked", []):
        if r["score_a"] >= 8:
            for s in (r.get("states") or [r.get("state")]):
                sc[s] = sc.get(s, 0) + 1
    w = (22, 8, 10, 12)
    A(ligne("state", "shops", "domains", "sports-card", w=w))
    for etat, dom in list(par_etat.items())[:20]:
        A(ligne(etat.replace("-", " ").title(), listings.get(etat, 0), dom, sc.get(etat, 0), w=w))
    A("")
    A("« sports-card » = candidats dont l'étage A du score atteint 8 (nom ou rubrique")
    A("explicitement cartes de sport). Ce n'est pas un comptage du basket : c'est un tri.")
    A("")

    # ------------------------------------------------ TOP 30 SHOPS
    A("TOP 30 SHOPS — hunt_priority_score")
    A("=" * 70)
    rangs = pri.get("ranked", [])
    fun = {s["domain"]: s for s in top.get("shops", [])}
    w = (26, 16, 12, 26, 5, 14, 14, 12, 4, 4, 4)
    A(ligne("shop", "city", "state", "domain", "score", "legitimacy", "purchase",
            "crawl", "bkb", "seal", "old", w=w))
    for r in rangs[:30]:
        f = fun.get(r["domain"], {})
        A(ligne(r.get("shop_name") or "?", r.get("city") or "?",
                (r.get("state") or "").replace("-", " ").title(), r["domain"],
                r["hunt_priority_score"], f.get("legitimacy") or r.get("legitimacy") or "UNKNOWN",
                f.get("purchase_mode") or "UNKNOWN", f.get("crawlability") or "UNKNOWN",
                _b(f.get("basketball")), _b(f.get("sealed_basketball")),
                r.get("old_stock_score", 0), w=w))
    A("")
    A("bkb / seal : oui, non, ou « ? » quand nous n'avons pas pu lire. « ? » n'est pas « non ».")
    A("")
    for r in rangs[:30]:
        A(f"  {r['domain']}")
        A(f"     {r['reason']}")
        if not r.get("inspected"):
            A(f"     [{r.get('inspection_note') or 'vitrine non lue'}]")
    A("")

    # ------------------------------------------------ QUALIFIED
    A("QUALIFIED FROM TOP 100")
    A("=" * 70)
    if top:
        A(f"{top.get('qualifies', 0)} / {top.get('top_n', 100)}")
        A("")
        for k, v in sorted(top.get("par_statut", {}).items(), key=lambda x: -x[1]):
            A(f"  {k:30} {v:4}   {_sens(k)}")
        A("")
        A(f"Rangs > {top.get('top_n', 100)} : {top.get('non_examines', 0)} domaines NON EXAMINÉS.")
    else:
        A("funnel non encore exécuté")
    A("Les domaines de rang supérieur ne sont pas rejetés :")
    A("le TOP 100 est un ordre de passage, pas une clôture.")
    A("")

    # ------------------------------------------------ OFFRES
    A("WEMBY TARGET OFFERS FOUND")
    A("=" * 70)
    off = top.get("offres", [])
    if off:
        w = (30, 14, 22, 18, 9, 12, 6, 16, 12)
        A(ligne("product", "UPC", "shop", "city/state", "price", "stock", "qty",
                "match level", "confidence", w=w))
        for o in off:
            A(ligne(o.get("product") or "?", o.get("upc") or "?", o.get("shop") or "?",
                    o.get("city_state") or "?", o.get("price"), o.get("stock"),
                    o.get("quantity") if o.get("quantity") is not None else "?",
                    o.get("match_level") or "?", o.get("confidence") or "?", w=w))
            A(f"     {o.get('url')}")
    else:
        A("Aucune offre trouvée dans le périmètre effectivement vérifié.")
        A("")
        A("Ce que cela veut dire exactement : sur les boutiques du TOP 100 que nous avons pu")
        A("lire automatiquement, aucune fiche ne correspond aux cinq UPC canoniques. Cela ne")
        A("dit rien des boutiques BLOCKED, MANUAL_ONLY, non inspectées, ni des rangs au-delà")
        A("de 100 — et rien du marché hors de cet annuaire.")
    A("")

    # ------------------------------------------------ OLD STOCK GEMS
    A("OLD STOCK GEMS")
    A("=" * 70)
    A("Boutiques sans nos 5 produits, mais dont le catalogue justifie une investigation.")
    A("Ce score ne prouve AUCUNE disponibilité : il dit où une chasse manuelle peut payer.")
    A("")
    avec = {o["domain"] for o in off}
    gems = sorted((r for r in rangs if r.get("old_stock_score", 0) > 0
                   and r["domain"] not in avec),
                  key=lambda r: -r["old_stock_score"])[:25]
    if gems:
        w = (26, 26, 16, 12, 4)
        A(ligne("shop", "domain", "city", "state", "old", w=w))
        for r in gems:
            A(ligne(r.get("shop_name") or "?", r["domain"], r.get("city") or "?",
                    (r.get("state") or "").replace("-", " ").title(),
                    r["old_stock_score"], w=w))
            A(f"     {r.get('old_stock_reason')}")
    else:
        A("Aucun signal d'ancienneté relevé sur les vitrines effectivement lues.")
    return "\n".join(L)


def _b(v):
    return "?" if v is None else ("oui" if v else "non")


def _sens(statut: str) -> str:
    return {"QUALIFIED": "basket scellé prouvé, vente à distance lisible",
            "REJECTED_NO_BASKETBALL": "preuve suffisante : pas de basketball",
            "REJECTED_NO_SEALED": "basketball prouvé, pas de scellé",
            "IN_STORE_ONLY": "scellé présent, aucune vente à distance identifiée",
            "UNVERIFIED_NOT_CRAWLABLE": "le marchand interdit le crawl — candidat NON JUGÉ",
            "ERROR": "lecture impossible — ignorance, pas rejet"}.get(statut, "")


if __name__ == "__main__":
    t = rapport()
    bas = t.lower()
    for mot in INTERDITS:
        assert mot not in bas, f"formulation interdite dans le rapport : {mot}"
    print(t)
