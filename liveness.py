#!/usr/bin/env python3
"""Sonde de vivacité — la plus économe possible, et conforme.

CE QU'ELLE CORRIGE
------------------
Le classement par similarité lit l'annuaire, et l'annuaire ne sait pas qu'un domaine est
mort. 27 des 50 créneaux de validation sont partis dans des sites injoignables ou interdits :
plus de la moitié du budget. La passe nationale n'avait pas ce défaut, mais l'avait payé
4 596 requêtes d'avance.

L'ORDRE DES SONDES, DU MOINS CHER AU PLUS CHER
-----------------------------------------------
1. DNS — zéro requête HTTP, le serveur du marchand n'est même pas contacté. Quatorze des
   dix-huit échecs précédents étaient de simples domaines sans résolution.
2. robots.txt — une requête, et elle décide si la suivante a le droit d'exister.
3. Accueil — une requête.

Un domaine mort coûte donc ZÉRO requête au lieu de deux.

CE QU'UN ÉTAT NE DIT PAS
------------------------
BLOCKED n'est pas DEAD : le marchand existe et refuse le robot. TIMEOUT n'est pas DEAD :
le serveur a peut-être seulement été lent. Et aucun de ces états ne dit quoi que ce soit sur
le catalogue — une lecture manquée n'est pas une absence de NBA.
"""
from __future__ import annotations
import socket
from concurrent.futures import ThreadPoolExecutor

import external_engine as xe

LIVE, DEAD, BLOCKED, TIMEOUT, HTTP_ERROR, UNKNOWN = (
    "LIVE", "DEAD", "BLOCKED", "TIMEOUT", "HTTP_ERROR", "UNKNOWN")

# Un état qui autorise la suite du funnel. Les autres laissent la boutique CANDIDATE.
EXPLOITABLE = {LIVE}
# Ce qui n'est PAS une raison d'abandonner un marchand : il existe, nous ne l'avons pas lu.
NON_JUGEANT = {BLOCKED, TIMEOUT, HTTP_ERROR, UNKNOWN}


def resout(dom: str, timeout: float = 4.0) -> bool:
    """Le domaine existe-t-il seulement ? Aucune requête HTTP n'est émise."""
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        socket.getaddrinfo(dom, 443, proto=socket.IPPROTO_TCP)
        return True
    except Exception:
        return False
    finally:
        socket.setdefaulttimeout(old)


def sonde(dom: str) -> dict:
    """Trois sondes, dans l'ordre du coût. On s'arrête dès qu'une tranche."""
    r = {"domain": dom, "state": None, "http": None, "fetchs": 0, "raison": None}
    if not resout(dom):
        r.update(state=DEAD, raison="le domaine ne résout pas (DNS) — aucune requête émise")
        return r
    if not xe.robots_ok(f"https://{dom}/"):
        r.update(state=BLOCKED, fetchs=1,
                 raison="robots.txt interdit — respecté ; le marchand existe, il refuse le robot")
        return r
    st, b, why = xe.fetch(f"https://{dom}", timeout=10)
    r["fetchs"] = 2
    r["http"] = st or why
    if st == 200 and b:
        r.update(state=LIVE, raison=f"accueil lu ({len(b)} octets)")
    elif why == "timeout" or st is None and why in ("timeout", "TimeoutError"):
        r.update(state=TIMEOUT, raison="délai dépassé — lenteur constatée, pas une absence")
    elif isinstance(st, int) and st in (429, 403):
        r.update(state=BLOCKED, raison=f"HTTP {st} — protection anti-robot, respectée")
    elif isinstance(st, int):
        r.update(state=HTTP_ERROR, raison=f"HTTP {st}")
    else:
        r.update(state=UNKNOWN, raison=f"pas de réponse exploitable ({why})")
    return r


def sonde_tous(domaines: list[str], workers: int = 10, journal=print) -> list[dict]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(sonde, domaines))
    from collections import Counter
    c = Counter(x["state"] for x in out)
    journal(f"  {dict(c)} · {sum(x['fetchs'] for x in out)} requêtes émises")
    return out
