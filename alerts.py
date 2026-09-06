#!/usr/bin/env python3
"""Coût rendu France, notation d'affaire, et les neuf événements de la chasse.

DEUX PRINCIPES, DONT TOUT LE RESTE DÉCOULE
------------------------------------------
1. Une remise ne se calcule que contre des VENTES RÉALISÉES. Sans sold fiable, le moteur dit
   NO_RELIABLE_SOLD_DATA et se tait sur le pourcentage. Il continue de signaler ce qu'il sait
   — un plus-bas, un restock, un stock ancien — mais il n'invente pas de décote.
2. Un coût rendu incertain vaut mieux qu'un coût rendu absent, À CONDITION que son incertitude
   voyage avec lui. Chaque montant porte donc son niveau de confiance, et une estimation ne
   se présente jamais comme un relevé.

POURQUOI LE SCORE N'EST PAS UNE MOYENNE PONDÉRÉE DE TOUT
--------------------------------------------------------
Un score sur 100 qui mélange discount, rareté, liquidité et risque vendeur donne un chiffre
lisse qui cache ses propres trous. Ici le score REFUSE de dépasser un plafond quand la donnée
manque : sans sold fiable il est plafonné, sans Wembanyama il s'effondre. Un 82/100 veut dire
quelque chose ; un 82/100 fabriqué à partir de trois inconnues ne veut rien dire.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# ---------------------------------------------------------------- coût rendu France
# Constantes d'import mesurées sur les commandes réelles de Julien, pas des hypothèses de
# barème : 340 € de transit MyUS pour 35 unités (Cardiacs/Hidden Gems), 144,10 € d'UPS réel
# pour 8 unités (Blowout). On retient la fourchette basse, l'estimation doit décevoir plutôt
# que flatter.
MYUS_PER_UNIT_EUR = 9.70          # 340 / 35
US_DOMESTIC_SHIP_EUR = 3.00       # port intérieur mutualisé sur un panier
VAT_FR = 0.20
CUSTOMS_RATE = 0.0                # cartes à collectionner : droits nuls, TVA seule
EU_SHIP_DEFAULT_EUR = 12.00       # ordre de grandeur d'un colis suivi intra-UE


@dataclass
class Landed:
    """Coût rendu France, avec ce qu'on sait et ce qu'on suppose."""
    value_eur: float | None
    confidence: str                # HIGH | MEDIUM | LOW | UNKNOWN
    basis: str
    components: dict = field(default_factory=dict)


def landed_cost_fr(price: float | None, currency: str, region: str, fx_usd_eur: float,
                   shipping_eur: float | None = None) -> Landed:
    """EU : prix + port. US : prix + port intérieur + transitaire + TVA.

    La confiance dit ce qui a été MESURÉ et ce qui a été supposé :
      HIGH    tout est connu, port compris
      MEDIUM  prix connu, port estimé sur une moyenne de notre propre historique
      LOW     conversion de devise en plus de l'estimation de port
      UNKNOWN pas de prix — et alors on ne rend pas un chiffre, on rend None
    """
    if not price or price <= 0:
        return Landed(None, "UNKNOWN", "aucun prix exploitable")
    eur = price if currency == "EUR" else price * fx_usd_eur
    if region != "US":
        ship = shipping_eur if shipping_eur is not None else EU_SHIP_DEFAULT_EUR
        conf = "HIGH" if shipping_eur is not None else "MEDIUM"
        if currency not in ("EUR",):
            conf = "MEDIUM" if conf == "HIGH" else "LOW"
        return Landed(round(eur + ship, 2), conf,
                      "intra-UE : prix + port, ni douane ni TVA à l'import",
                      {"produit_eur": round(eur, 2), "port_eur": ship})
    # États-Unis : la chaîne complète, chaque poste nommé
    sub = eur + US_DOMESTIC_SHIP_EUR + MYUS_PER_UNIT_EUR
    tva = sub * VAT_FR
    total = sub + tva + sub * CUSTOMS_RATE
    return Landed(round(total, 2), "LOW",
                  "États-Unis : prix + port intérieur + transitaire + TVA — les deux derniers "
                  "postes sont des moyennes tirées de nos propres factures",
                  {"produit_eur": round(eur, 2), "port_us_eur": US_DOMESTIC_SHIP_EUR,
                   "transitaire_eur": MYUS_PER_UNIT_EUR, "tva_eur": round(tva, 2)})


# ---------------------------------------------------------------- notation
TIERS = [(70, "🔥🔥 STRONG DEAL"), (80, "🔥 DEAL"), (90, "🟢 GOOD"),
         (105, "🟡 MARKET"), (120, "🟠 EXPENSIVE")]


def deal_tier(landed_eur: float | None, sold_median_eur: float | None,
              sold_confidence: str | None) -> tuple[str, float | None]:
    """Le palier, et le ratio qui l'a produit. Sans sold fiable : aucun palier, aucun ratio.

    « Fiable » veut dire confiance MEDIUM ou HIGH. Un sold LOW — trois ventes sur cent vingt
    jours, dispersion forte — documente le produit sans autoriser à en déduire une remise.
    """
    if landed_eur is None or not sold_median_eur or sold_confidence not in ("HIGH", "MEDIUM"):
        return "NO_RELIABLE_SOLD_DATA", None
    ratio = landed_eur / sold_median_eur * 100
    for seuil, nom in TIERS:
        if ratio <= seuil:
            return nom, round(ratio, 1)
    return "🔴 PASS", round(ratio, 1)


def wemby_score(sku: dict, tier: str, ratio: float | None, seller_trust: str | None,
                in_stock: bool) -> tuple[int, list[str]]:
    """WEMBY HUNT SCORE /100, et les raisons qui l'expliquent.

    Le score est PLAFONNÉ quand la donnée manque, jamais complété par une moyenne. Un produit
    sans Wembanyama ne peut pas dépasser 20 : ce n'est pas une chasse Wemby, c'est du stock.
    """
    why, score = [], 0
    present = sku.get("wemby_present")
    if present is False:
        return 5, [f"aucun Wembanyama ({sku.get('league') or 'NBA'}) — hors chasse"]
    if present is None:
        why.append("présence de Wembanyama NON VÉRIFIÉE — plafond à 45")

    # 1. la remise, seule composante qui peut valoir beaucoup, et seulement si elle est prouvée
    if ratio is not None:
        gain = max(0, min(40, int((100 - ratio) * 1.6)))
        score += gain
        why.append(f"{gain}/40 · {ratio:.0f} % du sold médian")
    else:
        why.append("0/40 · aucune vente réalisée fiable — la remise reste inconnue")

    # 2. le statut de la carte : une RC NBA n'a pas d'équivalent
    if sku.get("wemby_rc") is True:
        score += 25; why.append("25/25 · rookie card NBA officielle")
    elif sku.get("league") in ("EuroLeague", "Collegiate/Draft"):
        score += 10; why.append(f"10/25 · Wembanyama présent mais hors RC NBA ({sku['league']})")
    else:
        why.append("0/25 · statut RC inconnu")

    # 3. le niveau du produit : un hobby porte des autos, un blaster porte de l'espoir
    tier_pts = {"hobby": 15, "retail": 8}.get(sku.get("tier"), 5)
    score += tier_pts
    why.append(f"{tier_pts}/15 · gamme {sku.get('tier') or 'inconnue'}")

    # 4. la liquidité : ce qui s'achète partout se revend partout
    n = len(sku.get("market_ask_from") or [])
    liq = 10 if n >= 4 else 6 if n >= 2 else 2
    score += liq
    why.append(f"{liq}/10 · {n} vendeur(s) connus")

    # 5. le risque vendeur retranche, il n'ajoute jamais
    if seller_trust == "high_risk":
        score -= 20; why.append("−20 · vendeur à risque")
    elif seller_trust == "watch":
        score -= 5; why.append("−5 · vendeur sans historique chez nous")
    if not in_stock:
        score -= 15; why.append("−15 · pas en stock")

    if present is None:
        score = min(score, 45)
    if ratio is None:
        score = min(score, 60)
        why.append("plafonné à 60 : sans sold fiable, aucun score ne peut prétendre mieux")
    return max(0, min(100, score)), why


# ---------------------------------------------------------------- événements
EVENTS = ("NEW_PRODUCT", "NEW_SELLER", "CATALOG_GAP", "OLD_STOCK", "RESTOCK",
          "NEW_LOW", "PRICE_DROP", "DEAL", "STRONG_DEAL")

# Un produit d'une saison révolue encore en rayon : c'est le motif qui a fait trouver le
# Prizm Draft Picks chez Stickerpoint. On le date par rapport à la saison courante.
OLD_STOCK_SEASONS = ("2023-24", "2024-25")


def detect_events(*, sku: dict, price: float | None, in_stock: bool, was_in_stock: bool | None,
                  prev_price: float | None, hist_low: float | None, tier: str,
                  seller_is_new: bool, product_is_new: bool) -> list[dict]:
    """Les événements que cette ligne déclenche, avec leur motif en clair.

    Un événement n'est pas un verdict : il dit ce qui a CHANGÉ ou ce qui est REMARQUABLE.
    Le verdict de prix, lui, reste le travail de price_verdict().
    """
    ev = []
    if product_is_new:
        ev.append({"type": "NEW_PRODUCT",
                   "why": "produit absent du catalogue, découvert par exploration"})
        ev.append({"type": "CATALOG_GAP",
                   "why": f"{sku.get('set')} / {sku.get('format')} existe et n'était pas surveillé"})
    if seller_is_new:
        ev.append({"type": "NEW_SELLER", "why": "vendeur découvert lors de cette prospection"})
    if in_stock and sku.get("season") in OLD_STOCK_SEASONS:
        ev.append({"type": "OLD_STOCK",
                   "why": f"saison {sku['season']} encore en rayon — devenue difficile à trouver"})
    if in_stock and was_in_stock is False:
        ev.append({"type": "RESTOCK", "why": "était en rupture au passage précédent"})
    if price and hist_low is not None and price < hist_low:
        ev.append({"type": "NEW_LOW",
                   "why": f"{price:.2f} sous le plus bas connu {hist_low:.2f}"})
    if price and prev_price and price < prev_price * 0.9:
        ev.append({"type": "PRICE_DROP",
                   "why": f"−{(1 - price / prev_price) * 100:.0f} % depuis le dernier passage"})
    if tier.startswith("🔥🔥"):
        ev.append({"type": "STRONG_DEAL", "why": "coût rendu à 70 % ou moins des ventes réalisées"})
    elif tier.startswith("🔥"):
        ev.append({"type": "DEAL", "why": "coût rendu à 80 % ou moins des ventes réalisées"})
    return ev


def implausible(price: float | None, sold_median: float | None, ref_ask: float | None) -> str | None:
    """Un prix trop beau n'est pas une affaire, c'est un signal d'erreur ou d'appât.

    Vécu deux fois : jojosbazar affichait l'EuroLeague Hobby à 59,96 $ contre 130 $ de marché,
    et un Cactus Jack Hobby apparaît aujourd'hui à 30 € contre 600 € ailleurs. Dans les deux
    cas, ce n'est pas une remise de 80 %, c'est une fiche qui ment ou un produit qui n'est pas
    celui qu'on croit. On refuse de le noter, on le signale.
    """
    ref = sold_median or ref_ask
    if not price or not ref or price <= 0:
        return None
    if price < ref * 0.25:
        return (f"prix à {price / ref * 100:.0f} % de la référence — invraisemblable. "
                f"Fiche erronée, mauvais produit, ou appât : à vérifier à la main avant tout achat.")
    return None


# ---------------------------------------------------------------- référence de marché graduée
# Les ventes réalisées restent inaccessibles à l'échelle : sportscardspro, 130point et
# cardladder refusent tout client automatisé, pricecharting ne couvre pas le scellé. Plutôt que
# de laisser 307 SKU sans aucune intelligence prix, on gradue ce qu'on SAIT, en nommant à chaque
# fois la nature de la donnée. Une médiane d'asks n'est pas une cote — mais dire « huit vendeurs
# demandent entre 340 et 500, celui-ci en demande 210 » est une information utile et vraie.
REF_LEVELS = ("SOLD_MEDIAN", "SOLD_RANGE", "MARKET_ESTIMATE", "ASK_ONLY", "UNKNOWN")


def market_reference(*, sold_median=None, sold_confidence=None, sold_n=0,
                     asks: list[float] | None = None, n_sellers: int = 0):
    """Le meilleur niveau de référence disponible, et sa confiance.

    SOLD_MEDIAN      des ventes réelles, en nombre et récentes            HIGH
    SOLD_RANGE       des ventes réelles mais peu nombreuses ou dispersées MEDIUM
    MARKET_ESTIMATE  pas de vente, mais assez de vendeurs pour cerner     MEDIUM/LOW
    ASK_ONLY         un ou deux prix demandés, rien de plus               LOW
    UNKNOWN          rien                                                 —
    """
    if sold_median and sold_confidence in ("HIGH", "MEDIUM") and sold_n >= 5:
        return {"level": "SOLD_MEDIAN", "value": sold_median, "confidence": "HIGH",
                "n": sold_n, "why": f"{sold_n} ventes réalisées"}
    if sold_median and sold_n >= 2:
        return {"level": "SOLD_RANGE", "value": sold_median, "confidence": "MEDIUM",
                "n": sold_n, "why": f"seulement {sold_n} vente(s) réalisée(s) — fourchette, pas cote"}
    a = sorted(x for x in (asks or []) if x and x > 0)
    if len(a) >= 4 and n_sellers >= 4:
        med = a[len(a) // 2]
        disp = (a[-1] - a[0]) / med if med else 9
        return {"level": "MARKET_ESTIMATE", "value": med,
                "confidence": "MEDIUM" if disp <= 1.0 else "LOW", "n": len(a),
                "why": f"{n_sellers} vendeurs, aucune vente connue — estimation sur prix demandés",
                "low": a[0], "high": a[-1], "dispersion": round(disp, 2)}
    if a:
        return {"level": "ASK_ONLY", "value": a[len(a) // 2], "confidence": "LOW", "n": len(a),
                "why": f"{len(a)} prix demandé(s) seulement", "low": a[0], "high": a[-1]}
    return {"level": "UNKNOWN", "value": None, "confidence": None, "n": 0,
            "why": "aucune donnée de prix"}


def cross_retailer_low(price: float, asks: list[float], n_sellers: int,
                       seuil: float = 0.60) -> dict | None:
    """L'anomalie qui ne demande AUCUNE vente réalisée pour être visible.

    Quand huit marchands demandent entre 335 et 799 et qu'un neuvième affiche 335, la question
    n'est pas « quelle est la cote ». C'est qu'un vendeur est très loin de tous les autres, et
    cela mérite un regard — dans les deux sens : soit c'est l'affaire, soit c'est une erreur.

    Il faut au moins quatre vendeurs : à trois, l'écart peut n'être qu'un vendeur cher qui tire
    la médiane, pas un vendeur bon marché.
    """
    others = sorted(x for x in asks if x and x > 0 and abs(x - price) > 1e-9)
    if len(others) < 3 or n_sellers < 4:
        return None
    med = others[len(others) // 2]
    if not med or price >= med * seuil:
        return None
    return {"type": "CROSS_RETAILER_LOW", "price": price, "peer_median": round(med, 2),
            "peer_low": others[0], "peer_high": others[-1], "n_peers": len(others),
            "pct_of_peers": round(price / med * 100, 1),
            "why": (f"{price:.2f} contre une médiane de {med:.2f} sur {len(others)} autres "
                    f"vendeurs ({price / med * 100:.0f} %) — anomalie à vérifier avant achat, "
                    f"pas une remise établie")}


def below_dealer_buy(price: float, dealer_buy: float | None) -> dict | None:
    """Sous le prix auquel un marchand RACHÈTE, c'est-à-dire sous le plancher du marché.

    Un dealer buy price est la donnée la plus dure qui existe hors ventes réalisées : c'est un
    professionnel qui s'engage à payer ce montant. Passer dessous n'arrive normalement pas.
    """
    if not price or not dealer_buy or price >= dealer_buy:
        return None
    return {"type": "BELOW_DEALER_BUY_PRICE", "price": price, "dealer_buy": dealer_buy,
            "why": (f"{price:.2f} sous le prix de rachat marchand connu ({dealer_buy:.2f}) — "
                    f"vérification renforcée du vendeur obligatoire avant toute commande")}


# ---------------------------------------------------------------- confiance vendeur
# Une affirmation du vendeur sur lui-même n'est jamais une preuve. « 100% authentic »,
# « verified US business », « authorized dealer » sur sa propre page ne pèsent rien : ce sont
# des mots qu'il a écrits. Seuls comptent les signaux VÉRIFIABLES AILLEURS.
def seller_confidence(shop: dict) -> tuple[str, list[str]]:
    pts, why = 0, []
    if shop.get("official_topps_retailer"):
        pts += 2; why.append("figure à l'annuaire officiel Topps (source tierce)")
    if shop.get("legitimacy_checked_at") or shop.get("country_corrected_at"):
        pts += 1; why.append("identité vérifiée à la main")
    if shop.get("payment_passes") == "yes":
        pts += 1; why.append("commande réelle passée et honorée")
    if shop.get("trust") == "trusted":
        pts += 1; why.append("historique de crawl sans anomalie")
    elif shop.get("trust") == "high_risk":
        pts -= 3; why.append("marqué à risque")
    if shop.get("price_display_warning"):
        pts -= 1; why.append("affichage HT/TTC non confirmé")
    if shop.get("status") == "watch" and not shop.get("official_topps_retailer"):
        why.append("aucun historique chez nous")
    lvl = "HIGH" if pts >= 3 else "MEDIUM" if pts >= 2 else "LOW" if pts >= 1 else "UNVERIFIED"
    return lvl, why
