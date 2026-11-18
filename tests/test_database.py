"""Tests de l'étape 1 : schéma, contraintes, sauvegardes, corruption.

Lancer :  python -m unittest discover -s tests -v   (ou : pytest)
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import connection as db  # noqa: E402


class BaseTestCase(unittest.TestCase):
    """Chaque test travaille dans un dossier temporaire isolé."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name

    def tearDown(self):
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()


class TestSchema(BaseTestCase):
    def test_creation_base_neuve(self):
        res = db.ouvrir_base()
        self.assertIsNone(res.message)
        tables = {r[0] for r in res.connexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for attendu in ("flacons", "parfums", "alcools", "clients", "ventes",
                        "lignes_vente", "logs", "parametres"):
            self.assertIn(attendu, tables)
        res.connexion.close()

    def test_parametres_par_defaut(self):
        conn = db.ouvrir_base().connexion
        devise = conn.execute(
            "SELECT valeur FROM parametres WHERE cle='devise'").fetchone()[0]
        self.assertEqual(devise, "DA")
        conn.close()

    def test_schema_idempotent(self):
        conn = db.ouvrir_base().connexion
        db.creer_schema(conn)  # ne doit pas planter une 2e fois
        conn.close()

    def test_stock_negatif_autorise(self):
        conn = db.ouvrir_base().connexion
        conn.execute("INSERT INTO flacons (nom, capacite_ml, quantite_stock) "
                     "VALUES ('Carré 50ml', 50, -3)")
        self.assertEqual(
            conn.execute("SELECT quantite_stock FROM flacons").fetchone()[0], -3)
        conn.close()

    def test_contraintes_refusent_valeurs_invalides(self):
        conn = db.ouvrir_base().connexion
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO flacons (nom, capacite_ml) VALUES ('X', 0)")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO parfums (nom, prix_vente_100ml) VALUES ('Rose', -1)")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO alcools (nom) VALUES ('   ')")
        conn.close()

    def test_ligne_vente_flacon_client(self):
        """Un client qui apporte son flacon : prix et coût du flacon à 0."""
        conn = db.ouvrir_base().connexion
        conn.execute("INSERT INTO flacons (nom, capacite_ml, quantite_stock, "
                     "prix_achat, prix_vente) VALUES ('Carré 50ml', 50, 10, 100, 300)")
        conn.execute("INSERT INTO parfums (nom) VALUES ('Rose de Mai')")
        conn.execute("INSERT INTO ventes (total) VALUES (500)")
        conn.execute(
            """INSERT INTO lignes_vente
               (vente_id, flacon_id, parfum_id, flacon_client, flacon_nom,
                parfum_nom, qnt_parfum_ml, prix_flacon, cout_flacon,
                prix_calcule, prix_final, benefice)
               VALUES (1, 1, 1, 1, 'Carré 50ml', 'Rose de Mai', 15, 0, 0, 500, 500, 350)""")
        ligne = conn.execute("SELECT flacon_client, prix_flacon FROM lignes_vente").fetchone()
        self.assertEqual((ligne[0], ligne[1]), (1, 0))
        conn.close()

    def test_suppression_vente_efface_lignes_mais_garde_logs(self):
        conn = db.ouvrir_base().connexion
        conn.execute("INSERT INTO flacons (nom, capacite_ml) VALUES ('F', 50)")
        conn.execute("INSERT INTO parfums (nom) VALUES ('P')")
        conn.execute("INSERT INTO ventes (total) VALUES (100)")
        conn.execute(
            """INSERT INTO lignes_vente (vente_id, flacon_id, parfum_id, flacon_nom,
               parfum_nom, qnt_parfum_ml, prix_calcule, prix_final, benefice)
               VALUES (1, 1, 1, 'F', 'P', 10, 100, 100, 50)""")
        conn.execute("INSERT INTO logs (type, vente_id, details) "
                     "VALUES ('ANNULATION', 1, 'vente supprimée')")
        conn.execute("DELETE FROM ventes WHERE id = 1")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM lignes_vente").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0], 1)
        conn.close()

    def test_type_log_invalide_refuse(self):
        conn = db.ouvrir_base().connexion
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO logs (type) VALUES ('N_IMPORTE_QUOI')")
        conn.close()


class TestTransaction(BaseTestCase):
    def test_rollback_en_cas_d_erreur(self):
        conn = db.ouvrir_base().connexion
        conn.isolation_level = None  # gestion manuelle de BEGIN/COMMIT
        with self.assertRaises(sqlite3.IntegrityError):
            with db.transaction(conn):
                conn.execute("INSERT INTO parfums (nom) VALUES ('OK')")
                conn.execute("INSERT INTO parfums (nom) VALUES ('')")  # invalide
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM parfums").fetchone()[0], 0)
        conn.close()

    def test_commit_si_tout_va_bien(self):
        conn = db.ouvrir_base().connexion
        conn.isolation_level = None
        with db.transaction(conn):
            conn.execute("INSERT INTO parfums (nom) VALUES ('Rose')")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM parfums").fetchone()[0], 1)
        conn.close()


class TestSauvegardeEtCorruption(BaseTestCase):
    def test_sauvegarde_creee_au_redemarrage(self):
        db.ouvrir_base().connexion.close()          # 1er lancement
        db.ouvrir_base().connexion.close()          # 2e lancement -> sauvegarde
        self.assertGreaterEqual(len(list(db.dossier_sauvegardes().glob("*.db"))), 1)

    def test_purge_garde_au_plus_10_sauvegardes(self):
        conn = db.ouvrir_base().connexion
        for _ in range(db.NB_SAUVEGARDES_MAX + 4):
            db.sauvegarder(conn)
        self.assertLessEqual(len(list(db.dossier_sauvegardes().glob("*.db"))),
                             db.NB_SAUVEGARDES_MAX)
        conn.close()

    def test_corruption_restauree_depuis_sauvegarde(self):
        conn = db.ouvrir_base().connexion
        conn.execute("INSERT INTO parfums (nom) VALUES ('Rose de Mai')")
        conn.commit()
        db.sauvegarder(conn)
        conn.close()
        # On corrompt le fichier principal
        chemin = db.chemin_base()
        for suffixe in ("-wal", "-shm"):
            Path(str(chemin) + suffixe).unlink(missing_ok=True)
        chemin.write_bytes(b"ceci n'est pas une base sqlite" * 100)

        res = db.ouvrir_base()
        self.assertTrue(res.restauree)
        self.assertIsNotNone(res.message)
        noms = [r[0] for r in res.connexion.execute("SELECT nom FROM parfums")]
        self.assertEqual(noms, ["Rose de Mai"])
        # Le fichier corrompu est conservé, pas supprimé
        self.assertTrue(list(db.dossier_donnees().glob("parfumerie_corrompue_*.db")))
        res.connexion.close()

    def test_corruption_sans_sauvegarde_cree_base_neuve(self):
        chemin = db.chemin_base()
        chemin.write_bytes(b"garbage" * 500)
        res = db.ouvrir_base()
        self.assertTrue(res.reinitialisee)
        self.assertEqual(res.connexion.execute("SELECT COUNT(*) FROM parfums").fetchone()[0], 0)
        res.connexion.close()

    def test_verifier_integrite(self):
        db.ouvrir_base().connexion.close()
        self.assertTrue(db.verifier_integrite(db.chemin_base()))
        faux = Path(self._tmp.name) / "faux.db"
        faux.write_bytes(b"xxxx" * 1000)
        self.assertFalse(db.verifier_integrite(faux))


class TestMigration(BaseTestCase):
    def test_migration_v1_alcool_ml_vers_litre(self):
        """Une base v1 (prix de l'alcool au ml) est convertie au litre sans perte."""
        conn = db.ouvrir_base().connexion
        conn.execute("INSERT INTO alcools (nom, prix_achat_litre, prix_vente_litre) VALUES ('A', 0.5, 1)")
        # on simule l'ancienne structure v1
        conn.execute("ALTER TABLE alcools RENAME COLUMN prix_achat_litre TO prix_achat_ml")
        conn.execute("ALTER TABLE alcools RENAME COLUMN prix_vente_litre TO prix_vente_ml")
        conn.execute("UPDATE parametres SET valeur = '1' WHERE cle = 'schema_version'")
        conn.close()
        conn = db.ouvrir_base().connexion        # réouverture -> migration
        ligne = conn.execute("SELECT prix_achat_litre, prix_vente_litre FROM alcools").fetchone()
        self.assertEqual((ligne[0], ligne[1]), (500, 1000))
        version = conn.execute("SELECT valeur FROM parametres WHERE cle='schema_version'").fetchone()[0]
        self.assertEqual(version, "5")
        conn.close()
        db.ouvrir_base().connexion.close()       # idempotent : pas de 2e conversion
        conn = db.creer_connexion()
        self.assertEqual(conn.execute("SELECT prix_achat_litre FROM alcools").fetchone()[0], 500)
        conn.close()


    def test_migration_v2_parfum_vers_100ml(self):
        """Les prix du parfum déjà saisis sont conservés et lus comme des prix pour 100 ml."""
        conn = db.ouvrir_base().connexion
        conn.execute("INSERT INTO parfums (nom, prix_achat_100ml, prix_vente_100ml) VALUES ('P', 100, 200)")
        conn.execute("ALTER TABLE parfums RENAME COLUMN prix_achat_100ml TO prix_achat_ml")
        conn.execute("ALTER TABLE parfums RENAME COLUMN prix_vente_100ml TO prix_vente_10ml")
        conn.execute("UPDATE parametres SET valeur = '2' WHERE cle = 'schema_version'")
        conn.close()
        conn = db.ouvrir_base().connexion
        ligne = conn.execute("SELECT prix_achat_100ml, prix_vente_100ml FROM parfums").fetchone()
        self.assertEqual((ligne[0], ligne[1]), (100, 200))
        conn.close()


    def test_migration_v3_ajoute_les_id_personnalisables(self):
        """Une base v3 (sans colonne code) reçoit les ID F-1/P-1/A-1 ; un ID ne peut plus être dupliqué."""
        conn = db.ouvrir_base().connexion
        try:
            for table in ("flacons", "parfums", "alcools"):
                conn.execute(f"DROP INDEX IF EXISTS idx_{table}_code")
                conn.execute(f"ALTER TABLE {table} DROP COLUMN code")
        except sqlite3.OperationalError:
            conn.close()
            self.skipTest("SQLite trop ancien pour simuler l'ancienne structure")
        conn.execute("INSERT INTO flacons (nom, capacite_ml) VALUES ('Carré', 50)")
        conn.execute("INSERT INTO parfums (nom) VALUES ('Rose')")
        conn.execute("INSERT INTO alcools (nom) VALUES ('Alcool')")
        conn.execute("INSERT INTO parfums (nom, actif) VALUES ('Ancien supprimé', 0)")
        conn.execute("UPDATE parametres SET valeur = '3' WHERE cle = 'schema_version'")
        conn.close()
        conn = db.ouvrir_base().connexion
        codes = [conn.execute(f"SELECT code FROM {t} WHERE actif = 1").fetchone()[0]
                 for t in ("flacons", "parfums", "alcools")]
        self.assertEqual(codes, ["F-1", "P-1", "A-1"])
        self.assertIsNone(conn.execute("SELECT code FROM parfums WHERE actif = 0").fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):               # index unique actif
            conn.execute("INSERT INTO parfums (nom, code) VALUES ('Autre', 'p-1')")   # insensible à la casse
        conn.close()


    def test_migration_v4_utilisateurs_et_mot_de_passe(self):
        """Une base v4 (anciennes tables ventes/logs, mot de passe unique) est mise à niveau."""
        chemin = db.chemin_base()
        ancien = sqlite3.connect(str(chemin))
        ancien.executescript("""
            CREATE TABLE parametres (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
            INSERT INTO parametres VALUES ('schema_version', '4'), ('devise', 'DA'),
                ('mot_de_passe_hash', 'abc123hash'), ('mot_de_passe_sel', 'abc123sel');
            CREATE TABLE ventes (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER,
                date_vente TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                total REAL NOT NULL DEFAULT 0, cout_total REAL NOT NULL DEFAULT 0,
                benefice REAL NOT NULL DEFAULT 0, note TEXT);
            CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_log TEXT NOT NULL DEFAULT (datetime('now','localtime')), type TEXT NOT NULL,
                produit_type TEXT, produit_id INTEGER, produit_nom TEXT, quantite REAL, prix REAL,
                benefice REAL, vente_id INTEGER, details TEXT);
            INSERT INTO ventes (total) VALUES (500);
        """)
        ancien.close()
        conn = db.ouvrir_base().connexion
        colonnes = {r["name"] for r in conn.execute("PRAGMA table_info(ventes)")}
        self.assertTrue({"utilisateur_id", "session_id"} <= colonnes)
        self.assertEqual(conn.execute("SELECT total FROM ventes").fetchone()[0], 500)      # rien perdu
        admin = conn.execute("SELECT * FROM utilisateurs").fetchone()
        self.assertEqual((admin["identifiant"], admin["role"], admin["mot_de_passe_hash"]),
                         ("admin", "ADMIN", "abc123hash"))
        self.assertTrue(conn.execute("SELECT 1 FROM sqlite_master WHERE name='produits_caisse'").fetchone())
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
