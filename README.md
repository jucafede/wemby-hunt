# wemby-hunt v1 — moteur de chasse aux prix (LCS US, Shopify)

Pipeline : `sources.yaml` (shops) → `products_raw` (tout) → normalisation + score → `observations` (SKU reconnus) → décision GO / WATCH / NO_GO / REVIEW → CSV.

## Lancer
```bash
pip install -r requirements.txt
python hunt.py --dry-run          # teste le normaliseur sur des titres réels (sans réseau)
python hunt.py                    # crawl tous les shops shopify_json + rapport terminal + out/deals_*.csv
python hunt.py --shop ehcards     # un seul shop
python hunt.py --report           # rapport depuis hunt.db sans recrawler
```

## Fichiers à faire vivre
- `catalog.yaml` : les SKU canoniques (season / manufacturer / set / format / configuration), leurs seuils
  `buy_below_usd` / `watch_below_usd`, le prix marché US et la référence EU (saisis à la main, datés).
  Deux tiers : `retail` (classement principal) et `hobby` (watch séparé). Le bloc `landed_cost` contient
  les hypothèses de coût rendu France — à remplacer par les chiffres réels après la 1re expédition MyUS.
- `sources.yaml` : les shops. `type: shopify_json` est géré ; `html` (DACW, Chicagoland) = v2.

## Règles de matching (hunt.py::match_title)
- gamme (0.40) + saison (0.30) + format (0.25) + sport basket (0.05). Mauvaise saison ou mauvais
  format = éliminé. Format inconnu = plafonné sous 0.80 → REVIEW (jamais comparé automatiquement).
- garde-fous : `Prizm` exige "Panini Prizm" ou "Prizm Basketball" (évite "Ice Prizms", "Hyper Pink Prizms"),
  exclut Monopoly/Draft ; `Donruss Optic` exige le mot Optic ; football/baseball/WNBA/EuroLeague = exclus.
- seuil de rattachement : `>= 0.80`.

## Politesse
1 requête/seconde par shop, User-Agent identifiable. Un LCS qui bloque = une source perdue.

## Sans terminal (GitHub Actions + GitHub Pages)
1. Crée un repo GitHub (gratuit) et dépose ce dossier dedans (ou demande à Claude Code : « crée un repo GitHub avec ce dossier, active Actions et Pages sur la branche gh-pages »).
2. Onglet Actions → « wemby-hunt » → Run workflow. GitHub lance le crawler toutes les 6 h.
3. Settings → Pages → source = branche `gh-pages`. Ta page de résultats est à `https://<toi>.github.io/<repo>/`.
4. Le CSV et le rapport texte de chaque passage sont dans l'artefact « deals » du run.

## Signaux
- 🔥 GO / 👀 WATCH / ⛔ NO_GO sur le meilleur prix EN STOCK, par rapport à `buy_below_usd` / `watch_below_usd`.
- 🔔 RESTOCK : dispo passée de 0 → 1 depuis le passage précédent ; 🚨 RESTOCK DEAL si en plus le prix ≤ `buy_below_usd`.
- `market_ask_us` (prix affiché) ≠ `market_sold_us` (ventes réalisées) : le seuil GO se cale sur les ventes réalisées.
- landed € = coût rendu France ESTIMÉ par boîte dans un panier de `bundle_boxes` boîtes — pas le coût d'une boîte seule.
- Une ligne par variante Shopify (titre + variant_title) : un produit "Optic Basketball" avec variantes Blaster/Mega donne 2 observations distinctes.

## v2 (Claude Code)
collecteur `html` (DACW, Chicagoland, Steel City), eBay Browse API (factory sealed, feedback ≥ 5k, US),
alertes Telegram (passage sous seuil / retour en stock), historique de prix par SKU, mini-dashboard.
