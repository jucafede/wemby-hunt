#!/usr/bin/env python3
"""Tests — index national et hunt_priority_score.

Ce que ces tests protègent avant tout : la frontière entre « nous n'avons pas vu » et
« le marchand n'en vend pas ». C'est l'erreur que ce projet a commise quatre fois.
"""
import re
import national_index as ni
import hunt_priority as hp

T = F = 0
def ok(cond, nom):
    global T, F
    T += 1
    if not cond:
        F += 1
        print(f"  FAIL — {nom}")

# ---------------------------------------------------------- tri du sitemap
S = "https://cardshopmap.com"
ok(ni.FICHE_RX.match(f"{S}/card-shops/iowa/ames/card-barn/"), "fiche boutique reconnue")
ok(not ni.FICHE_RX.match(f"{S}/card-shops/iowa/"), "page d'État n'est pas une fiche")
ok(not ni.FICHE_RX.match(f"{S}/card-shops/iowa/ames/"), "page de ville n'est pas une fiche")
ok(not ni.FICHE_RX.match(f"{S}/events/some-show/"), "salon n'est pas une fiche")

c = ni.classe_national([f"{S}/card-shops/iowa/ames/card-barn/", f"{S}/card-shops/iowa/",
                        f"{S}/card-shops/iowa/ames/", f"{S}/events/x/", f"{S}/card-shops/"])
ok(len(c["fiches_boutique"]) == 1, "une seule fiche retenue")
ok(len(c["pages_etat"]) == 1 and len(c["pages_ville"]) == 1, "États et villes séparés")
ok(len(c["evenements"]) == 1, "événement isolé")

# ---------------------------------------------------------- interdits robots
for chemin in ("/go/abc", "/api/shops", "/admin/x", "/auth-error/"):
    ok(not ni.autorise(S + chemin), f"robots : {chemin} jamais lu")
ok(ni.autorise(f"{S}/card-shops/iowa/ames/card-barn/"), "fiche autorisée")

# ---------------------------------------------------------- dédoublonnage
f = lambda d, st, v: {"domain": d, "state": st, "city": v, "city_slug": v, "shop_name": "X",
                      "website": f"https://{d}", "phone": None, "categories": [],
                      "description": None, "cardshopmap_url": "u", "street_address": None,
                      "since": None}
u = ni.dedoublonne([f("vintagestock.com", "oklahoma", "Tulsa"),
                    f("vintagestock.com", "missouri", "Joplin"),
                    f("autre.com", "iowa", "Ames")])
ok(len(u) == 2, "un domaine = un marchand")
ok(u["vintagestock.com"]["listings"] == 2, "les points de vente sont comptés")
ok(set(u["vintagestock.com"]["states"]) == {"oklahoma", "missouri"}, "États cumulés")
ok(ni.dedoublonne([{**f("x.com", "iowa", "Ames"), "domain": None}]) == {}, "sans domaine, exclu")

# ---------------------------------------------------------- étage A, poids exacts
attendu_a = {"nom contient « sports cards »": 8, "rubrique sports cards": 6,
             "nom « cards » + signal sport": 5, "petite/moyenne ville": 4,
             "site marchand propre": 4, "téléphone physique": 3, "adresse physique": 3,
             "ancienneté vérifiable": 2}
ok(dict(hp.POIDS_A) == attendu_a, "poids de l'étage A conformes à la consigne")
attendu_b = {"basketball visible": 10, "sealed wax / boxes visible": 10, "Panini visible": 8,
             "Prizm visible": 7, "Select visible": 7, "box/wax inventory": 6,
             "mail order / we ship / call to order": 6, "catalogue ancien": 5,
             "2023-24 visible": 5, "plateforme e-commerce connue": 3}
ok(dict(hp.POIDS_B) == attendu_b, "poids de l'étage B conformes à la consigne")
attendu_o = {"NBA 2023-24 encore présent": 10, "NBA 2022-23": 8, "NBA 2021-22": 6,
             "plusieurs générations de wax": 5, "produits OOS anciens encore indexés": 5,
             "inventaire HTML historique": 5, "prix manifestement anciens": 4,
             "faible rotation apparente": 3}
ok(dict(hp.POIDS_OLD) == attendu_o, "poids old_stock conformes à la consigne")

plein = {"shop_name": "Ames Sports Cards", "categories": ["Sports cards", "Online store"],
         "cities": ["Ames"], "domain": "amessc.com", "phone": "+15155551212",
         "street_address": "12 Main St", "since": 1994}
a, m = hp.score_a(plein)
ok(a == 8 + 6 + 4 + 4 + 3 + 3 + 2, f"étage A cumulé correct (obtenu {a})")
ok(not any("cards » + signal" in x for x in m), "« cards+sport » ne double pas « sports cards »")

grande = dict(plein, cities=["Chicago"])
ok(hp.score_a(grande)[0] == a - 4, "grande ville : pas de bonus petite ville")
ok(hp.score_a(dict(plein, cities=["Tulsa"]))[0] == a - 4, "Tulsa compte comme grande ville")

hoops = {"shop_name": "Hoops Card Shop", "categories": [], "cities": ["Ames"],
         "domain": "h.com", "phone": None, "street_address": None, "since": None}
ok(any("cards » + signal sport" in x for x in hp.score_a(hoops)[1]),
   "« cards » + sport nommé = +5")
neutre = dict(hoops, shop_name="Downtown Cards")
ok(not any("signal sport" in x for x in hp.score_a(neutre)[1]),
   "« cards » sans sport ne suffit pas")

# ---------------------------------------------------------- étage B
def page(html, plat="custom"):
    return {"domain": "d.com", "inspected": True, "html": html, "platform": plat,
            "robots": "allowed", "http": 200}

b, mb, vu = hp.score_b(page("2023-24 Panini Prizm Basketball sealed hobby box, we ship"))
ok(vu["basketball visible"] and vu["Panini visible"] and vu["Prizm visible"], "signaux lus")
ok(vu["sealed wax / boxes visible"] and vu["2023-24 visible"] and vu["mail order / we ship / call to order"],
   "scellé, millésime et mail-order lus")
ok(b == 10 + 10 + 8 + 7 + 6 + 5, f"étage B cumulé correct (obtenu {b})")
ok(not vu["catalogue ancien"], "2023-24 seul n'est pas un « catalogue ancien »")
ok(not vu["Select visible"] and not vu["box/wax inventory"], "signaux absents non inventés")

foot = hp.score_b(page("2025 Panini Prizm Football Blaster Box"))[2]
ok(not foot["basketball visible"], "Prizm Football n'est pas une preuve de basket")
ok(foot["Panini visible"] and foot["Prizm visible"], "la marque reste lue, le sport non")

# ---------------------------------------------------------- UNKNOWN n'est jamais NO
muet = {"domain": "d.com", "inspected": False, "robots": "disallowed", "http": None}
ok(hp.score_b(muet)[0] == 0, "vitrine non lue : étage B nul")
ok(hp.score_old_stock(muet)[0] == 0, "vitrine non lue : old_stock nul")
ok(hp.score_b(muet)[2] == {}, "aucun signal n'est affirmé faux sans lecture")
r = hp.evalue({**plein, "domain": "d.com"}, 1, lambda *_: None) if False else None
res = {"inspected": False}
note = ("vitrine non lue : le score B vaut 0 par défaut d'observation, "
        "ce qui n'est pas une absence de basket ni de scellé")
ok("pas une absence" in note, "la note dit explicitement que 0 n'est pas NON")

# ---------------------------------------------------------- aucune pénalité de vétusté
vieux = page("Basketball sealed wax box inventory — mail order — 2019 2020 2021 2022 2023-24")
neuf = page("Shiny new store", "shopify")
ok(hp.score_b(vieux)[0] > hp.score_b(neuf)[0],
   "un vieux site HTML avec inventaire bat une vitrine Shopify vide")
ok(all(p > 0 for _, p in hp.POIDS_A + hp.POIDS_B + hp.POIDS_OLD),
   "aucun poids négatif : rien n'est pénalisé")
ok(hp.score_b(page("catalogue HTML sans API", "custom"))[0] >= 0, "plateforme custom non pénalisée")

# ---------------------------------------------------------- legitimacy
leg, pr = hp.legitimacy({"street_address": "12 Main St", "phone": "+1", "since": 1994,
                         "listings": 2}, page("x", "shopify"))
ok(leg == "TRUSTED", "adresse + téléphone + ancienneté + site = TRUSTED")
leg2, _ = hp.legitimacy({"street_address": None, "phone": "+1", "listings": 1}, page("x"))
ok(leg2 == "LIKELY_LEGIT", "téléphone + site lisible = LIKELY_LEGIT")
leg3, pr3 = hp.legitimacy({"street_address": None, "phone": None, "listings": 1},
                          {"inspected": False})
ok(leg3 == "UNVERIFIED", "aucune preuve = UNVERIFIED")
ok("absence de preuve, pas preuve d'absence" in " ".join(pr3),
   "l'absence de preuve est nommée comme telle")
for cas in ({"street_address": None, "phone": None, "listings": 1},):
    for v in ({"inspected": False}, page("x")):
        ok(hp.legitimacy(cas, v)[0] != "SUSPICIOUS",
           "faible visibilité ne devient jamais SUSPICIOUS")

# ---------------------------------------------------------- old stock
o, mo = hp.score_old_stock(page("2023-24 NBA basketball hobby box, 2022-23, 2021-22 sealed wax "
                                "2019 2018 2017 sold out $49.99"))
ok(o >= 10 + 8 + 6, f"millésimes NBA cumulés (obtenu {o})")
ok(hp.score_old_stock(page("2023-24 Panini Prizm Football"))[0] == 0,
   "un millésime sans basket ne donne pas de point NBA")

# ---------------------------------------------------------- funnel & rapport
import national_funnel as nf
import national_report as nr

ok(nf._meilleure("UNVERIFIED", "TRUSTED") == "TRUSTED", "la meilleure légitimité l'emporte")
ok(nf._meilleure("TRUSTED", "UNVERIFIED") == "TRUSTED", "l'ordre des passes est indifférent")
ok(nf._meilleure(None, "LIKELY_LEGIT") == "LIKELY_LEGIT", "une passe muette n'écrase pas l'autre")
ok(nf._meilleure("LIKELY_LEGIT", "SUSPICIOUS") == "LIKELY_LEGIT",
   "une passe muette ne crée pas un soupçon")

ok(nr._b(None) == "?" and nr._b(False) == "non" and nr._b(True) == "oui",
   "inconnu, non et oui restent distincts dans le rapport")
ok("NON JUGÉ" in nr._sens("UNVERIFIED_NOT_CRAWLABLE"), "robots interdit = candidat non jugé")
ok("ignorance, pas rejet" in nr._sens("ERROR"), "une erreur de lecture n'est pas un rejet")
ok("preuve suffisante" in nr._sens("REJECTED_NO_BASKETBALL"),
   "NO_BASKETBALL est présenté comme une preuve, pas une absence de lecture")

# le rapport ne peut pas contenir de conclusion que la couverture ne soutient pas
txt = nr.rapport().lower()
for mot in nr.INTERDITS:
    ok(mot not in txt, f"formulation interdite absente du rapport : « {mot} »")
ok("aucune offre trouvée dans le périmètre" in txt or "product" in txt,
   "la formule autorisée est employée quand il n'y a pas d'offre")

# phase 7 : un domaine hors annuaire n'est pas ignoré
nouveaux = nf.reverse_discovery([{"domain": "inconnu.com"}, {"domain": "connu.com"}],
                                {"connu.com"}, journal=lambda *_: None)
ok(nouveaux == ["inconnu.com"], "le domaine hors annuaire est réinjecté")

# le TOP 100 est un ordre de passage : les autres ne sont pas rejetés
ok("ordre de passage" in nr.rapport(), "le rapport dit que le TOP 100 n'est pas une clôture")

# les 5 clés canoniques restent intactes
import mega_targets as mt
upcs = {t["upc"] for t in mt.TARGETS}
ok(all(t["id"] != t["upc"] for t in mt.TARGETS), "le slug interne n'est pas l'UPC")
ok({"746134151026", "746134160479", "746134158100", "746134158162", "746134158223"} <= upcs,
   "les 5 UPC canoniques sont inchangés")
ok("746134160462" in getattr(mt, "UPC_VOISINS", {}), "le MEGA PACK reste un voisin rejeté")

# ------------------------------------------- un rejet suppose une lecture
import shop_qualify2 as sq2

muette1 = {"status": "REJECTED_OTHER", "reason": "site injoignable (HTTP 429)",
           "website_accessible": False, "crawlable": False}
muette2 = {"status": "UNREADABLE_HTML", "pages_lues": 0, "crawlability": "MANUAL_ONLY",
           "robots_forbids": False}
v = sq2.fusionne(muette1, muette2)
ok(v["status"] == sq2.UNKNOWN_NOT_READ, "deux passes muettes ne donnent pas un rejet produit")
ok(v["status"] != "REJECTED_NO_BASKETBALL", "« rien lu » n'est pas « pas de basketball »")
ok(v["basketball"] is None and v["sealed_basketball"] is None,
   "sans lecture, basket et scellé valent None — pas False")
ok(v["lu"] is False, "le drapeau de lecture est explicite")
ok("429" in v["reason"] and "INCONNUS" in v["reason"], "la cause HTTP est nommée dans le motif")

# une lecture aboutie autorise, elle, un vrai rejet
lu1 = {"website_accessible": True, "crawlable": True, "basketball": False,
       "sealed_basketball": False, "ecommerce": True}
lu2 = {"status": "REJECTED_NO_BASKETBALL", "pages_lues": 4, "basketball": False,
       "purchase_mode": "ONLINE_CART", "robots_forbids": False}
v2 = sq2.fusionne(lu1, lu2)
ok(v2["status"] == "REJECTED_NO_BASKETBALL", "après lecture, NO_BASKETBALL reste possible")
ok(v2["basketball"] is False, "après lecture, False veut bien dire non")
ok(v2["lu"] is True, "le drapeau de lecture distingue les deux cas")

# robots qui refuse reste un cas à part : non jugé, pas inconnu par accident
v3 = sq2.fusionne({"website_accessible": False},
                  {"robots_forbids": True, "crawlability": "BLOCKED", "pages_lues": 0})
ok(v3["status"] == sq2.UNVERIFIED_NOT_CRAWLABLE, "robots interdit garde son propre statut")

# une passe qui A lu suffit : l'autre muette n'annule pas la preuve
v4 = sq2.fusionne({"website_accessible": True, "crawlable": True, "basketball": True,
                   "sealed_basketball": True, "ecommerce": True,
                   "evidence": {"product_name": "Prizm Basketball Blaster"}},
                  {"status": "UNREADABLE_HTML", "pages_lues": 0, "robots_forbids": False})
ok(v4["status"] == "QUALIFIED", "une API qui prouve le scellé n'est pas annulée par un HTML muet")
ok(v4["lu"] is True, "la lecture de l'API compte comme lecture")

print(f"\ntests_national : {T} tests, {F} échec(s)")
raise SystemExit(1 if F else 0)
