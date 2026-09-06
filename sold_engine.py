#!/usr/bin/env python3
"""Moteur de ventes réalisées — ingestion, filtrage, médianes 30/90/365 jours.

POURQUOI CE MODULE PREND DU TEXTE COLLÉ PLUTÔT QUE DE CRAWLER
--------------------------------------------------------------
SportsCardsPro et PriceCharting publient exactement ce qu'il nous faut : l'historique des
ventes réalisées, daté, titré, chiffré. Leur HTML est inaccessible depuis ici — Cloudflare
oppose un défi « Just a moment » sur chaque route essayée, y compris via un proxy de lecture,
et je ne contourne pas une protection anti-robot.

Leur API, elle, répond. `/api/product` rend `{"error":"Must provide an access token"}` avec un
code 400, pas un 403 : l'endpoint existe, il est documenté, il attend une clé. C'est la voie
propre et scalable — elle couvrirait les 307 SKU, pas seulement trente.

En attendant cette clé, ce module accepte le tableau collé depuis un navigateur. C'est du
travail humain, mais c'est du travail humain qui ne se refait pas : chaque vente ingérée est
datée et conservée, et la médiane se recalcule toute seule au fil du temps.

CE QU'IL FILTRE, ET POURQUOI
----------------------------
Une ligne de vente n'est comparable que si elle porte le MÊME produit. Le tableau d'un site de
cotation mélange volontiers la boîte, le case, le lot de trois, la variante FOTL et l'exemplaire
abîmé. Les inclure ne rend pas la médiane « plus robuste », elle la rend fausse.
"""
from __future__ import annotations
import re
import statistics
from datetime import date, datetime, timedelta

# Motifs d'exclusion, appliqués au TITRE de l'annonce vendue.
EXCLUDE = [
    ("lot",        r"\blot\b|\bbundle\b|\d+\s*(?:boxes|box)\b(?!\s*case)|\bx\s?[2-9]\b"),
    ("case",       r"\bcase\b|\d{1,3}\s*-?\s*box\s*case"),
    ("pack",       r"(?<![\w-])packs?\b|\bpochette"),
    ("fotl",       r"\bfotl\b|first\s*off\s*the\s*line|1st\s*off\s*the\s*line"),
    ("imparfait",  r"\bdamaged?\b|\bimperfect\b|\bcrease|\bdented?\b|\bresealed\b|\bopened\b|\bempty\b"),
    ("autre saison", None),      # traité à part : la saison se compare, elle ne se devine pas
]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s: str, today: date | None = None) -> date | None:
    """Les tableaux de cotation datent en clair (« Aug 19, 2026 ») ou en ISO. On accepte les
    deux et on refuse le reste — une vente sans date ne peut entrer dans aucune fenêtre."""
    s = s.strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    # « 19/08/26 » et « 08/19/2026 » : ambigus. On refuse plutôt que de deviner le mois.
    return None


def excluded(title: str, season: str | None = None) -> str | None:
    """Le motif d'exclusion, ou None si la vente est comparable."""
    t = " " + title.lower() + " "
    for label, rx in EXCLUDE:
        if rx and re.search(rx, t):
            return label
    if season:
        # la saison écrite dans le titre doit correspondre ; « 2023-24 » et « 2023/24 » sont
        # la même chose, « 2022-23 » ne l'est pas
        y = season.split("-")[0]
        if re.search(r"\b20\d{2}\b", t) and y not in t.replace("/", "-"):
            return "autre saison"
    return None


def parse_pasted(text: str, season: str | None = None, today: date | None = None):
    """Ingère un tableau collé. Une vente par ligne, dans n'importe quel ordre de colonnes,
    du moment qu'on y trouve une date et un prix.

    Rend (ventes_retenues, rejets) — les rejets sont CONSERVÉS avec leur motif, parce qu'un
    filtre qu'on ne peut pas relire est un filtre qu'on ne peut pas corriger.
    """
    kept, dropped = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        pm = re.search(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)", line)
        d = parse_date(line, today)
        if not pm or not d:
            continue
        price = float(pm.group(1).replace(",", ""))
        title = re.sub(r"\$\s?[0-9][0-9,]*(?:\.[0-9]{2})?", " ", line)
        # la DATE de la vente doit sortir du titre avant tout contrôle de saison : sinon
        # « Aug 19, 2026 » fait croire à un produit 2026 et toute vente récente est rejetée
        title = re.sub(r"\d{4}-\d{2}-\d{2}", " ", title)
        title = re.sub(r"[A-Za-z]{3}[a-z]*\.?\s+\d{1,2},?\s+\d{4}", " ", title)
        title = re.sub(r"\s{2,}", " ", title).strip(" \t|·-")
        why = excluded(title, season)
        rec = {"date": d.isoformat(), "price": price, "title": title[:120]}
        if why:
            rec["excluded"] = why
            dropped.append(rec)
        else:
            kept.append(rec)
    return kept, dropped


def windows(sales: list[dict], today: date | None = None) -> dict:
    """Médianes et fourchettes à 30, 90 et 365 jours, plus la confiance qui en découle.

    La confiance suit l'échelle validée : >=10 ventes HIGH, 3-9 MEDIUM, 1-2 LOW. Avec une ou
    deux ventes on ne prétend pas à une médiane robuste — on rend une FOURCHETTE, ce qui reste
    infiniment plus utile qu'UNKNOWN.
    """
    today = today or date.today()
    out = {}
    for days in (30, 90, 365):
        cut = today - timedelta(days=days)
        w = [s for s in sales if date.fromisoformat(s["date"]) >= cut]
        px = sorted(s["price"] for s in w)
        if not px:
            out[f"d{days}"] = {"n": 0, "median": None, "low": None, "high": None,
                               "confidence": "NONE"}
            continue
        conf = "HIGH" if len(px) >= 10 else "MEDIUM" if len(px) >= 3 else "LOW"
        out[f"d{days}"] = {"n": len(px), "median": round(statistics.median(px), 2),
                           "low": px[0], "high": px[-1], "confidence": conf}
    return out


def best_window(w: dict) -> dict:
    """La fenêtre la plus courte qui reste crédible. Un marché bouge : trente jours valent
    mieux que trois cent soixante-cinq, à condition d'avoir assez de ventes dedans."""
    for k in ("d30", "d90", "d365"):
        if w[k]["confidence"] in ("HIGH", "MEDIUM"):
            return {**w[k], "window": k}
    for k in ("d30", "d90", "d365"):
        if w[k]["n"]:
            return {**w[k], "window": k}
    return {"n": 0, "median": None, "confidence": "NONE", "window": None}
