#!/usr/bin/env python3
"""PHASES 4 à 7 — le funnel complet, mais sur CENT domaines, pas sur trois mille.

POURQUOI CENT
-------------
Ouvrir le catalogue de 3 281 marchands pour en retenir quelques dizaines coûterait des
dizaines de milliers de requêtes à des serveurs qui ne nous doivent rien. L'index et le score
existent précisément pour que le crawl profond soit dirigé. Le TOP 100 est un ordre de
passage, pas une clôture : le 101ᵉ n'est pas rejeté, il n'est pas encore examiné, et le
fichier le dit.

CE QUE LE FUNNEL PEUT CONCLURE, ET CE QU'IL NE PEUT PAS
--------------------------------------------------------
NO_BASKETBALL  : preuve suffisante que le marchand ne vend pas de basket.
NO_SEALED      : basket prouvé, preuve suffisante que le scellé n'est pas vendu.
MANUAL_ONLY    : nous n'avons pas su automatiser la lecture. Ce n'est pas un jugement.
BLOCKED        : le marchand interdit le crawl. Il reste CANDIDAT, non jugé.
UNKNOWN        : nous ne savons pas — et UNKNOWN n'est jamais NO.

PHASE 7
-------
Un domaine qui surgit d'une recherche produit sans figurer dans l'annuaire n'est pas moins
réel pour autant. cardshopmap est une source de découverte, pas l'univers du marché :
`reverse_discovery()` réinjecte ces domaines dans l'index des candidats.
"""
from __future__ import annotations
import json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import external_engine as xe
import shop_discovery as sd
import shop_qualify2 as sq2
import mega_hunt as mh
import mega_targets as mt

ROOT = Path(__file__).parent
PRIORITE = ROOT / "discovered" / "national_priority.json"
SORTIE = ROOT / "discovered" / "national_top100.json"
CANDIDATS = ROOT / "discovered" / "shop_candidates.json"

TOP_N = 100


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ phase 4
def funnel(c: dict) -> dict:
    """Les deux passes existantes, fusionnées — aucune règle de conformité n'est touchée."""
    dom = c["domain"]
    try:
        p1 = sd.qualifie(dom)
    except Exception as e:
        p1 = {"domain": dom, "status": "ERROR", "reason": e.__class__.__name__}
    try:
        p2 = sq2.qualifie2(dom)
    except Exception as e:
        p2 = {"domain": dom, "status": "ERROR", "reason": e.__class__.__name__}
    v = sq2.fusionne(p1, p2)
    return {**c, **v, "platform_api": p1.get("platform"), "checked_at": now(),
            # la légitimité de l'étage 3 se nourrit des DEUX lectures : l'annuaire publie une
            # adresse et un téléphone que les pages du marchand ne répètent pas toujours.
            "legitimacy": _meilleure(c.get("legitimacy"), v.get("legitimacy")),
            "legitimacy_evidence": sorted(set((c.get("legitimacy_evidence") or [])
                                              + (p2.get("signaux") or [])))}


_RANG = {"TRUSTED": 3, "LIKELY_LEGIT": 2, "UNVERIFIED": 1, None: 0, "SUSPICIOUS": -1}


def _meilleure(a, b):
    """Deux fenêtres sur le même commerçant : on retient la mieux étayée, pas la dernière."""
    return a if _RANG.get(a, 0) >= _RANG.get(b, 0) else b


def passe_top(candidats: list[dict], n: int = TOP_N, workers: int = 6, journal=print) -> list[dict]:
    top = candidats[:n]
    journal(f"funnel complet sur {len(top)} domaines (rangs 1 à {len(top)})")
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = []
        for i, r in enumerate(ex.map(funnel, top), 1):
            out.append(r)
            if i % 20 == 0:
                journal(f"  {i}/{len(top)} — {(time.monotonic()-t0)/60:.1f} min")
    return out


# ------------------------------------------------------------------ phase 5
def cibles(shops: list[dict], journal=print) -> list[dict]:
    """Les 5 références canoniques, sur les seules boutiques qualifiées. Matching INCHANGÉ."""
    offres, vus = [], set()
    for s in shops:
        if not s.get("hunt_enabled"):
            continue
        base = f"https://{s['domain']}"
        vide = 0
        for q in mh.REQUETES:
            try:
                res = mh.cherche(base, q)
            except Exception:
                res = []
            if not res:
                vide += 1
                if vide >= 3:
                    break
                continue
            for r in res:
                if r["url"] in vus:
                    continue
                ident = mh.identifie(r["titre"], sku_vendeur=r.get("sku", ""))
                if ident["confiance"] == "HORS_PERIMETRE" or not ident["target"]:
                    continue
                vus.add(r["url"])
                t = ident["target"]
                # `id` est un slug interne, `upc` est le code produit. Les confondre
                # publierait « prizm_2023_24_mega_red_ice » dans la colonne UPC du rapport.
                offres.append({"product": t["libelle"], "upc": t["upc"], "target_id": t["id"],
                               "shop": s.get("shop_name") or s["domain"],
                               "domain": s["domain"],
                               "city_state": f"{s.get('city') or '?'} / {s.get('state') or '?'}",
                               "price": r.get("prix"), "currency": r.get("devise") or "USD",
                               "stock": "IN_STOCK" if r.get("dispo") else "OUT_OF_STOCK",
                               "quantity": r.get("qty"), "shipping": None, "url": r["url"],
                               "match_level": ident["preuve"], "confidence": ident["confiance"],
                               "config": mh.valide_config(t, f"{r['titre']} {r.get('sku','')}"),
                               "title": r["titre"]})
                journal(f"  TROUVÉ {ident['confiance']:<18} {s['domain'][:26]:<26} {r['titre'][:50]}")
    return offres


# ------------------------------------------------------------------ phase 7
def reverse_discovery(offres: list[dict], connus: set[str], journal=print) -> list[str]:
    """Un domaine inconnu surgi d'une recherche produit n'est pas un domaine à ignorer."""
    nouveaux = sorted({o["domain"] for o in offres if o["domain"] not in connus})
    for d in nouveaux:
        journal(f"  domaine hors annuaire à qualifier : {d}")
    return nouveaux


# ------------------------------------------------------------------ sortie
def sauve(payload: dict):
    payload["generated_at"] = now()
    payload["note"] = (
        "Le TOP 100 est un ORDRE DE PASSAGE, pas une clôture. Les domaines de rang 101 et "
        "au-delà ne sont pas rejetés : ils ne sont pas encore examinés. BLOCKED et "
        "MANUAL_ONLY restent des candidats non jugés — une limite de lecture n'est jamais "
        "un jugement sur le marchand.")
    SORTIE.parent.mkdir(exist_ok=True)
    SORTIE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else TOP_N
    d = json.loads(PRIORITE.read_text(encoding="utf-8"))
    cands = d["ranked"]
    print(f"PHASE 4 — FUNNEL COMPLET SUR LE TOP {n}\n" + "=" * 46)
    shops = passe_top(cands, n)
    par_statut: dict[str, int] = {}
    for s in shops:
        par_statut[s["status"]] = par_statut.get(s["status"], 0) + 1
    print("\nrésultat du funnel :")
    for k, v in sorted(par_statut.items(), key=lambda x: -x[1]):
        print(f"  {k:28} {v:4}")
    qualifies = [s for s in shops if s.get("hunt_enabled")]
    print(f"\nQUALIFIED FROM TOP {n} : {len(qualifies)} / {n}")

    print(f"\nPHASE 5 — LES 5 CIBLES SUR {len(qualifies)} BOUTIQUES QUALIFIÉES\n" + "=" * 46)
    offres = cibles(qualifies)
    print(f"  {len(offres)} offre(s) correspondant aux cibles canoniques")

    connus = {c["domain"] for c in cands}
    nouveaux = reverse_discovery(offres, connus)

    sauve({"top_n": n, "examines": len(shops), "qualifies": len(qualifies),
           "par_statut": par_statut, "shops": shops, "offres": offres,
           "reverse_discovery": nouveaux,
           "non_examines": max(0, len(cands) - len(shops))})
    print(f"\nnon encore examinés (rang > {n}) : {max(0, len(cands) - len(shops))} "
          f"— non rejetés, non examinés")


if __name__ == "__main__":
    main()
