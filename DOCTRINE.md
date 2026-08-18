# Doctrine — NBA Wax Radar US → France (v1.1, figée le 17/08/2026, validée Julien + GPT + Claude)

Trois axes indépendants. Ne jamais les mélanger.

## ❤️ Personal (subjectif — Julien)
- Ce que je veux collectionner. `wemby_rc` est un FILTRE PERSONNEL, sans rapport nécessaire avec la rentabilité.
- Champs : `personal.wemby_rc` (bool), `personal.interest` (1–5).

## 🔥 Market (le public)
- Désirabilité intrinsèque de la box (Midnight, Chrome Update, Cosmic, NT, Immaculate…), indépendante du prix.
- Champs : `market.heat` (1–5, manuel au départ ; calculé plus tard : ventes réalisées, volume, tenue du sealed, vitesse de vente, dispo, rookie class — le "prestige" d'une gamme ne compte que s'il se traduit en comportements observables, jamais comme facteur autonome),
  `market.ask_us` (prix affiché : WaxStat/shops), `market.sold_us` (ventes réalisées : SportsCardsPro / eBay sold), `market.eu_ref_eur`.
- Règle : le seuil GO se cale sur `sold_us`, jamais sur `ask_us`. Toute valeur est datée et sourcée.

## 💰 Business (aucune note subjective — uniquement des calculs sur données observées)
- SEALED : `prix réellement vendable FR − coût rendu − frais de vente` → `resale_margin_eur / pct`.
- BREAK  : `revenu réellement encaissé des spots − coût box − frais plateforme` → `break_margin_eur`.
- Un prix affiché chez un shop FR n'est PAS un prix de vente réaliste. Sans donnée sourcée, le moteur affiche `n/a`, jamais un score inventé.
- Chaque valeur France porte : `value` + `source` (own_sales | ebay_fr_sold | cardmarket_sold | shop_ask) + `sample_size` + `checked_at`.
  La confiance est DÉRIVÉE (source × sample_size), jamais saisie.
- Break : mesurer `break_fill_rate`, `break_fill_time_min`, `avg_spot_realized_eur`, `spots_unsold_absorbed` — pas le prix de spot théorique.
  30 × 20 € affichés avec 4 équipes reprises par Julien ≠ 600 € encaissés : le revenu = spots réellement payés par des tiers.
  L'effet d'entraînement (une box premium quasi break-even qui remplit vite et porte 3 blasters à forte marge) est à MESURER plus tard, pas à inventer.

## Règles de données (déjà apprises à nos dépens)
1. Fiche produit / variant LIVE > page collection > Google/indexation. (EH Cards 29,99 → 34,99 ; Baseball Card Connection 26,91 → terminé.)
2. Conserver le dernier prix quand un produit passe OOS ; un RESTOCK sous seuil vaut plus qu'une baisse de prix.
3. Séparer `ask` et `sold`.
4. Une observation par variante Shopify (titre + variant_title). Mauvaise saison ou mauvais format = éliminé ; format inconnu = REVIEW.
5. Landed cost = coût rendu ESTIMÉ par boîte dans un panier de N boîtes ; hypothèses → remplacées par les chiffres MyUS réels.

## Ce qui rend l'outil unique
Le crawl US, n'importe qui peut le refaire. La base de VRAIES ventes France (`own_sales`) et le comportement réel des spots en live, non.
→ Tenir cette base dès la première session Whatnot, même à la main.

## Séquence
V1.1 : premier crawl réel → corriger la section REVIEW → accumuler l'historique.
V2   : `personal / market / business` dans catalog.yaml, deux vues (🎯 Wemby | 💎 Radar), bannière "🚨 N deals aujourd'hui",
       collecteur html (DACW, Steel City, Blowout, Chicagoland), eBay Browse API, alertes Telegram.
On ne touche à rien avant le premier crawl réel.
