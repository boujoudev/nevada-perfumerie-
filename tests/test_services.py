"""Tests de la logique métier (étapes 2 à 5)."""

import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import connection as db  # noqa: E402
from services import (auth_service, clients_service, produits_service as ps,  # noqa: E402
                      stats_service as st, vente_service as vs)
from utils.erreurs import ErreurMetier  # noqa: E402
from utils.formatage import fmt_nombre, fmt_prix, parse_nombre  # noqa: E402


class BaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PARFUM_TEST"] = "1"
        os.environ["PARFUMERIE_DATA_DIR"] = self._tmp.name
        self.conn = db.ouvrir_base().connexion

    def tearDown(self):
        self.conn.close()
        os.environ.pop("PARFUMERIE_DATA_DIR", None)
        self._tmp.cleanup()

    # --- jeu de données : flacon 50 ml = 15 ml parfum + 35 ml alcool (automatique) ---
    def creer_jeu(self, stock_flacon="10", stock_parfum="500", stock_alcool="5000"):
        f = ps.creer_produit(self.conn, "FLACON", {
            "nom": "Carré 50ml", "capacite_ml": "50", "prix_achat": "100",
            "quantite_stock": stock_flacon, "qnt_parfum_necessaire": "15"})["id"]
        p = ps.creer_produit(self.conn, "PARFUM", {
            "nom": "Rose de Mai", "prix_achat_100ml": "1000",
            "quantite_stock_ml": stock_parfum})["id"]
        a = ps.creer_produit(self.conn, "ALCOOL", {
            "nom": "Alcool 96°", "prix_achat_litre": "500",
            "quantite_stock_ml": stock_alcool})["id"]
        return f, p, a

    def stock(self, table, col, id_=1):
        return self.conn.execute(f"SELECT {col} FROM {table} WHERE id=?", (id_,)).fetchone()[0]


class TestFormatage(unittest.TestCase):
    def test_parse_nombre(self):
        self.assertEqual(parse_nombre("1 234,5", "x"), 1234.5)
        self.assertEqual(parse_nombre("12", "x", entier=True), 12)
        for mauvais in ("", "abc", "nan", "-3"):
            with self.assertRaises(ErreurMetier):
                parse_nombre(mauvais, "x", minimum=0)
        with self.assertRaises(ErreurMetier):
            parse_nombre("2,5", "x", entier=True)
        with self.assertRaises(ErreurMetier):
            parse_nombre("0", "x", strictement_positif=True)

    def test_affichage(self):
        self.assertEqual(fmt_prix(1234.5), "1 234,50 DA")
        self.assertEqual(fmt_nombre(50.0), "50")
        self.assertEqual(fmt_nombre(1234.5), "1 234,5")


class TestProduits(BaseTest):
    def test_creation_flacon_entre_en_stock_et_log(self):
        f, _, _ = self.creer_jeu()
        self.assertEqual(self.stock("flacons", "quantite_stock", f), 10)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM logs WHERE type='CREATION'").fetchone()[0], 3)

    def test_validation_refuse_saisies_invalides(self):
        with self.assertRaises(ErreurMetier):
            ps.creer_produit(self.conn, "FLACON", {"nom": "", "capacite_ml": "50"})
        with self.assertRaises(ErreurMetier):
            ps.creer_produit(self.conn, "FLACON", {"nom": "X", "capacite_ml": "0",
                                                   "prix_achat": "1", "qnt_parfum_necessaire": "0"})
        with self.assertRaises(ErreurMetier):
            ps.creer_produit(self.conn, "PARFUM", {"nom": "P", "prix_achat_100ml": "abc"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM flacons").fetchone()[0], 0)

    def test_alcool_automatique_capacite_moins_parfum(self):
        res = ps.creer_produit(self.conn, "FLACON", {
            "nom": "Rond 100ml", "capacite_ml": "100", "prix_achat": "50",
            "qnt_parfum_necessaire": "30"})
        row = self.conn.execute("SELECT * FROM flacons WHERE id=?", (res["id"],)).fetchone()
        self.assertEqual(row["qnt_alcool_necessaire"], 70)
        # à la modification, l'alcool est recalculé
        ps.modifier_produit(self.conn, "FLACON", res["id"], {
            "nom": "Rond 100ml", "capacite_ml": "100", "prix_achat": "50",
            "quantite_stock": "0", "qnt_parfum_necessaire": "40", "seuil_alerte": "5"})
        row = self.conn.execute("SELECT * FROM flacons WHERE id=?", (res["id"],)).fetchone()
        self.assertEqual(row["qnt_alcool_necessaire"], 60)

    def test_parfum_superieur_a_la_capacite_refuse(self):
        with self.assertRaises(ErreurMetier):
            ps.creer_produit(self.conn, "FLACON", {
                "nom": "Petit", "capacite_ml": "30", "prix_achat": "1", "qnt_parfum_necessaire": "31"})
        with self.assertRaises(ErreurMetier):   # parfum obligatoire (sert au calcul de l'alcool)
            ps.creer_produit(self.conn, "FLACON", {
                "nom": "Petit", "capacite_ml": "30", "prix_achat": "1"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM flacons").fetchone()[0], 0)

    def test_valeurs_par_defaut(self):
        res = ps.creer_produit(self.conn, "PARFUM", {
            "nom": "P", "prix_achat_100ml": "1"})
        row = self.conn.execute("SELECT * FROM parfums WHERE id=?", (res["id"],)).fetchone()
        self.assertEqual((row["quantite_stock_ml"], row["seuil_alerte"]), (0, 100))

    def test_modifier_et_supprimer_doux(self):
        f, p, _ = self.creer_jeu()
        ps.modifier_produit(self.conn, "PARFUM", p, {
            "nom": "Rose Noire", "prix_achat_100ml": "1100",
            "quantite_stock_ml": "400", "seuil_alerte": "50"})
        self.assertEqual(self.conn.execute("SELECT nom FROM parfums WHERE id=?", (p,)).fetchone()[0],
                         "Rose Noire")
        ps.supprimer_produit(self.conn, "PARFUM", p)
        self.assertEqual(ps.rechercher(self.conn, "Rose", "Nom", "PARFUM"), [])
        # la ligne existe toujours en base (suppression douce)
        self.assertEqual(self.conn.execute("SELECT actif FROM parfums WHERE id=?", (p,)).fetchone()[0], 0)
        with self.assertRaises(ErreurMetier):
            ps.supprimer_produit(self.conn, "PARFUM", p)

    def test_reapprovisionnement_cree_log_achat(self):
        f, p, a = self.creer_jeu()
        nouveau = ps.reapprovisionner(self.conn, "PARFUM", p, "250")
        self.assertEqual(nouveau, 750)
        log = self.conn.execute("SELECT * FROM logs WHERE type='ACHAT'").fetchone()
        self.assertEqual((log["quantite"], log["prix"]), (250, 2500))  # 250 ml × 10 DA
        with self.assertRaises(ErreurMetier):
            ps.reapprovisionner(self.conn, "FLACON", f, "2,5")  # flacons = entiers
        with self.assertRaises(ErreurMetier):
            ps.reapprovisionner(self.conn, "PARFUM", p, "0")

    def test_reappro_alcool_prix_au_litre(self):
        _, _, a = self.creer_jeu()
        ps.reapprovisionner(self.conn, "ALCOOL", a, "2000")           # 2000 ml à 500 DA/L
        log = self.conn.execute("SELECT * FROM logs WHERE type='ACHAT'").fetchone()
        self.assertEqual((log["quantite"], log["prix"]), (2000, 1000))
        ligne = ps.rechercher(self.conn, "", "Nom", "ALCOOL")[0]
        self.assertEqual(ligne["prix_achat_txt"], "500,00 DA/L")

    def test_recherche(self):
        self.creer_jeu()
        self.assertEqual(len(ps.rechercher(self.conn)), 3)
        self.assertEqual(len(ps.rechercher(self.conn, "ROSE", "Nom")), 1)          # partielle, casse
        self.assertEqual(len(ps.rechercher(self.conn, "1", "ID")), 3)              # id 1 dans chaque table
        self.assertEqual(len(ps.rechercher(self.conn, "p-1", "ID")), 1)            # code préfixé
        self.assertEqual(len(ps.rechercher(self.conn, "", "Nom", "FLACON")), 1)    # filtre type
        self.assertEqual(ps.rechercher(self.conn, "zzz", "Nom"), [])

    def test_alerte_stock_bas(self):
        self.creer_jeu(stock_flacon="3")  # < 5
        alertes = ps.produits_en_alerte(self.conn)
        self.assertEqual([a["code"] for a in alertes], ["F-1"])
        self.assertTrue(ps.rechercher(self.conn, "", "Nom", "FLACON")[0]["bas"])


class TestVente(BaseTest):
    def test_couts_et_benefice_avec_prix_saisi(self):
        f, p, a = self.creer_jeu()
        l = vs.calculer_ligne(self.conn, f, p, a)
        self.assertEqual(l["cout_flacon"], 100)
        self.assertEqual(l["cout_parfum"], 150)     # 15 ml × 1000 / 100
        self.assertEqual(l["cout_alcool"], 17.5)    # 35 ml × 500 / 1000
        self.assertEqual(l["cout_total"], 267.5)
        self.assertIsNone(l["prix_final"])          # aucun prix calculé : il est saisi
        vs.appliquer_prix_final(l, 600)
        self.assertEqual(l["benefice"], 600 - 267.5)
        with self.assertRaises(ErreurMetier):
            vs.appliquer_prix_final(l, -1)

    def test_prix_de_vente_obligatoire(self):
        f, p, a = self.creer_jeu()
        with self.assertRaises(ErreurMetier):
            vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a}])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 0)

    def test_validation_decremente_stocks_et_logge(self):
        f, p, a = self.creer_jeu()
        res = vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a,
                                            "prix_final": 600}])
        self.assertEqual(res["total"], 600)
        self.assertEqual(self.stock("flacons", "quantite_stock"), 9)
        self.assertEqual(self.stock("parfums", "quantite_stock_ml"), 485)
        self.assertEqual(self.stock("alcools", "quantite_stock_ml"), 4965)
        log = self.conn.execute("SELECT * FROM logs WHERE type='VENTE'").fetchone()
        self.assertEqual((log["prix"], log["benefice"]), (600, 600 - 267.5))
        self.assertEqual(res["avertissements"], [])

    def test_flacon_du_client(self):
        f, p, a = self.creer_jeu()
        l = vs.calculer_ligne(self.conn, f, p, a, flacon_client=True)
        self.assertEqual(l["cout_flacon"], 0)
        self.assertEqual(l["cout_total"], 167.5)
        vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a,
                                      "flacon_client": True, "prix_final": 400}])
        self.assertEqual(self.conn.execute("SELECT benefice FROM ventes").fetchone()[0], 400 - 167.5)
        self.assertEqual(self.stock("flacons", "quantite_stock"), 10)       # inchangé
        self.assertEqual(self.stock("parfums", "quantite_stock_ml"), 485)   # consommé

    def test_stock_negatif_autorise_avec_avertissement(self):
        f, p, a = self.creer_jeu(stock_flacon="0", stock_parfum="5")
        l = vs.calculer_ligne(self.conn, f, p, a)
        self.assertIn("Flacon en rupture de stock", l["avertissements"])
        self.assertIn("Parfum en rupture de stock", l["avertissements"])
        res = vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a,
                                            "prix_final": 500}])
        self.assertEqual(self.stock("flacons", "quantite_stock"), -1)
        self.assertEqual(self.stock("parfums", "quantite_stock_ml"), -10)
        self.assertEqual(len(res["avertissements"]), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 1)

    def test_vente_multi_lignes_et_client(self):
        f, p, a = self.creer_jeu()
        c = clients_service.creer_client(self.conn, "Karim", "0555")
        res = vs.valider_vente(self.conn, [
            {"flacon_id": f, "parfum_id": p, "alcool_id": a, "prix_final": 635},
            {"flacon_id": f, "parfum_id": p, "alcool_id": None, "prix_final": 500}], client_id=c)
        self.assertEqual(res["total"], 635 + 500)
        self.assertEqual(self.stock("flacons", "quantite_stock"), 8)
        self.assertEqual(self.stock("alcools", "quantite_stock_ml"), 4965)   # 2e ligne sans alcool
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lignes_vente").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT client_id FROM ventes").fetchone()[0], c)

    def test_panier_vide_refuse(self):
        with self.assertRaises(ErreurMetier):
            vs.valider_vente(self.conn, [])

    def test_echec_annule_tout(self):
        f, p, a = self.creer_jeu()
        with self.assertRaises(ErreurMetier):
            vs.valider_vente(self.conn, [
                {"flacon_id": f, "parfum_id": p, "alcool_id": a, "prix_final": 600},
                {"flacon_id": 999, "parfum_id": p, "prix_final": 600}])           # 2e ligne invalide
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 0)
        self.assertEqual(self.stock("flacons", "quantite_stock"), 10)

    def test_suppression_vente_remet_stock_et_logge(self):
        f, p, a = self.creer_jeu()
        r1 = vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a,
                                           "prix_final": 600}])
        r2 = vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a,
                                           "flacon_client": True, "prix_final": 400}])
        vs.supprimer_vente(self.conn, r1["vente_id"])
        vs.supprimer_vente(self.conn, r2["vente_id"])
        self.assertEqual(self.stock("flacons", "quantite_stock"), 10)       # pas de +1 en trop
        self.assertEqual(self.stock("parfums", "quantite_stock_ml"), 500)
        self.assertEqual(self.stock("alcools", "quantite_stock_ml"), 5000)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ventes").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lignes_vente").fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM logs WHERE type='ANNULATION'").fetchone()[0], 2)
        with self.assertRaises(ErreurMetier):
            vs.supprimer_vente(self.conn, r1["vente_id"])                   # déjà supprimée


class TestStatsEtExport(BaseTest):
    def vendre(self, n=1, prix=600):
        f, p, a = self.creer_jeu()
        for _ in range(n):
            vs.valider_vente(self.conn, [{"flacon_id": f, "parfum_id": p, "alcool_id": a,
                                          "prix_final": prix}])

    def test_resume_et_valeur_stock(self):
        self.vendre(2, prix=600)
        r = st.resume_standard(self.conn)
        for periode in ("Aujourd'hui", "Ce mois", "Cette année"):
            self.assertEqual(r[periode]["nb_ventes"], 2)
            self.assertEqual(r[periode]["ca"], 1200)
            self.assertEqual(r[periode]["benefice"], 2 * (600 - 267.5))
        # stock : 8 flacons×100 + 470 ml×10 + 4930 ml×0.5
        self.assertEqual(st.valeur_stock(self.conn), 800 + 4700 + 2465)

    def test_ventes_supprimees_exclues_des_stats(self):
        self.vendre(2, prix=600)
        vid = self.conn.execute("SELECT id FROM ventes LIMIT 1").fetchone()[0]
        vs.supprimer_vente(self.conn, vid)
        self.assertEqual(st.resume_standard(self.conn)["Aujourd'hui"]["nb_ventes"], 1)
        logs = st.lister_logs(self.conn, None, None, "Tous")
        self.assertEqual(st.totaux_nets(logs), (600.0, 600 - 267.5))   # vente - annulation

    def test_top_produits(self):
        self.vendre(3)
        self.assertEqual(st.top_parfums(self.conn)[0]["nom"], "Rose de Mai")
        self.assertEqual(st.top_parfums(self.conn)[0]["nb_ventes"], 3)
        self.assertEqual(st.top_flacons(self.conn)[0]["nb_ventes"], 3)

    def test_bornes(self):
        j = date(2026, 11, 15)  # dimanche
        self.assertEqual(st.bornes("Aujourd'hui", aujourdhui=j),
                         ("2026-11-15 00:00:00", "2026-11-16 00:00:00"))
        self.assertEqual(st.bornes("Cette semaine", aujourdhui=j),
                         ("2026-11-09 00:00:00", "2026-11-16 00:00:00"))
        self.assertEqual(st.bornes("Ce mois", aujourdhui=j),
                         ("2026-11-01 00:00:00", "2026-12-01 00:00:00"))
        self.assertEqual(st.bornes("Cette année", aujourdhui=j),
                         ("2026-01-01 00:00:00", "2027-01-01 00:00:00"))
        self.assertEqual(st.bornes("Tout"), (None, None))
        self.assertEqual(st.bornes("Personnalisé", "01/11/2026", "05/11/2026"),
                         ("2026-11-01 00:00:00", "2026-11-06 00:00:00"))
        with self.assertRaises(ErreurMetier):
            st.bornes("Personnalisé", "10/11/2026", "05/11/2026")
        with self.assertRaises(ErreurMetier):
            st.bornes("Personnalisé", "pas une date", "")

    def test_filtres_type_et_periode(self):
        self.vendre(1)
        ps.reapprovisionner(self.conn, "PARFUM", 1, "100")
        tous = st.lister_logs(self.conn, None, None, "Tous")
        ventes = st.lister_logs(self.conn, None, None, "Ventes")
        achats = st.lister_logs(self.conn, None, None, "Achats")
        self.assertEqual((len(ventes), len(achats)), (1, 1))
        self.assertGreater(len(tous), 2)
        hier = st.bornes("Personnalisé", "01/01/2000", "01/01/2000")
        self.assertEqual(st.lister_logs(self.conn, *hier, "Tous"), [])

    def test_export_csv(self):
        self.vendre(1, prix=600)
        logs = st.lister_logs(self.conn, None, None, "Ventes")
        chemin = os.path.join(self._tmp.name, "export.csv")
        self.assertEqual(st.exporter_csv(chemin, logs), 1)
        with open(chemin, encoding="utf-8-sig", newline="") as f:
            lignes = list(csv.reader(f, delimiter=";"))
        self.assertEqual(lignes[0][:3], ["Date/Heure", "Type", "Produit"])
        self.assertEqual(lignes[1][1], "Vente")
        self.assertEqual(lignes[1][4], "600")
        self.assertEqual(lignes[1][5], "332,5")
        with self.assertRaises(ErreurMetier):
            st.exporter_csv(os.path.join(self._tmp.name, "dossier_inexistant", "x.csv"), logs)


class TestAuth(BaseTest):
    def test_cycle_mot_de_passe(self):
        self.assertFalse(auth_service.a_mot_de_passe(self.conn))
        with self.assertRaises(ErreurMetier):
            auth_service.definir_mot_de_passe(self.conn, "abc", "abc")        # trop court
        with self.assertRaises(ErreurMetier):
            auth_service.definir_mot_de_passe(self.conn, "secret1", "secret2")
        auth_service.definir_mot_de_passe(self.conn, "secret1", "secret1")
        self.assertTrue(auth_service.a_mot_de_passe(self.conn))
        self.assertTrue(auth_service.verifier_mot_de_passe(self.conn, "secret1"))
        self.assertFalse(auth_service.verifier_mot_de_passe(self.conn, "faux"))
        auth_service.supprimer_mot_de_passe(self.conn)
        self.assertFalse(auth_service.a_mot_de_passe(self.conn))


class TestClients(BaseTest):
    def test_creer_et_lister(self):
        clients_service.creer_client(self.conn, "  Amine ", "0550")
        self.assertEqual([c["nom"] for c in clients_service.lister_clients(self.conn)], ["Amine"])
        with self.assertRaises(ErreurMetier):
            clients_service.creer_client(self.conn, "  ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
