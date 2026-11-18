"""Utilisateurs, droits, sessions de caisse, clôtures et écarts."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import connection as db  # noqa: E402
from services import session_service as ss, utilisateurs_service as us  # noqa: E402
from utils.erreurs import ErreurMetier  # noqa: E402


class BaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name
        self.conn = db.ouvrir_base().connexion
        self.admin = self.utilisateur("Admin", "admin", "ADMIN")
        self.karim = self.utilisateur("Karim", "karim", "CAISSIER")     # employé du jour
        self.sara = self.utilisateur("Sara", "sara", "CAISSIER")        # employée du soir

    def tearDown(self):
        self.conn.close()
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()

    def utilisateur(self, nom, identifiant, role):
        return us.obtenir(self.conn, us.creer_utilisateur(self.conn, nom, identifiant, "1234", "1234", role))

    def encaisser(self, session_id, montant, utilisateur):
        """Simule des ventes parfum de ce montant dans une session (sans passer par les produits)."""
        self.conn.execute("INSERT INTO ventes (total, session_id, utilisateur_id) VALUES (?, ?, ?)",
                          (montant, session_id, utilisateur["id"]))


class TestUtilisateurs(BaseTest):
    def test_connexion(self):
        self.assertEqual(us.authentifier(self.conn, "KARIM", "1234")["nom"], "Karim")      # casse ignorée
        self.assertIsNone(us.authentifier(self.conn, "karim", "faux"))
        self.assertIsNone(us.authentifier(self.conn, "inconnu", "1234"))

    def test_validations(self):
        for args in (("", "x1", "1234", "1234"), ("Nom", "a b", "1234", "1234"),
                     ("Nom", "ok", "123", "123"), ("Nom", "ok", "1234", "4321"),
                     ("Nom", "KARIM", "1234", "1234")):                                   # identifiant déjà pris
            with self.assertRaises(ErreurMetier):
                us.creer_utilisateur(self.conn, *args)

    def test_mot_de_passe_hache_et_modifiable(self):
        self.assertNotIn("1234", self.karim["mot_de_passe_hash"])
        us.changer_mot_de_passe(self.conn, self.karim["id"], "nouveau", "nouveau")
        self.assertIsNone(us.authentifier(self.conn, "karim", "1234"))
        self.assertIsNotNone(us.authentifier(self.conn, "karim", "nouveau"))

    def test_desactiver_empeche_la_connexion(self):
        us.modifier_utilisateur(self.conn, self.karim["id"], "Karim", "CAISSIER", actif=False)
        self.assertIsNone(us.authentifier(self.conn, "karim", "1234"))

    def test_dernier_admin_protege(self):
        with self.assertRaises(ErreurMetier):
            us.modifier_utilisateur(self.conn, self.admin["id"], "Admin", "CAISSIER")
        with self.assertRaises(ErreurMetier):
            us.modifier_utilisateur(self.conn, self.admin["id"], "Admin", "ADMIN", actif=False)
        autre = self.utilisateur("Admin2", "admin2", "ADMIN")
        us.modifier_utilisateur(self.conn, autre["id"], "Admin2", "CAISSIER")             # il reste « admin »

    def test_pas_de_desactivation_avec_session_en_cours(self):
        ss.ouvrir_session(self.conn, self.karim, "1000")
        with self.assertRaises(ErreurMetier):
            us.modifier_utilisateur(self.conn, self.karim["id"], "Karim", "CAISSIER", actif=False)

    def test_permissions(self):
        for action in ("caisse_vente", "parfum_vente", "caisse_retour", "session", "caisse_stock_lecture"):
            self.assertTrue(us.autorise("CAISSIER", action))
        for action in ("parfum_creation", "parfum_stock", "parfum_logs", "parfum_parametres",
                       "caisse_logs_stats", "caisse_stock_modifier", "utilisateurs", "voir_prix_achat"):
            self.assertFalse(us.autorise("CAISSIER", action), action)
            self.assertTrue(us.autorise("ADMIN", action), action)


class TestSessions(BaseTest):
    def test_ouverture_et_une_seule_active(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        self.assertEqual(ss.session_active(self.conn)["id"], a)
        with self.assertRaises(ErreurMetier):                       # déjà une session non clôturée
            ss.ouvrir_session(self.conn, self.karim, "0")
        with self.assertRaises(ErreurMetier):
            ss.ouvrir_session(self.conn, self.sara, "-5")
        with self.assertRaises(ErreurMetier):
            ss.mettre_en_pause(self.conn, 999, self.karim)

    def test_changement_d_employe_sans_cloturer(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        b = ss.ouvrir_session(self.conn, self.sara, "0")            # Sara prend la caisse
        self.assertEqual(ss.lire(self.conn, a)["statut"], "EN_PAUSE")
        self.assertEqual(ss.lire(self.conn, b)["statut"], "OUVERTE")
        self.assertEqual(ss.session_active(self.conn)["utilisateur_nom"], "Sara")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM sessions_caisse WHERE statut = 'OUVERTE'").fetchone()[0], 1)
        ss.reprendre_session(self.conn, a, self.karim)              # Karim reprend ; Sara passe en pause
        self.assertEqual(ss.lire(self.conn, a)["statut"], "OUVERTE")
        self.assertEqual(ss.lire(self.conn, b)["statut"], "EN_PAUSE")
        with self.assertRaises(ErreurMetier):                       # un caissier ne reprend pas la session d'un autre
            ss.reprendre_session(self.conn, b, self.karim)
        ss.reprendre_session(self.conn, b, self.admin)              # l'admin le peut

    def test_les_ventes_vont_dans_la_session_ouverte(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        self.encaisser(a, 1000, self.karim)
        b = ss.ouvrir_session(self.conn, self.sara, "0")
        self.encaisser(b, 400, self.sara)
        self.assertEqual(ss.calculer(self.conn, a)["attendues"], 6000)
        self.assertEqual(ss.calculer(self.conn, b)["attendues"], 400)

    def test_cloture_ecart_manque_par_session(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        self.encaisser(a, 3000, self.karim)
        res = ss.cloturer_session(self.conn, a, "7800", self.karim)       # attendu 8000 : manque 200
        self.assertEqual((res["attendues"], res["ecart"]), (8000, -200))
        s = ss.lire(self.conn, a)
        self.assertEqual((s["statut"], s["ecart"], s["especes_comptees"]), ("CLOTUREE", -200, 7800))
        b = ss.ouvrir_session(self.conn, self.sara, "7800")               # passation exacte
        self.assertEqual(ss.lire(self.conn, b)["ecart_passation"], 0)
        self.encaisser(b, 1000, self.sara)
        res = ss.cloturer_session(self.conn, b, "8900", self.sara)        # attendu 8800 : excédent 100
        self.assertEqual(res["ecart"], 100)
        par_user = {r["nom"]: r["ecart_total"] for r in ss.ecarts_par_utilisateur(self.conn)}
        self.assertEqual(par_user, {"Karim": -200, "Sara": 100})

    def test_ecart_de_passation(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        ss.cloturer_session(self.conn, a, "5000", self.karim)
        self.assertEqual(ss.fond_suggere(self.conn), 5000)
        b = ss.ouvrir_session(self.conn, self.sara, "4700")              # 300 de moins qu'à la clôture
        self.assertEqual(ss.lire(self.conn, b)["ecart_passation"], -300)
        self.assertIn("passation", ss.rapport_session(self.conn, b).lower())

    def test_pas_d_ecart_de_passation_si_une_session_reste_en_pause(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        b = ss.ouvrir_session(self.conn, self.sara, "0")                 # Karim reste en pause
        self.assertEqual(ss.lire(self.conn, b)["ecart_passation"], 0)
        self.assertEqual(ss.fond_suggere(self.conn), 0)

    def test_cloturer_une_session_en_pause(self):
        a = ss.ouvrir_session(self.conn, self.karim, "1000")
        ss.ouvrir_session(self.conn, self.sara, "0")
        res = ss.cloturer_session(self.conn, a, "1000", self.karim)       # Karim clôture sa session en pause
        self.assertEqual(res["ecart"], 0)
        self.assertEqual(ss.session_active(self.conn)["utilisateur_nom"], "Sara")   # Sara reste active

    def test_droits_de_cloture(self):
        a = ss.ouvrir_session(self.conn, self.karim, "1000")
        with self.assertRaises(ErreurMetier):
            ss.cloturer_session(self.conn, a, "1000", self.sara)          # pas sa session
        ss.cloturer_session(self.conn, a, "1000", self.admin)             # l'admin peut
        with self.assertRaises(ErreurMetier):
            ss.cloturer_session(self.conn, a, "1000", self.admin)         # déjà clôturée
        with self.assertRaises(ErreurMetier):
            ss.cloturer_session(self.conn, ss.ouvrir_session(self.conn, self.sara, "0"), "abc", self.sara)

    def test_mouvements_de_caisse(self):
        with self.assertRaises(ErreurMetier):                              # aucune session
            ss.ajouter_mouvement(self.conn, self.karim, "SORTIE", "100", "essence")
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        ss.ajouter_mouvement(self.conn, self.karim, "SORTIE", "1500", "Retrait pour la banque")
        ss.ajouter_mouvement(self.conn, self.karim, "ENTREE", "200", "Monnaie apportée")
        self.assertEqual(ss.calculer(self.conn, a)["attendues"], 5000 - 1500 + 200)
        for args in (("SORTIE", "0", "x"), ("SORTIE", "50", " "), ("AUTRE", "50", "x")):
            with self.assertRaises(ErreurMetier):
                ss.ajouter_mouvement(self.conn, self.karim, *args)
        ss.cloturer_session(self.conn, a, "3700", self.karim)
        with self.assertRaises(ErreurMetier):                              # plus de session active
            ss.ajouter_mouvement(self.conn, self.karim, "SORTIE", "10", "trop tard")

    def test_session_cloturee_est_figee(self):
        a = ss.ouvrir_session(self.conn, self.karim, "1000")
        self.encaisser(a, 500, self.karim)
        ss.cloturer_session(self.conn, a, "1500", self.karim)
        self.encaisser(a, 999, self.karim)                                 # donnée modifiée après coup
        self.assertEqual(ss.calculer(self.conn, a)["attendues"], 1500)     # le chiffre figé ne bouge pas

    def test_un_seul_tiroir_garanti_par_la_base(self):
        ss.ouvrir_session(self.conn, self.karim, "0")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO sessions_caisse (utilisateur_id, statut) VALUES (?, 'OUVERTE')",
                              (self.sara["id"],))

    def test_rapports(self):
        a = ss.ouvrir_session(self.conn, self.karim, "5000")
        self.encaisser(a, 3000, self.karim)
        ss.cloturer_session(self.conn, a, "7800", self.karim)
        b = ss.ouvrir_session(self.conn, self.sara, "7800")
        rapport = ss.rapport_session(self.conn, a)
        self.assertIn("MANQUE", rapport)
        self.assertIn("Karim", rapport)
        jour = ss.rapport_journee(self.conn)
        self.assertIn("Karim", jour)
        self.assertIn("Sara", jour)
        self.assertIn("non clôturée", jour)
        self.assertIn("Aucune session", ss.rapport_journee(self.conn, "01/01/2000"))



class TestParfumEtSessions(BaseTest):
    """Les ventes de parfum passent dans la session de caisse ouverte."""

    def jeu(self):
        from services import produits_service as ps
        f = ps.creer_produit(self.conn, "FLACON", {"nom": "Carré", "capacite_ml": "50", "prix_achat": "100",
                                                   "quantite_stock": "10", "qnt_parfum_necessaire": "15"})["id"]
        p = ps.creer_produit(self.conn, "PARFUM", {"nom": "Rose", "prix_achat_100ml": "1000",
                                                   "quantite_stock_ml": "500"})["id"]
        return {"flacon_id": f, "parfum_id": p, "alcool_id": None, "prix_final": 600}

    def test_vente_parfum_exige_une_session_et_va_dedans(self):
        from services import vente_service as vs
        ligne = self.jeu()
        with self.assertRaises(ErreurMetier):
            vs.valider_vente(self.conn, [ligne], utilisateur=self.karim)          # pas de session ouverte
        a = ss.ouvrir_session(self.conn, self.karim, "1000")
        vs.valider_vente(self.conn, [ligne], utilisateur=self.karim)
        vente = self.conn.execute("SELECT * FROM ventes").fetchone()
        self.assertEqual((vente["session_id"], vente["utilisateur_id"]), (a, self.karim["id"]))
        log = self.conn.execute("SELECT * FROM logs WHERE type = 'VENTE'").fetchone()
        self.assertEqual((log["session_id"], log["utilisateur_id"]), (a, self.karim["id"]))
        self.assertEqual(ss.calculer(self.conn, a)["attendues"], 1600)
        self.assertEqual(ss.calculer(self.conn, a)["ventes_parfum"], 600)
        # changement d'employé : la vente suivante va dans la session de Sara
        b = ss.ouvrir_session(self.conn, self.sara, "0")
        vs.valider_vente(self.conn, [ligne], utilisateur=self.sara)
        self.assertEqual(ss.calculer(self.conn, b)["ventes_parfum"], 600)
        self.assertEqual(ss.calculer(self.conn, a)["ventes_parfum"], 600)

    def test_suppression_vente_parfum_regles(self):
        from services import vente_service as vs
        ligne = self.jeu()
        a = ss.ouvrir_session(self.conn, self.karim, "1000")
        vid = vs.valider_vente(self.conn, [ligne], utilisateur=self.karim)["vente_id"]
        with self.assertRaises(ErreurMetier):
            vs.supprimer_vente(self.conn, vid, self.karim)                        # réservé à l'admin
        vid2 = vs.valider_vente(self.conn, [ligne], utilisateur=self.karim)["vente_id"]
        ss.cloturer_session(self.conn, a, "2200", self.karim)
        with self.assertRaises(ErreurMetier) as ctx:                              # session clôturée : refusé
            vs.supprimer_vente(self.conn, vid2, self.admin)
        self.assertIn("clôturée", str(ctx.exception))
        ss.ouvrir_session(self.conn, self.sara, "2200")
        vid3 = vs.valider_vente(self.conn, [ligne], utilisateur=self.sara)["vente_id"]
        vs.supprimer_vente(self.conn, vid3, self.admin)                           # session ouverte : OK
        log = self.conn.execute("SELECT * FROM logs WHERE type = 'ANNULATION'").fetchone()
        self.assertEqual(log["utilisateur_id"], self.admin["id"])

    def test_logs_parfum_avec_nom_utilisateur(self):
        from services import stats_service as st, vente_service as vs
        ligne = self.jeu()
        ss.ouvrir_session(self.conn, self.karim, "0")
        vs.valider_vente(self.conn, [ligne], utilisateur=self.karim)
        logs = st.lister_logs(self.conn, None, None, "Ventes")
        self.assertEqual(logs[0]["utilisateur_nom"], "Karim")


if __name__ == "__main__":
    unittest.main()
