"""Test de fumée des écrans (faux widgets) : parcours complet de l'application."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gui_stubs  # noqa: E402

gui_stubs.installer()

from database import connection as db  # noqa: E402
from services import session_service as ss, utilisateurs_service as us  # noqa: E402
from views.application import Application  # noqa: E402
from views.dialogues import DialogueModifier  # noqa: E402
from views.dialogues_caisse import DialogueAttentes, DialogueProduitCaisse  # noqa: E402
from views.dialogues_session import DialogueCloture, DialogueMouvement, DialogueOuvertureSession  # noqa: E402
from views.dialogues_utilisateurs import DialogueUtilisateur, DialogueUtilisateurs  # noqa: E402


def saisir(entree, texte):
    entree.delete(0, "end")
    entree.insert(0, texte)


class BaseGui(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name
        gui_stubs.messages.reinitialiser()
        self.conn = db.ouvrir_base().connexion
        self.app = Application(self.conn)
        self.app._demarrer()
        self.m = gui_stubs.messages

    def tearDown(self):
        self.conn.close()
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()

    def premier_admin(self):
        """Premier lancement : création du compte administrateur -> accueil."""
        vue = self.app._vue
        saisir(vue.nom, "Boss")
        saisir(vue.mot_de_passe, "1234")
        saisir(vue.confirmation, "1234")
        vue._creer()
        self.assertEqual(self.m.erreurs, [])
        self.assertEqual(self.app.ctx.utilisateur["role"], "ADMIN")

    def ouvrir_session(self, fond="1000"):
        dialogue = DialogueOuvertureSession(self.app, self.app.ctx, None)
        saisir(dialogue.entree, fond)
        dialogue._ouvrir()
        self.assertEqual(self.m.erreurs, [])

    def remplir(self, formulaire, valeurs):
        for cle, texte in valeurs.items():
            saisir(formulaire.entrees[cle], texte)

    def stock(self, table, col, id_=1):
        return self.conn.execute(f"SELECT {col} FROM {table} WHERE id=?", (id_,)).fetchone()[0]


class TestConnexionEtAccueil(BaseGui):
    def test_premier_demarrage_puis_connexion(self):
        self.assertFalse(us.a_des_utilisateurs(self.conn))
        self.premier_admin()
        self.assertEqual(us.lister_utilisateurs(self.conn)[0]["identifiant"], "admin")
        # déconnexion -> écran de connexion
        self.app.deconnecter()
        login = self.app._vue
        saisir(login.identifiant, "admin")
        saisir(login.mot_de_passe, "faux")
        login._valider()
        self.assertIsNone(self.app.ctx.utilisateur)
        self.assertIn("incorrect", login.message.cget("text"))
        saisir(login.mot_de_passe, "1234")
        login._valider()
        self.assertEqual(self.app.ctx.utilisateur["nom"], "Boss")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM logs_caisse WHERE type='CONNEXION'").fetchone()[0], 2)

    def test_les_deux_modules_et_le_bouton_retour(self):
        self.premier_admin()
        self.app.ouvrir_module("PARFUM")
        self.assertEqual(set(self.app.modules["PARFUM"].sections), {"Création", "Stock", "Vente", "Logs", "Session", "Paramètres"})
        self.app.ouvrir_module("COSMETIQUE")
        self.assertEqual(set(self.app.modules["COSMETIQUE"].sections), {"Caisse", "Retours", "Stock", "Logs", "Session"})
        self.app.modules["PARFUM"].retour_accueil()              # le bouton « Retour à l'accueil »
        self.assertNotIn(self.app._vue, self.app.modules.values())
        self.assertEqual(self.m.erreurs, [])

    def test_gestion_des_utilisateurs_par_l_admin(self):
        self.premier_admin()
        d = DialogueUtilisateur(self.app, self.conn, None, lambda: None)
        saisir(d.nom, "Karim")
        saisir(d.identifiant, "karim")
        saisir(d.mot_de_passe, "1234")
        saisir(d.confirmation, "1234")
        d._enregistrer()
        self.assertEqual(self.m.erreurs, [])
        self.assertEqual(us.authentifier(self.conn, "karim", "1234")["role"], "CAISSIER")
        d = DialogueUtilisateur(self.app, self.conn, None, lambda: None)           # doublon refusé
        saisir(d.nom, "Autre")
        saisir(d.identifiant, "KARIM")
        saisir(d.mot_de_passe, "1234")
        saisir(d.confirmation, "1234")
        d._enregistrer()
        self.assertEqual(len(self.m.erreurs), 1)
        liste = DialogueUtilisateurs(self.app, self.conn)
        self.assertEqual(len(liste.tableau.arbre.lignes), 2)

    def test_droits_du_caissier(self):
        self.premier_admin()
        us.creer_utilisateur(self.conn, "Karim", "karim", "1234", "1234", "CAISSIER")
        self.app.deconnecter()
        login = self.app._vue
        saisir(login.identifiant, "karim")
        saisir(login.mot_de_passe, "1234")
        login._valider()
        self.assertEqual(self.app.ctx.utilisateur["role"], "CAISSIER")
        self.app.ouvrir_module("PARFUM")
        self.assertEqual(set(self.app.modules["PARFUM"].sections), {"Vente", "Session"})         # rien d'autre
        self.app.ouvrir_module("COSMETIQUE")
        cosm = self.app.modules["COSMETIQUE"]
        self.assertEqual(set(cosm.sections), {"Caisse", "Retours", "Stock", "Session"})
        stock = cosm.vue("Stock")
        self.assertFalse(stock.modifiable)
        self.assertFalse(stock.voir_achat)                                                    # pas de prix d'achat
        self.assertEqual(self.m.erreurs, [])


class TestPerformance(BaseGui):
    """Les écrans ne sont ni reconstruits ni rechargés inutilement (c'est ce qui ralentissait l'application)."""

    def test_sections_construites_a_la_demande(self):
        self.premier_admin()
        self.app.ouvrir_module("COSMETIQUE")
        module = self.app.modules["COSMETIQUE"]
        self.assertEqual(set(module.vues), {"Caisse"})                       # seule la section ouverte est construite
        module.afficher("Retours")
        self.assertEqual(set(module.vues), {"Caisse", "Retours"})
        self.assertIs(module.vue("Caisse"), module.vue("Caisse"))            # jamais reconstruite

    def test_accueil_et_modules_reutilises(self):
        self.premier_admin()
        accueil = self.app._vue
        self.app.ouvrir_module("PARFUM")
        module = self.app.modules["PARFUM"]
        for _ in range(3):                                                    # aller-retour accueil <-> modules
            self.app.afficher_accueil()
            self.assertIs(self.app._vue, accueil)
            self.app.ouvrir_module("PARFUM")
            self.app.ouvrir_module("COSMETIQUE")
        self.assertIs(self.app.modules["PARFUM"], module)
        self.app.deconnecter()                                                # à la déconnexion tout est libéré
        self.assertEqual(self.app.modules, {})
        self.assertIsNone(self.app.accueil)

    def test_rechargement_seulement_si_les_donnees_ont_change(self):
        self.premier_admin()
        self.app.ouvrir_module("COSMETIQUE")
        module = self.app.modules["COSMETIQUE"]
        stock = module.vue("Stock")
        appels = []
        original = stock.rafraichir
        stock.rafraichir = lambda: (appels.append(1), original())
        module.afficher("Stock")
        module.afficher("Caisse")
        module.afficher("Stock")
        module.afficher("Caisse")
        module.afficher("Stock")
        self.assertEqual(len(appels), 1)                                      # rien n'a changé : pas de rechargement
        from services import caisse_service as cs
        cs.creer_produit(self.conn, {"nom": "Nouveau", "prix_achat": "1", "prix_vente": "2"})
        module.afficher("Caisse")
        module.afficher("Stock")
        self.assertEqual(len(appels), 2)                                      # une donnée a changé : rechargé une fois
        module.afficher("Stock", forcer=True)
        self.assertEqual(len(appels), 3)

    def test_logo_charge_une_seule_fois(self):
        from utils import ressources
        self.assertIs(ressources.charger_logo(150), ressources.charger_logo(150))

    def test_stock_cosmetique_limite_les_lignes_affichees(self):
        from services import caisse_service as cs
        from views import stock_caisse_view
        self.premier_admin()
        with db.transaction(self.conn):
            for i in range(stock_caisse_view.LIMITE_AFFICHAGE + 50):
                self.conn.execute("INSERT INTO produits_caisse (code, nom, prix_vente) VALUES (?, ?, 100)",
                                  (f"P{i}", f"Produit {i}"))
        self.app.ouvrir_module("COSMETIQUE", "Stock")
        stock = self.app.modules["COSMETIQUE"].vue("Stock")
        self.assertEqual(len(stock.tableau.arbre.lignes), stock_caisse_view.LIMITE_AFFICHAGE)
        self.assertIn("affiner", stock.lbl_resume.cget("text"))
        saisir(stock.recherche, "Produit 3")                                   # une recherche retrouve tout produit
        stock.rafraichir()
        self.assertGreater(len(stock.tableau.arbre.lignes), 0)
        self.assertLess(len(stock.tableau.arbre.lignes), stock_caisse_view.LIMITE_AFFICHAGE)


class TestCosmetique(BaseGui):
    def creer_produits(self):
        self.app.ouvrir_module("COSMETIQUE")
        module = self.app.modules["COSMETIQUE"]
        stock = module.vue("Stock")
        for champs in ({"codes_barres": "6111", "nom": "Shampoing Nivea", "prix_achat": "300", "prix_vente": "500",
                        "quantite_stock": "20"},
                       {"code": "DOVE", "nom": "Gel douche Dove", "prix_achat": "100", "prix_vente": "250",
                        "quantite_stock": "10"}):
            d = DialogueProduitCaisse(self.app, self.app.ctx, None, stock.rafraichir)
            self.remplir(d.formulaire, champs)
            d._enregistrer()
        self.assertEqual(self.m.erreurs, [])
        return module

    def test_parcours_complet_de_la_caisse(self):
        self.premier_admin()
        module = self.creer_produits()
        stock = module.vue("Stock")
        self.app.ouvrir_module("COSMETIQUE", "Stock")
        self.assertEqual(len(stock.tableau.arbre.lignes), 2)
        saisir(stock.recherche, "dove")
        stock.rafraichir()
        self.assertEqual(len(stock.tableau.arbre.lignes), 1)
        saisir(stock.recherche, "")

        # --- sans session : on ne peut pas encaisser
        caisse = module.vue("Caisse")
        self.app.ouvrir_module("COSMETIQUE", "Caisse")
        saisir(caisse.saisie, "6111")
        caisse._sur_entree()                                        # un scan de code-barres
        self.assertEqual(caisse.panier[0]["quantite"], 1)
        caisse._encaisser()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)
        self.assertTrue(any("session" in x.lower() for x in self.m.infos))

        # --- ouverture de session puis ventes
        self.ouvrir_session("1000")
        saisir(caisse.saisie, "6111")
        caisse._sur_entree()                                        # même produit : la quantité augmente
        caisse._traiter_saisie("3*6111")                            # 3 articles d'un coup
        self.assertEqual((len(caisse.panier), caisse.panier[0]["quantite"]), (1, 5))
        caisse._fixer(0, "quantite", 2)
        caisse._traiter_saisie("dove")                              # par ID (sans code-barres)
        caisse._traiter_saisie("gel douche")                        # par nom
        self.assertEqual([l["quantite"] for l in caisse.panier], [2, 2])
        caisse.remise_type, caisse.remise_valeur = "POURCENT", 10   # remise de 10 % sur le ticket
        caisse._afficher_panier()
        self.assertEqual(caisse.calcul["total"], 1350)              # (2×500 + 2×250) = 1500 - 10 %
        saisir(caisse.entree_donne, "2000")
        caisse._maj_monnaie()
        self.assertIn("650", caisse.lbl_monnaie.cget("text"))
        caisse._encaisser()
        self.assertEqual(self.m.erreurs, [])
        self.assertEqual(self.conn.execute("SELECT total, monnaie_rendue FROM tickets").fetchone()[:], (1350, 650))
        self.assertEqual((self.stock("produits_caisse", "quantite_stock", 1), caisse.panier), (18, []))
        self.assertIn("Ticket n°1", caisse.lbl_dernier.cget("text"))

        # --- mise en attente puis reprise
        caisse._traiter_saisie("6111")
        caisse._mettre_en_attente()
        self.assertEqual(caisse.panier, [])
        attentes = DialogueAttentes(self.app, self.app.ctx, caisse._reprendre_panier)
        attentes.tableau.selectionner(next(iter(attentes.tableau.arbre.lignes)))
        attentes._reprendre()
        self.assertEqual(len(caisse.panier), 1)
        caisse._vider_panier()

        # --- retour d'un article du ticket n°1
        retours = module.vue("Retours")
        self.app.ouvrir_module("COSMETIQUE", "Retours")
        retours.tableau_tickets.selectionner("1")
        retours._voir_lignes()
        retours.tableau_lignes.selectionner(retours.tableau_lignes.arbre.get_children()[0])
        saisir(retours.entree_qte, "1")
        retours._ajouter_ligne_ticket()
        self.assertEqual(retours.ticket_id, 1)
        retours._valider()
        self.assertEqual(self.m.erreurs, [])
        self.assertEqual(self.conn.execute("SELECT total_rembourse FROM retours").fetchone()[0], 450)  # prix payé (remise comprise)
        self.assertEqual(self.stock("produits_caisse", "quantite_stock", 1), 19)

        # --- mouvement de caisse
        sessions = module.vue("Session")
        mouvement = DialogueMouvement(self.app, self.app.ctx, sessions.rafraichir)
        saisir(mouvement.montant, "300")
        saisir(mouvement.motif, "Retrait pour la banque")
        mouvement._valider()
        self.assertEqual(self.m.erreurs, [])

        # --- clôture : attendu = 1000 + 1350 - 450 - 300 = 1600 ; compté 1550 => manque 50
        self.app.ouvrir_module("COSMETIQUE", "Session")
        session_id = ss.session_active(self.conn)["id"]
        cloture = DialogueCloture(self.app, self.app.ctx, session_id, sessions.rafraichir)
        saisir(cloture.entree, "1550")
        cloture._cloturer()
        self.assertEqual(self.m.erreurs, [])
        s = ss.lire(self.conn, session_id)
        self.assertEqual((s["statut"], s["especes_attendues"], s["ecart"]), ("CLOTUREE", 1600, -50))
        sessions.rafraichir()
        self.assertEqual(len(sessions.tableau_historique.arbre.lignes), 1)
        self.assertIn("MANQUE", sessions.lbl_ecarts.cget("text"))

        # --- logs et statistiques
        logs = module.vue("Logs")
        self.app.ouvrir_module("COSMETIQUE", "Logs")
        self.assertGreaterEqual(len(logs.tableau.arbre.lignes), 5)
        self.assertIn("Dépense nette", logs.lbl_totaux.cget("text"))
        self.assertIn("Boss", " ".join(str(v) for v, _t in logs.tableau.arbre.lignes.values()))
        ligne_vente = next(i for i, (v, _t) in logs.tableau.arbre.lignes.items() if v[1] == "Vente")
        logs.tableau.selectionner(ligne_vente)
        logs._annuler_ticket()                                      # session clôturée : refusé
        self.assertTrue(any("clôturée" in e for e in self.m.erreurs))
        self.assertEqual(self.conn.execute("SELECT statut FROM tickets").fetchone()[0], "VALIDE")

    def test_retour_libre_avec_liste_de_suggestions(self):
        self.premier_admin()
        module = self.creer_produits()
        from services import caisse_service as cs
        cs.creer_produit(self.conn, {"nom": "Shampoing Dove", "prix_achat": "200", "prix_vente": "400",
                                     "quantite_stock": "5"})
        self.ouvrir_session("1000")
        retours = module.vue("Retours")
        self.app.ouvrir_module("COSMETIQUE", "Retours")
        retours._changer_mode("Retour libre (sans ticket)")
        saisir(retours.entree_libre, "sham")
        retours._maj_suggestions()                                  # la liste s'affiche pendant la frappe
        self.assertEqual(len(retours.suggestions.arbre.lignes), 2)
        saisir(retours.entree_libre, "nivea")
        retours._maj_suggestions()
        self.assertEqual(len(retours.suggestions.arbre.lignes), 1)
        retours.suggestions.selectionner(next(iter(retours.suggestions.arbre.lignes)))
        retours._ajouter_suggestion()                               # Entrée / double-clic sur la liste
        self.assertEqual([l["designation"] for l in retours.lignes_retour], ["Shampoing Nivea"])
        saisir(retours.entree_libre, "sham")                        # Entrée avec plusieurs résultats : la liste
        retours._sur_entree_libre()
        self.assertEqual(len(retours.lignes_retour), 1)
        self.assertEqual(len(retours.suggestions.arbre.lignes), 2)
        saisir(retours.entree_libre, "dove")                        # un seul résultat : ajout direct
        retours._sur_entree_libre()
        self.assertEqual(len(retours.lignes_retour), 2)
        retours._valider()
        self.assertEqual(self.m.erreurs, [])
        self.assertEqual(self.conn.execute("SELECT total_rembourse FROM retours").fetchone()[0], 500 + 250)

    def test_changement_d_employe_sans_cloturer(self):
        self.premier_admin()
        us.creer_utilisateur(self.conn, "Sara", "sara", "1234", "1234", "CAISSIER")
        module = self.creer_produits()
        self.ouvrir_session("1000")                                 # session de Boss
        admin_session = ss.session_active(self.conn)["id"]
        caisse = module.vue("Caisse")
        self.app.ouvrir_module("COSMETIQUE", "Caisse")
        caisse._traiter_saisie("6111")
        caisse._encaisser()
        self.app.deconnecter()                                      # Sara se connecte, sans que Boss ait clôturé
        login = self.app._vue
        saisir(login.identifiant, "sara")
        saisir(login.mot_de_passe, "1234")
        login._valider()
        self.ouvrir_session("200")
        self.assertEqual(ss.lire(self.conn, admin_session)["statut"], "EN_PAUSE")
        self.assertEqual(ss.session_active(self.conn)["utilisateur_nom"], "Sara")
        self.app.ouvrir_module("COSMETIQUE", "Caisse")
        caisse = self.app.modules["COSMETIQUE"].vue("Caisse")
        caisse._traiter_saisie("6111")
        saisir(caisse.entree_donne, "500")
        caisse._encaisser()                                         # va dans la session de Sara
        self.assertEqual(self.m.erreurs, [])
        sara = ss.session_active(self.conn)["id"]
        self.assertEqual(self.conn.execute("SELECT session_id FROM tickets ORDER BY id DESC").fetchone()[0], sara)
        self.assertEqual(ss.calculer(self.conn, sara)["attendues"], 700)
        self.assertEqual(ss.calculer(self.conn, admin_session)["attendues"], 1500)


class TestParfumEnSession(BaseGui):
    def test_vente_parfum_dans_la_session(self):
        self.premier_admin()
        self.app.ouvrir_module("PARFUM")
        module = self.app.modules["PARFUM"]
        creation = module.vue("Création")
        self.remplir(creation.formulaires["FLACON"], {"nom": "Carré 50ml", "capacite_ml": "50", "prix_achat": "100",
                                                      "quantite_stock": "10", "qnt_parfum_necessaire": "15"})
        creation._creer("FLACON")
        self.remplir(creation.formulaires["PARFUM"], {"nom": "Rose de Mai", "prix_achat_100ml": "1000",
                                                      "quantite_stock_ml": "500"})
        creation._creer("PARFUM")
        self.assertEqual(self.m.erreurs, [])

        vente = module.vue("Vente")
        self.app.ouvrir_module("PARFUM", "Vente")
        saisir(vente.entree_total, "700")
        vente._valider()                                            # pas de session : refusé + proposition d'ouvrir
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 0)
        self.ouvrir_session("1000")
        saisir(vente.entree_total, "700")
        vente._valider()
        self.assertEqual(self.m.erreurs, [])
        v = self.conn.execute("SELECT * FROM ventes").fetchone()
        self.assertEqual((v["total"], v["session_id"], v["utilisateur_id"]), (700, 1, 1))
        self.assertEqual(ss.calculer(self.conn, 1)["attendues"], 1700)

        # suppression de la vente par l'admin (session ouverte) : visible dans les logs avec le nom
        logs = module.vue("Logs")
        self.app.ouvrir_module("PARFUM", "Logs")
        self.assertIn("Boss", " ".join(str(vals) for vals, _t in logs.tableau.arbre.lignes.values()))
        logs.tableau.selectionner(next(i for i, (vals, _t) in logs.tableau.arbre.lignes.items() if vals[1] == "Vente"))
        logs._supprimer_vente()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 0)
        self.assertEqual(self.stock("flacons", "quantite_stock"), 10)

    def test_alcool_automatique_dans_le_formulaire(self):
        self.premier_admin()
        self.app.ouvrir_module("PARFUM")
        formulaire = self.app.modules["PARFUM"].vue("Création").formulaires["FLACON"]
        saisir(formulaire.entrees["capacite_ml"], "100")
        saisir(formulaire.entrees["qnt_parfum_necessaire"], "30")
        formulaire._maj_alcool()
        self.assertIn("70", formulaire.lbl_alcool.cget("text"))
        saisir(formulaire.entrees["qnt_parfum_necessaire"], "130")
        formulaire._maj_alcool()
        self.assertIn("dépasse", formulaire.lbl_alcool.cget("text"))

    def test_id_personnalise_dans_creation_et_stock(self):
        self.premier_admin()
        self.app.ouvrir_module("PARFUM")
        module = self.app.modules["PARFUM"]
        creation = module.vue("Création")
        form = creation.formulaires["PARFUM"]
        self.remplir(form, {"code": "ROSE1", "nom": "Rose", "prix_achat_100ml": "1000", "quantite_stock_ml": "500"})
        creation._creer("PARFUM")
        self.assertEqual(self.m.erreurs, [])
        self.remplir(form, {"code": "rose1", "nom": "Autre", "prix_achat_100ml": "1"})      # ID déjà pris
        creation._creer("PARFUM")
        self.assertEqual(len(self.m.erreurs), 1)
        self.assertIn("déjà utilisé", self.m.erreurs[0])
        self.m.erreurs.clear()
        stock = module.vue("Stock")
        self.app.ouvrir_module("PARFUM", "Stock")
        self.assertEqual(stock.tableau.arbre.lignes["PARFUM:1"][0][0], "ROSE1")
        modif = DialogueModifier(self.app, self.conn, "PARFUM", 1, stock.rafraichir)
        saisir(modif.formulaire.entrees["code"], "ROSE2")
        modif._enregistrer()
        self.assertEqual(self.m.erreurs, [])
        self.assertEqual(self.conn.execute("SELECT code FROM parfums").fetchone()[0], "ROSE2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
