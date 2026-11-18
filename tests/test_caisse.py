"""Module cosmétique : produits, scan, panier, remises, tickets, retours, import, statistiques."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import connection as db  # noqa: E402
from services import (caisse_service as cs, session_service as ss, stats_caisse_service as sc,  # noqa: E402
                      utilisateurs_service as us)
from utils.erreurs import ErreurMetier  # noqa: E402


class BaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name
        self.conn = db.ouvrir_base().connexion
        mk = lambda n, i, r: us.obtenir(self.conn, us.creer_utilisateur(self.conn, n, i, "1234", "1234", r))  # noqa: E731
        self.admin, self.karim = mk("Admin", "admin", "ADMIN"), mk("Karim", "karim", "CAISSIER")

    def tearDown(self):
        self.conn.close()
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()

    def produit(self, nom="Shampoing Nivea", achat="300", vente="500", stock="20", codes="6111111111111", **extra):
        return cs.creer_produit(self.conn, {"nom": nom, "prix_achat": achat, "prix_vente": vente,
                                            "quantite_stock": stock, "codes_barres": codes, **extra}, self.admin)

    def ouvrir(self, fond="1000"):
        return ss.ouvrir_session(self.conn, self.karim, fond)

    def stock(self, produit_id):
        return self.conn.execute("SELECT quantite_stock FROM produits_caisse WHERE id=?", (produit_id,)).fetchone()[0]


class TestProduits(BaseTest):
    def test_creation_et_ids(self):
        p = self.produit()
        self.assertEqual(p["code"], f"C-{p['id']}")
        q = self.produit("Rasoir Gillette", codes="", code="GIL1")            # ID choisi, sans code-barres
        self.assertEqual(q["code"], "GIL1")
        with self.assertRaises(ErreurMetier):
            self.produit("Autre", codes="", code="gil1")                      # ID déjà pris (casse ignorée)

    def test_validation(self):
        for champs in ({"nom": ""}, {"prix_vente": "abc"}, {"prix_achat": "-1"}, {"stock": "1,5"}):
            with self.assertRaises(ErreurMetier):
                self.produit(**champs)
        res = self.produit("Piège", achat="900", vente="100", codes="")
        self.assertEqual(len(res["avertissements"]), 1)                       # achat > vente

    def test_codes_barres_multiples_et_uniques(self):
        p = self.produit(codes="111 222, 333;444")
        self.assertEqual(sorted(cs.obtenir(self.conn, p["id"])["codes_barres"].split()), ["111", "222", "333", "444"])
        for code in ("222", "444"):
            self.assertEqual(cs.trouver_exact(self.conn, code)["id"], p["id"])  # chaque code retrouve le produit
        with self.assertRaises(ErreurMetier) as ctx:
            self.produit("Autre", codes="999 333")
        self.assertIn("déjà utilisé", str(ctx.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM produits_caisse").fetchone()[0], 1)  # rien créé

    def test_scan_et_recherche(self):
        p = self.produit("Shampoing Nivea Men", codes="6111111111111")
        self.produit("Gel douche Dove", codes="", code="DOVE")
        self.assertEqual(cs.trouver_exact(self.conn, "6111111111111")["id"], p["id"])    # scan code-barres
        self.assertEqual(cs.trouver_exact(self.conn, "dove")["nom"], "Gel douche Dove")  # ID exact (casse ignorée)
        self.assertIsNone(cs.trouver_exact(self.conn, "000"))
        self.assertEqual([r["nom"] for r in cs.rechercher(self.conn, "nivea men")], ["Shampoing Nivea Men"])
        self.assertEqual(len(cs.rechercher(self.conn, "sham")), 1)                       # partiel
        self.assertEqual(len(cs.rechercher(self.conn, "61111")), 1)                      # code-barres partiel
        self.assertEqual(len(cs.rechercher(self.conn)), 2)
        self.assertEqual(cs.rechercher(self.conn, "zzz"), [])

    def test_modifier_et_supprimer(self):
        p = self.produit(codes="111")
        q = self.produit("Autre", codes="222", code="B")
        champs = {"nom": "Nivea 2", "prix_achat": "310", "prix_vente": "520", "quantite_stock": "20", "seuil_alerte": "5"}
        with self.assertRaises(ErreurMetier):
            cs.modifier_produit(self.conn, p["id"], {**champs, "codes_barres": "222"}, self.admin)   # pris par « Autre »
        with self.assertRaises(ErreurMetier):
            cs.modifier_produit(self.conn, p["id"], {**champs, "code": "b"}, self.admin)
        cs.modifier_produit(self.conn, p["id"], {**champs, "codes_barres": "111 555"}, self.admin)
        self.assertEqual(cs.trouver_exact(self.conn, "555")["nom"], "Nivea 2")
        cs.supprimer_produit(self.conn, q["id"], self.admin)
        self.assertIsNone(cs.trouver_exact(self.conn, "222"))                   # code-barres libéré
        self.produit("Nouveau", codes="222", code="B")                         # ... ainsi que l'ID

    def test_reapprovisionnement_et_inventaire(self):
        p = self.produit(achat="300", stock="10")
        self.assertEqual(cs.reapprovisionner(self.conn, p["id"], "5", "320", self.admin), 15)
        self.assertEqual(cs.obtenir(self.conn, p["id"])["prix_achat"], 320)    # dernier prix d'achat
        log = self.conn.execute("SELECT * FROM logs_caisse WHERE type='ACHAT'").fetchone()
        self.assertEqual((log["quantite"], log["prix"]), (5, 1600))
        self.assertEqual(cs.reapprovisionner(self.conn, p["id"], "2", "", self.admin), 17)   # prix vide = inchangé
        self.assertEqual(cs.ajuster_stock(self.conn, p["id"], "12", self.admin, "casse"), -5)
        self.assertEqual(self.stock(p["id"]), 12)
        for args in (("0", ""), ("1,5", ""), ("2", "abc")):
            with self.assertRaises(ErreurMetier):
                cs.reapprovisionner(self.conn, p["id"], *args)

    def test_alerte_stock_bas(self):
        self.produit("A", stock="3", codes="1")
        self.produit("B", stock="30", codes="2")
        self.assertEqual([x["nom"] for x in cs.produits_en_alerte(self.conn)], ["A"])


class TestPanierEtTickets(BaseTest):
    def test_calcul_du_panier(self):
        lignes = [{"quantite": 2, "prix_unitaire": 500}, {"quantite": 1, "prix_unitaire": 300}]
        c = cs.calculer_panier(lignes)
        self.assertEqual((c["sous_total"], c["total"], c["remise_totale"]), (1300, 1300, 0))
        # remise de ligne en %, puis remise globale en montant
        lignes[0].update(remise_type="POURCENT", remise_valeur=10)                  # -100 sur la ligne 1
        c = cs.calculer_panier(lignes, "MONTANT", 120)                              # -120 sur 1200
        self.assertEqual(c["total"], 1080)
        self.assertEqual(c["remise_totale"], 220)
        self.assertEqual(round(sum(l["total_ligne"] for l in c["lignes"]), 2), 1080)   # la répartition est exacte
        self.assertEqual(cs.calculer_panier(lignes, "POURCENT", 50)["total"], 600)
        self.assertEqual(cs.calculer_panier(lignes, "MONTANT", 99999)["total"], 0)     # remise plafonnée
        for mauvais in ([{"quantite": 0, "prix_unitaire": 1}], [{"quantite": 1, "prix_unitaire": -1}]):
            with self.assertRaises(ErreurMetier):
                cs.calculer_panier(mauvais)
        with self.assertRaises(ErreurMetier):
            cs.calculer_panier(lignes, "POURCENT", 101)

    def test_repartition_remise_globale_sans_perdre_un_centime(self):
        lignes = [{"quantite": 1, "prix_unitaire": 100}] * 3
        c = cs.calculer_panier(lignes, "MONTANT", 10)
        self.assertEqual(round(sum(l["remise_globale"] for l in c["lignes"]), 2), 10)
        self.assertEqual(c["total"], 290)

    def test_vente_exige_une_session(self):
        p = self.produit()
        with self.assertRaises(ErreurMetier) as ctx:
            cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 1}], self.karim)
        self.assertIn("session", str(ctx.exception).lower())
        with self.assertRaises(ErreurMetier):
            cs.valider_ticket(self.conn, [], self.karim)

    def test_ticket_complet(self):
        p = self.produit(achat="300", vente="500", stock="20")
        q = self.produit("Gel", achat="100", vente="250", stock="5", codes="222")
        s = self.ouvrir()
        res = cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 2},
                                            {"produit_id": q["id"], "quantite": 1}], self.karim,
                                montant_donne_txt="2000")
        self.assertEqual((res["total"], res["monnaie"]), (1250, 750))
        self.assertEqual(res["benefice"], 1250 - (600 + 100))
        self.assertEqual((self.stock(p["id"]), self.stock(q["id"])), (18, 4))
        t = self.conn.execute("SELECT * FROM tickets").fetchone()
        self.assertEqual((t["session_id"], t["utilisateur_id"], t["statut"]), (s, self.karim["id"], "VALIDE"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lignes_ticket").fetchone()[0], 2)
        self.assertEqual(ss.calculer(self.conn, s)["attendues"], 1000 + 1250)       # espèces attendues
        log = self.conn.execute("SELECT * FROM logs_caisse WHERE type='VENTE'").fetchone()
        self.assertEqual((log["prix"], log["ticket_id"], log["utilisateur_id"]), (1250, t["id"], self.karim["id"]))

    def test_prix_modifie_remise_et_traçabilite(self):
        p = self.produit(achat="300", vente="500")
        self.ouvrir()
        res = cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 2, "prix_unitaire": 450,
                                             "remise_type": "POURCENT", "remise_valeur": 10}], self.karim,
                                remise_type="MONTANT", remise_valeur=10)
        self.assertEqual(res["total"], 800)             # 900 - 90 (10 %) = 810 ; -10 = 800
        self.assertEqual(res["benefice"], 800 - 600)
        l = self.conn.execute("SELECT * FROM lignes_ticket").fetchone()
        self.assertEqual((l["prix_unitaire"], l["remise_ligne"], l["total_ligne"], l["cout_unitaire"]), (450, 100, 800, 300))
        details = self.conn.execute("SELECT details FROM logs_caisse WHERE type='VENTE'").fetchone()[0]
        self.assertIn("prix", details)
        self.assertIn("remise", details)

    def test_paiement(self):
        p = self.produit(vente="500")
        self.ouvrir()
        with self.assertRaises(ErreurMetier) as ctx:
            cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 1}], self.karim, montant_donne_txt="300")
        self.assertIn("200", str(ctx.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)
        self.assertEqual(self.stock(p["id"]), 20)                                    # rien n'a bougé
        res = cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 1}], self.karim)   # montant vide = juste
        self.assertEqual(res["monnaie"], 0)

    def test_stock_negatif_autorise_avec_avertissement(self):
        p = self.produit(stock="1")
        self.ouvrir()
        res = cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 3}], self.karim)
        self.assertEqual(self.stock(p["id"]), -2)
        self.assertEqual(len(res["avertissements"]), 1)

    def test_erreur_annule_tout(self):
        p = self.produit()
        self.ouvrir()
        with self.assertRaises(ErreurMetier):
            cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 1},
                                          {"produit_id": 999, "quantite": 1}], self.karim)
        self.assertEqual(self.stock(p["id"]), 20)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)

    def test_annulation_de_ticket(self):
        p = self.produit()
        s = self.ouvrir()
        t = cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 2}], self.karim)["ticket_id"]
        with self.assertRaises(ErreurMetier):
            cs.annuler_ticket(self.conn, t, self.karim)                              # réservé à l'admin
        cs.annuler_ticket(self.conn, t, self.admin)
        self.assertEqual(self.stock(p["id"]), 20)
        self.assertEqual(ss.calculer(self.conn, s)["attendues"], 1000)               # l'argent n'est plus attendu
        with self.assertRaises(ErreurMetier):
            cs.annuler_ticket(self.conn, t, self.admin)                              # déjà annulé
        t2 = cs.valider_ticket(self.conn, [{"produit_id": p["id"], "quantite": 1}], self.karim)["ticket_id"]
        ss.cloturer_session(self.conn, s, "1500", self.karim)
        with self.assertRaises(ErreurMetier) as ctx:                                 # session clôturée : refusé
            cs.annuler_ticket(self.conn, t2, self.admin)
        self.assertIn("clôturée", str(ctx.exception))

    def test_mise_en_attente(self):
        p = self.produit()
        panier = [{"produit_id": p["id"], "designation": "x", "quantite": 2, "prix_unitaire": 500, "stock": 20}]
        a = cs.mettre_en_attente(self.conn, self.karim, panier, "MONTANT", 50, "Cliente en bleu")
        attentes = cs.lister_attentes(self.conn)
        self.assertEqual((attentes[0]["nb_articles"], attentes[0]["total"]), (2, 950))
        repris = cs.reprendre_attente(self.conn, a)
        self.assertEqual((repris["remise_type"], repris["remise_valeur"]), ("MONTANT", 50))
        self.assertEqual(repris["lignes"][0]["designation"], "Shampoing Nivea")      # rafraîchi depuis le produit
        self.assertEqual(cs.lister_attentes(self.conn), [])
        with self.assertRaises(ErreurMetier):
            cs.reprendre_attente(self.conn, a)
        a = cs.mettre_en_attente(self.conn, self.karim, panier)
        cs.supprimer_produit(self.conn, p["id"], self.admin)                        # produit supprimé entre-temps
        repris = cs.reprendre_attente(self.conn, a)
        self.assertEqual((repris["lignes"], len(repris["avertissements"])), ([], 1))


class TestRetours(BaseTest):
    def vendre(self, p, quantite=3, prix=None, **kw):
        ligne = {"produit_id": p["id"], "quantite": quantite}
        if prix is not None:
            ligne["prix_unitaire"] = prix
        return cs.valider_ticket(self.conn, [ligne], self.karim, **kw)["ticket_id"]

    def test_retour_partiel_sur_ticket_remis_en_stock(self):
        p = self.produit(achat="300", vente="500")
        s = self.ouvrir()
        t = self.vendre(p, 3)
        ligne = cs.lignes_du_ticket(self.conn, t)[0]
        res = cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1, "remis_en_stock": True}],
                                self.karim, ticket_id=t, motif="Ne convient pas")
        self.assertEqual(res["total_rembourse"], 500)
        self.assertEqual(self.stock(p["id"]), 18)                                  # 20 - 3 + 1
        self.assertEqual(cs.lignes_du_ticket(self.conn, t)[0]["quantite_retournee"], 1)
        self.assertEqual(ss.calculer(self.conn, s)["attendues"], 1000 + 1500 - 500)
        with self.assertRaises(ErreurMetier) as ctx:                               # il n'en reste que 2 à rendre
            cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 3}], self.karim, ticket_id=t)
        self.assertIn("2", str(ctx.exception))
        with self.assertRaises(ErreurMetier):
            cs.annuler_ticket(self.conn, t, self.admin)                            # ticket avec retour : plus annulable

    def test_remboursement_au_prix_paye_avec_remise(self):
        p = self.produit(achat="300", vente="500")
        self.ouvrir()
        t = self.vendre(p, 2, remise_type="MONTANT", remise_valeur=100)            # total 900 : 450 l'unité
        ligne = cs.lignes_du_ticket(self.conn, t)[0]
        res = cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1}], self.karim, ticket_id=t)
        self.assertEqual(res["total_rembourse"], 450)
        res = cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1}], self.karim, ticket_id=t)
        self.assertEqual(res["total_rembourse"], 450)                              # au total : 900, pas un centime de plus

    def test_retour_perte_non_remis_en_stock(self):
        p = self.produit(achat="300", vente="500")
        self.ouvrir()
        t = self.vendre(p, 1)
        ligne = cs.lignes_du_ticket(self.conn, t)[0]
        cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1, "remis_en_stock": False}],
                          self.karim, ticket_id=t)
        self.assertEqual(self.stock(p["id"]), 19)                                  # abîmé : pas remis en stock
        r = sc.resume_periode(self.conn, None, None)
        # vente : +200 de bénéfice ; retour en perte : -500  => -300
        self.assertEqual((r["ventes"], r["retours"], r["ca_net"], r["benefice"]), (500, 500, 0, -300))

    def test_retour_remis_en_stock_annule_le_benefice(self):
        p = self.produit(achat="300", vente="500")
        self.ouvrir()
        t = self.vendre(p, 1)
        ligne = cs.lignes_du_ticket(self.conn, t)[0]
        cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1}], self.karim, ticket_id=t)
        r = sc.resume_periode(self.conn, None, None)
        self.assertEqual((r["ca_net"], r["benefice"], r["cout"]), (0, 0, 0))

    def test_retour_libre(self):
        p = self.produit(achat="300", vente="500")
        s = self.ouvrir()
        res = cs.valider_retour(self.conn, [{"produit_id": p["id"], "quantite": 2}], self.karim)
        self.assertEqual(res["total_rembourse"], 1000)
        self.assertEqual(self.stock(p["id"]), 22)
        res = cs.valider_retour(self.conn, [{"produit_id": p["id"], "quantite": 1, "prix_rembourse_unitaire": 400,
                                             "remis_en_stock": False}], self.karim)
        self.assertEqual(res["total_rembourse"], 400)
        self.assertEqual(ss.calculer(self.conn, s)["attendues"], 1000 - 1000 - 400)
        with self.assertRaises(ErreurMetier):
            cs.valider_retour(self.conn, [{"produit_id": p["id"], "quantite": 0}], self.karim)

    def test_retour_exige_une_session_et_un_ticket_valide(self):
        p = self.produit()
        with self.assertRaises(ErreurMetier):
            cs.valider_retour(self.conn, [{"produit_id": p["id"], "quantite": 1}], self.karim)
        s = self.ouvrir()
        t = self.vendre(p, 1)
        cs.annuler_ticket(self.conn, t, self.admin)
        ligne = cs.lignes_du_ticket(self.conn, t)[0]
        with self.assertRaises(ErreurMetier):
            cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1}], self.karim, ticket_id=t)
        with self.assertRaises(ErreurMetier):                                       # mélange ticket / libre
            cs.valider_retour(self.conn, [{"ligne_ticket_id": ligne["id"], "quantite": 1}], self.karim)


class TestImport(BaseTest):
    def ecrire(self, texte, nom="catalogue.csv", encodage="utf-8"):
        chemin = os.path.join(self._tmp.name, nom)
        with open(chemin, "w", encoding=encodage, newline="") as f:
            f.write(texte)
        return chemin

    def test_import_csv_point_virgule(self):
        chemin = self.ecrire("Code-barres;Désignation;Catégorie;Prix d'achat;Prix de vente;Stock\n"
                             "6111;Shampoing Nivea;Cheveux;300;500;12\n"
                             "6222;Rasoir Gillette;Rasage;120,5;250;8\n"
                             ";Savon sans code;Corps;40;80;30\n")
        res = cs.importer(self.conn, chemin, self.admin)
        self.assertEqual((res["crees"], res["mis_a_jour"], res["erreurs"]), (3, 0, []))
        self.assertEqual(cs.trouver_exact(self.conn, "6222")["prix_achat"], 120.5)
        self.assertEqual(self.stock(cs.trouver_exact(self.conn, "6111")["id"]), 12)
        self.assertEqual(len(cs.rechercher(self.conn, "savon")), 1)

    def test_reimport_met_a_jour_sans_toucher_au_stock(self):
        cs.importer(self.conn, self.ecrire("code,nom,prix vente,stock\n6111,Nivea,500,12\n"), self.admin)
        res = cs.importer(self.conn, self.ecrire("code,nom,prix vente,stock\n6111,Nivea Men,550,99\n"), self.admin)
        self.assertEqual((res["crees"], res["mis_a_jour"]), (0, 1))
        p = cs.trouver_exact(self.conn, "6111")
        self.assertEqual((p["nom"], p["prix_vente"], p["quantite_stock"]), ("Nivea Men", 550, 12))   # stock intact

    def test_erreurs_ligne_par_ligne(self):
        chemin = self.ecrire("code,nom,prix vente\n6111,Bon,500\n6222,,300\n6333,Prix faux,abc\n6111x,Autre,10\n")
        res = cs.importer(self.conn, chemin, self.admin)
        self.assertEqual(res["crees"], 2)                                            # « Bon » et « Autre »
        self.assertEqual(len(res["erreurs"]), 2)
        self.assertIn("Ligne 3", res["erreurs"][0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM produits_caisse").fetchone()[0], 2)

    def test_colonnes_obligatoires_et_fichiers_invalides(self):
        with self.assertRaises(ErreurMetier):
            cs.importer(self.conn, self.ecrire("code,stock\n1,2\n"), self.admin)
        with self.assertRaises(ErreurMetier):
            cs.importer(self.conn, self.ecrire(""), self.admin)
        with self.assertRaises(ErreurMetier):
            cs.importer(self.conn, os.path.join(self._tmp.name, "absent.csv"), self.admin)

    def test_encodage_windows(self):
        chemin = self.ecrire("code;désignation;prix de vente\n7;Crème hydratante;900\n", encodage="cp1252")
        self.assertEqual(cs.importer(self.conn, chemin, self.admin)["crees"], 1)
        self.assertEqual(cs.rechercher(self.conn, "crème")[0]["nom"], "Crème hydratante")

    def test_import_excel(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl non installé")
        classeur = Workbook()
        feuille = classeur.active
        feuille.append(["Code barre", "Nom", "Prix vente", "Stock"])
        feuille.append([6111111111111.0, "Lait corps", 700, 4])                       # code numérique comme dans Excel
        chemin = os.path.join(self._tmp.name, "catalogue.xlsx")
        classeur.save(chemin)
        self.assertEqual(cs.importer(self.conn, chemin, self.admin)["crees"], 1)
        self.assertEqual(cs.trouver_exact(self.conn, "6111111111111")["nom"], "Lait corps")


class TestStatsCaisse(BaseTest):
    def test_resume_tops_et_logs(self):
        a = self.produit("Shampoing", achat="300", vente="500", codes="1")
        b = self.produit("Parfum luxe", achat="1000", vente="3000", codes="2")
        self.ouvrir()
        for _ in range(3):
            cs.valider_ticket(self.conn, [{"produit_id": a["id"], "quantite": 1}], self.karim)
        cs.valider_ticket(self.conn, [{"produit_id": b["id"], "quantite": 1}], self.karim)
        r = sc.resume_standard(self.conn)["Aujourd'hui"]
        self.assertEqual((r["ventes"], r["nb_tickets"], r["panier_moyen"]), (4500, 4, 1125))
        self.assertEqual((r["cout"], r["benefice"]), (1900, 2600))
        self.assertEqual(sc.top_produits(self.conn, par="quantite")[0]["nom"], "Shampoing")
        self.assertEqual(sc.top_produits(self.conn, par="benefice")[0]["nom"], "Parfum luxe")
        self.assertEqual(sc.valeur_stock(self.conn), 17 * 300 + 19 * 1000)
        logs = sc.lister_logs(self.conn, None, None, "Ventes")
        self.assertEqual(len(logs), 4)
        t = sc.totaux_logs(logs)
        self.assertEqual((t["ca"], t["cout"], t["benefice"]), (4500, 1900, 2600))

    def test_filtre_ventes_masque_les_tickets_annules(self):
        a = self.produit()
        self.ouvrir()
        t1 = cs.valider_ticket(self.conn, [{"produit_id": a["id"], "quantite": 1}], self.karim)["ticket_id"]
        cs.valider_ticket(self.conn, [{"produit_id": a["id"], "quantite": 1}], self.karim)
        cs.annuler_ticket(self.conn, t1, self.admin)
        self.assertEqual(len(sc.lister_logs(self.conn, None, None, "Ventes")), 1)
        types = sorted(l["type"] for l in sc.lister_logs(self.conn, None, None, "Tous") if l["type"] in ("VENTE", "ANNULATION"))
        self.assertEqual(types, ["ANNULATION", "VENTE", "VENTE"])
        t = sc.totaux_logs(sc.lister_logs(self.conn, None, None, "Tous"))
        self.assertEqual(t["ca"], 500)                                              # 2 ventes - 1 annulation
        self.assertEqual(sc.resume_standard(self.conn)["Aujourd'hui"]["nb_tickets"], 1)

    def test_achats_et_utilisateur_dans_les_logs(self):
        a = self.produit()
        cs.reapprovisionner(self.conn, a["id"], "10", "300", self.admin)
        logs = sc.lister_logs(self.conn, None, None, "Stock (achats, inventaires)")
        self.assertEqual((logs[0]["utilisateur_nom"], sc.totaux_logs(logs)["achats"]), ("Admin", 3000))


if __name__ == "__main__":
    unittest.main()
