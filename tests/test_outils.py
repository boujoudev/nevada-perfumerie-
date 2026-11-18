"""Outil de réinitialisation de mot de passe."""

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from database import connection as db  # noqa: E402
from services import utilisateurs_service as us  # noqa: E402
from utils.erreurs import ErreurMetier  # noqa: E402

spec = importlib.util.spec_from_file_location("reinit", RACINE / "outils" / "reinitialiser_mot_de_passe.py")
reinit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reinit)


class TestReinitialisation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name
        conn = db.ouvrir_base().connexion
        us.creer_utilisateur(conn, "Boss", "admin", "oublie", "oublie", "ADMIN")
        us.creer_utilisateur(conn, "Karim", "karim", "1234", "1234", "CAISSIER")
        conn.close()
        self.chemin = db.chemin_base()

    def tearDown(self):
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()

    def test_nouveau_mot_de_passe_et_copie_de_securite(self):
        copie = reinit.reinitialiser(self.chemin, "ADMIN", "nouveau1")             # casse ignorée
        self.assertTrue(copie.is_file())
        conn = db.creer_connexion(self.chemin)
        self.assertIsNone(us.authentifier(conn, "admin", "oublie"))
        self.assertEqual(us.authentifier(conn, "admin", "nouveau1")["nom"], "Boss")
        self.assertIsNotNone(us.authentifier(conn, "karim", "1234"))                # les autres ne changent pas
        conn.close()
        ancienne = sqlite3.connect(str(copie))                                       # la copie a l'ancien mot de passe
        self.assertEqual(ancienne.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0], 2)
        ancienne.close()

    def test_erreurs(self):
        with self.assertRaises(ErreurMetier) as ctx:
            reinit.reinitialiser(self.chemin, "inconnu", "nouveau1")
        self.assertIn("admin", str(ctx.exception))                                   # liste les identifiants existants
        with self.assertRaises(ErreurMetier):
            reinit.reinitialiser(self.chemin, "admin", "123")                        # trop court
        with self.assertRaises(ErreurMetier):
            reinit.reinitialiser(Path(self._tmp.name) / "absent.db", "admin", "nouveau1")
        self.assertEqual(len(list(Path(self._tmp.name).glob("*_avant_reinit_*"))), 0)   # rien créé en cas d'erreur


if __name__ == "__main__":
    unittest.main()
