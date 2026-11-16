"""Test de fumée des écrans (avec faux widgets) : scénario complet de bout en bout."""

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
from views.dialogues import (DialogueClient, DialogueConnexion, DialogueDetails,  # noqa: E402
                             DialogueModifier, DialogueReappro)
from views.main_window import FenetrePrincipale  # noqa: E402


def saisir(entree, texte):
    entree.delete(0, "end")
    entree.insert(0, texte)


class TestEcrans(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name
        gui_stubs.messages.reinitialiser()
        self.conn = db.ouvrir_base().connexion
        self.app = FenetrePrincipale(self.conn)
        self.app._demarrer()

    def tearDown(self):
        self.conn.close()
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()

    def remplir(self, formulaire, valeurs):
        for cle, texte in valeurs.items():
            saisir(formulaire.entrees[cle], texte)

    def creer_catalogue(self):
        creation = self.app.vues["Création"]
        self.remplir(creation.formulaires["FLACON"], {
            "nom": "Carré 50ml", "capacite_ml": "50", "prix_achat": "100",
            "quantite_stock": "10", "qnt_parfum_necessaire": "15"})
        creation._creer("FLACON")
        self.remplir(creation.formulaires["PARFUM"], {
            "nom": "Rose de Mai", "prix_achat_100ml": "1000",
            "quantite_stock_ml": "500"})
        creation._creer("PARFUM")
        self.remplir(creation.formulaires["ALCOOL"], {
            "nom": "Alcool 96°", "prix_achat_litre": "500",
            "quantite_stock_ml": "5000"})
        creation._creer("ALCOOL")

    def test_scenario_complet(self):
        m = gui_stubs.messages
        # 1. Création des 3 produits
        self.creer_catalogue()
        self.assertEqual(m.erreurs, [])
        self.assertEqual(len(m.infos), 3)

        # 2. Stock
        stock = self.app.vues["Stock"]
        self.app.afficher("Stock")
        self.assertEqual(len(stock.tableau.arbre.lignes), 3)
        saisir(stock.recherche, "rose")
        stock.rafraichir()
        self.assertEqual(list(stock.tableau.arbre.lignes), ["PARFUM:1"])
        saisir(stock.recherche, "")

        # 3. Dialogues du stock
        stock.tableau.arbre.selection_set("PARFUM:1")
        DialogueDetails(self.app, self.conn, "PARFUM", 1)
        modif = DialogueModifier(self.app, self.conn, "PARFUM", 1, stock.rafraichir)
        saisir(modif.formulaire.entrees["nom"], "Rose Noire")
        modif._enregistrer()
        reappro = DialogueReappro(self.app, self.conn, "PARFUM", 1, stock.rafraichir)
        saisir(reappro.entree, "100")
        reappro._valider()
        self.assertEqual(self.conn.execute(
            "SELECT quantite_stock_ml FROM parfums WHERE id=1").fetchone()[0], 600)
        stock.tableau.arbre.selection_set("ALCOOL:1")          # suppression d'un produit
        stock._supprimer()
        self.assertEqual(self.conn.execute("SELECT actif FROM alcools WHERE id=1").fetchone()[0], 0)
        self.assertEqual(m.erreurs, [])

        # 4. Vente (flacon + parfum + alcool par défaut)
        vente = self.app.vues["Vente"]
        self.app.afficher("Vente")
        self.assertIsNotNone(vente.ligne)
        self.assertEqual(vente.ligne["cout_total"], 250)         # alcool supprimé : flacon 100 + parfum 150
        self.assertIsNone(vente.ligne["alcool_id"])
        saisir(vente.entree_total, "700")                        # prix modifié à la main
        vente._maj_benefice()
        vente._valider()                                         # ajoute au panier puis valide
        self.assertEqual(m.erreurs, [])
        self.assertEqual(self.conn.execute("SELECT total FROM ventes").fetchone()[0], 700)
        self.assertEqual(self.conn.execute(
            "SELECT quantite_stock FROM flacons").fetchone()[0], 9)

        # 5. Flacon du client puis « tout effacer »
        vente.var_flacon_client.set(True)
        vente._recalculer()
        self.assertEqual(vente.ligne["cout_flacon"], 0)
        vente._ajouter_au_panier()                               # sans prix saisi : refusé
        self.assertEqual(vente.panier, [])
        m.erreurs.clear()
        saisir(vente.entree_total, "500")
        vente._ajouter_au_panier()
        self.assertEqual(len(vente.panier), 1)
        self.assertIn("BÉNÉFICE DU PANIER", vente.lbl_benefice_panier.cget("text"))
        self.assertNotIn("—", vente.lbl_benefice_panier.cget("text"))
        vente._tout_effacer()
        self.assertEqual(vente.panier, [])

        # 6. Client
        DialogueClient(self.app, self.conn, lambda _i: None)._creer()   # nom vide -> erreur affichée
        self.assertEqual(len(m.erreurs), 1)
        m.erreurs.clear()

        # 7. Logs, stats et suppression de la vente
        logs = self.app.vues["Logs"]
        self.app.afficher("Logs")
        self.assertGreaterEqual(len(logs.tableau.arbre.lignes), 5)
        iid_vente = next(i for i, (v, _t) in logs.tableau.arbre.lignes.items() if v[1] == "Vente")
        logs.tableau.arbre.selection_set(iid_vente)
        logs._supprimer_vente()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT quantite_stock FROM flacons").fetchone()[0], 10)
        self.assertEqual(m.erreurs, [])

        # 8. Paramètres + connexion par mot de passe
        params = self.app.vues["Paramètres"]
        saisir(params.nouveau, "secret1")
        saisir(params.confirmation, "secret1")
        params._definir()
        params._sauvegarder()
        self.assertEqual(m.erreurs, [])
        connexion = DialogueConnexion(self.app, self.conn)
        saisir(connexion.entree, "mauvais")
        connexion._valider()
        self.assertFalse(connexion.ok)
        saisir(connexion.entree, "secret1")
        connexion._valider()
        self.assertTrue(connexion.ok)

    def test_alcool_automatique_dans_le_formulaire(self):
        creation = self.app.vues["Création"]
        formulaire = creation.formulaires["FLACON"]
        saisir(formulaire.entrees["capacite_ml"], "100")
        saisir(formulaire.entrees["qnt_parfum_necessaire"], "30")
        formulaire._maj_alcool()
        self.assertIn("70", formulaire.lbl_alcool.cget("text"))
        saisir(formulaire.entrees["qnt_parfum_necessaire"], "130")
        formulaire._maj_alcool()
        self.assertIn("dépasse", formulaire.lbl_alcool.cget("text"))

    def test_stock_negatif_affiche_alerte(self):
        self.creer_catalogue()
        self.conn.execute("UPDATE flacons SET quantite_stock = 0")
        vente = self.app.vues["Vente"]
        self.app.afficher("Vente")
        self.assertIn("Flacon en rupture", vente.lbl_alertes.cget("text"))
        saisir(vente.entree_total, "500")
        vente._valider()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT quantite_stock FROM flacons").fetchone()[0], -1)
        self.assertEqual(len(gui_stubs.messages.avertissements), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
