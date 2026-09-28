#!/usr/bin/env python3
"""NBA n'est pas « basketball », et la porte doit savoir la différence.

CE QUE CETTE DISTINCTION CORRIGE
--------------------------------
Ryno's Sports Cards est ressortie QUALIFIED sur une seule preuve : une boîte Donruss
« Turkish Airlines EuroLeague », épuisée de surcroît. C'est du basket scellé, et ce n'est pas
ce que nous chassons. EuroLeague, WNBA, NCAA, Draft Picks, Overtime Elite, FIBA : autant de
basket qui ne contiendra jamais une recrue NBA 2023-24.

POURQUOI L'ABSENCE DE SIGNAL NÉGATIF NE SUFFIT PAS
---------------------------------------------------
On pourrait croire qu'il suffit d'écarter les ligues étrangères. Non : « Basketball Hobby
Boxes », intitulé de rayon sans millésime ni gamme, ne prouve aucun produit NBA. Il faut une
preuve POSITIVE — la ligue nommée, ou une gamme dont on sait qu'elle est sous licence NBA —
et l'absence de marqueur d'une autre ligue. Les deux conditions, pas l'une des deux.

CE QUE « GENERIC » VEUT DIRE
-----------------------------
Ni NBA prouvé, ni autre ligue prouvée. C'est une ignorance, elle porte son nom, et elle
laisse la boutique CANDIDATE — jamais rejetée.
"""
from __future__ import annotations
import re

# Une autre ligue NOMMÉE : preuve positive que ce n'est pas de la NBA.
NON_NBA = re.compile(
    r"euro\s*-?league|euroleague|turkish\s*airlines|eurocup|\bfiba\b|\bacb\b|liga\s*endesa|"
    r"\bwnba\b|\bncaa\b|college|collegiate|university|\bnit\b|march\s*madness|"
    r"draft\s*picks?|\bote\b|overtime\s*elite|rising\s*stars|"
    r"mcdonald'?s\s*all[\s-]*american|olympic|team\s*usa|\bnbl\b|\bcba\b|"
    r"basketball\s*hall\s*of\s*fame|harlem\s*globetrotters", re.I)

# La ligue nommée, sans ambiguïté.
NBA_EXPLICITE = re.compile(r"\bnba\b", re.I)

# Gammes sous licence NBA. Associées au mot « basketball », elles désignent la NBA — Panini
# et Topps déclinent ces noms sur d'autres sports, d'où l'exigence du mot.
GAMMES_NBA = re.compile(
    r"\bprizm\b|\bselect\b|\bmosaic\b|\boptic\b|\bdonruss\b|\bhoops\b|court\s*kings|"
    r"\brevolution\b|\borigins\b|\bobsidian\b|\bnoir\b|immaculate|\bflawless\b|"
    r"national\s*treasures|\bcontenders\b|\bchronicles\b|crown\s*royale|\bspectra\b|"
    r"\babsolute\b|\bcertified\b|\brecon\b|\bstatus\b|\bphoenix\b|\bimpeccable\b|"
    r"topps\s*chrome|\bbowman\b|\bsticker\b|\bcourtside\b|\bhigh\s*voltage\b", re.I)

BASKET = re.compile(r"basketball|\bnba\b|\bhoops\b|court\s*kings", re.I)

SCELLE = re.compile(
    r"hobby\s*box|blaster\s*box|blaster|mega\s*box|booster\s*box|retail\s*box|hobby\s*case\b|"
    r"\d{1,2}[\s-]*box\s*case|hanger\s*(?:box|pack)|fat\s*pack|jumbo\s*(?:box|pack)|"
    r"sealed\s*(?:box|case|pack|wax)|\bwax\s*box\b|value\s*box|\bcello\b|\bh2\b|"
    r"\bbox\b(?!\s*(?:break|topper))|\bcase\b(?=\s|$)", re.I)

PAS_DES_CARTES = re.compile(r"funko|\bpop!|vinyl|bobblehead|jersey|sneaker|poster|t-?shirt|"
                            r"\bmug\b|\bhat\b|figure|statue|autographed\s*(?:photo|ball)", re.I)

NBA, AUTRE_LIGUE, GENERIQUE = "NBA", "NON_NBA", "GENERIC"


def classe_ligue(titre: str) -> str:
    """NBA prouvée, autre ligue prouvée, ou nous ne savons pas. Trois états, jamais deux."""
    t = titre or ""
    if NON_NBA.search(t):
        return AUTRE_LIGUE
    if NBA_EXPLICITE.search(t):
        return NBA
    if BASKET.search(t) and GAMMES_NBA.search(t):
        return NBA
    return GENERIQUE


def est_scelle_nba(titre: str) -> bool:
    """Le produit qui qualifie : scellé, basket, NBA prouvée, et pas une figurine."""
    t = titre or ""
    return (bool(BASKET.search(t)) and bool(SCELLE.search(t))
            and not PAS_DES_CARTES.search(t) and classe_ligue(t) == NBA)


# Millésimes : ce que le titre dit de la saison, sans interprétation.
SAISON = re.compile(r"\b(19[7-9]\d|20[0-2]\d)\s*[-/]\s*(\d{2})\b")


def saison(titre: str) -> str | None:
    m = SAISON.search(titre or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def annee_debut(titre: str) -> int | None:
    m = SAISON.search(titre or "")
    return int(m.group(1)) if m else None
