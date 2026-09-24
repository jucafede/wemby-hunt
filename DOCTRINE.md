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

## Autonomie du noyau Prizm (07/09/2026)

Trois fichiers étaient tenus à la main : les annonces externes, les ventes réalisées, et le
balayage Prizm qui recrawlait ce que le moteur venait de lire. Un tableau de bord dont les
données dépendent d'une intervention humaine n'est pas un outil, c'est un rapport.

**Une boutique se lit une fois.** `hunt.py` interroge Shopify ET WooCommerce sur chaque source
et dépose tout dans `products_raw` ; `prizm_core.py` y puise. La preuve n'est pas une relecture
de code — `tests_autonomy` coupe les sockets avant de l'appeler. Et le balayage de découverte
relit `sources.yaml` à chaque passage pour écarter les domaines déjà crawlés : sans ce filtre,
une ligne ajoutée aux sources suffisait à faire lire un marchand deux fois.

**Chercher et revérifier sont deux étapes.** Revalider les URL connues répond à « celle-ci
tient-elle ? ». Découvrir répond à « qu'avons-nous raté ? ». Un moteur qui ne fait que la
première ne trouvera jamais la treizième annonce.

**Six états, dont STALE.** Une annonce non vérifiée depuis plus de 24 h reste affichée, datée,
mais ne compte pas comme disponible, ne peut pas porter le meilleur prix et ne déclenche aucun
achat. La règle vaut pour TOUTES les couches, y compris les sources enregistrées : la couche la
mieux instrumentée ne doit pas être la seule autorisée à mentir sur sa fraîcheur.

**Ce qu'on ne peut pas lire, on ne le prétend pas.** eBay, StockX, SportsCardsPro et 130point
répondent 403 à toute lecture automatisée. On ne contourne pas une protection anti-robot, et
robots.txt est respecté même quand le catalogue nous intéresse (Blowout nomme ClaudeBot avec
`Disallow: /`). Conséquence assumée : les lignes de ces sites sont structurellement STALE.

**La découverte ne repose pas sur un seul canal.** Aucun moteur de recherche généraliste ne
nous est acquis — Brave bloque l'IP à la deuxième requête, Bing lit le tiret de « 2023-24 »
comme un opérateur d'exclusion. Un second canal balaie par rotation le catalogue des marchands
connus mais non enregistrés, par API publique, où la disponibilité est une donnée structurée.
Chaque interrogation est journalisée avec son issue : un « 0 trouvé » ne doit jamais pouvoir se
confondre avec un « 0 cherché ».

**Les ventes sont des transactions.** `sold_ledger.json` conserve chaque vente — date, prix,
source, URL. `sold_prizm.json` en est la sortie calculée à chaque passage. `LAST_SALE` n'est
jamais une médiane : c'est un point, souvent le plus bruyant de la série. Un relevé agrégé
qu'on ne peut pas décomposer se cite comme tel et ne se déplie pas en fausses transactions.

## Le piège récurrent : confondre notre lecture et le marchand (24/09/2026)

Quatre fois dans la même session, la même faute sous quatre formes. Elle mérite d'être nommée
parce qu'elle ne ressemble pas à une erreur : elle produit des chiffres plausibles, tous faux
dans le même sens.

| Confusion | Ce que ça a produit |
|---|---|
| Filtre de ligues appliqué au texte ENTIER d'une page au lieu du titre | des Mega basket écartées parce qu'un menu disait « football » |
| « L'API répond zéro résultat » lu comme « aucune API lisible » | 16 boutiques classées non crawlables alors qu'elles n'avaient simplement pas de basket |
| Filtre de sport appliqué au texte entier | `NO_BASKETBALL` gonflé de 7 à 57 |
| « Nous n'avons rien su lire » lu comme « le site nous interdit » | une boutique prouvée par son API annulée |

LA RÈGLE QUI EN DÉCOULE
Un filtre pertinent sur un TITRE de produit devient faux sur le texte d'une page : une page
contient le catalogue entier, donc tous les sports et toutes les ligues. Un filtre d'exclusion
s'applique à l'objet qu'il juge, jamais à son contexte.

Et surtout : une limite de NOTRE lecture n'est jamais un jugement sur le marchand. « Nous ne
savons pas lire » et « il n'y en a pas » sont deux phrases opposées. Les ranger sous le même
statut transforme silencieusement notre ignorance en information — c'est la même faute que
« 0 résultat dans le registre » lu comme « introuvable sur le marché », et elle appelle la
même discipline : deux axes séparés, LEGITIMACY et CRAWLABILITY, et un statut
UNVERIFIED_NOT_CRAWLABLE qui dit ce qu'il est — une candidate non jugée, pas un rejet.

---

## Découverte nationale : un ordre de passage n'est pas un verdict

3 281 fiches d'annuaire, et le budget pour en crawler cent. Tout le problème de cette phase
tient dans ce rapport : il faut DIRIGER le crawl profond sans laisser le tri se faire passer
pour un jugement.

**Le score ne note pas les magasins.** `hunt_priority_score` répond à une seule question :
dans quel ordre ouvrir les catalogues pour tomber sur du scellé ancien. Il ne dit pas quelle
boutique est bonne. Un rang 800 n'est pas une boutique rejetée, c'est une boutique dont le
tour n'est pas venu — et le fichier comme le rapport doivent l'écrire, parce qu'un tableau
trié se lit spontanément comme un classement du meilleur au pire.

**Aucun poids n'est négatif, et c'est délibéré.** Un site en HTML de 2009, sans API, sans
panier, avec un inventaire mail-order profond, est une MEILLEURE cible qu'un Shopify neuf qui
ne stocke que le produit de l'année. Pénaliser la vétusté reviendrait à trier par
sophistication technique — exactement l'inverse de ce qu'on cherche. RK Collectibles est le
modèle : vieux magasin réel, catalogue profond, vieux scellé.

**Un zéro d'observation n'est pas un zéro de fait.** L'étage B du score vaut 0 quand la
vitrine n'a pas été lue — robots.txt qui refuse, site injoignable, page vide. Ce 0 se range
dans la même colonne qu'un 0 obtenu après lecture, et devient indiscernable dès qu'on trie.
D'où le champ `inspected`, la note qui l'accompagne, et le `?` du rapport là où un `non`
serait un mensonge. C'est la cinquième occurrence de la même faute dans ce projet ; la seule
parade qui tienne est structurelle, pas une bonne intention.

**Le débit se compte, il ne se suppose pas.** L'annuaire rend ses pages en 0,4 s ou en 9 s
selon son cache. Le compteur par hôte de `xe.fetch` n'est pas protégé : à plusieurs fils il
devient une condition de course, qui laisse passer des rafales ou fige tout. La politesse
qu'on ne peut pas mesurer n'est pas de la politesse — d'où un compteur explicite sous verrou.
Cela ne touche à aucune règle de conformité : robots.txt reste souverain, et les chemins
interdits — `/go/`, `/api/`, `/admin/`, `/auth-error/` — ne sont jamais demandés.
