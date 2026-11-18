"""Logique métier des ventes : calcul des prix, validation, suppression."""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from database.connection import transaction
from models.catalogue import CATALOGUE
from repositories import logs_repo, produits_repo
from services import session_service, utilisateurs_service
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_nombre


def _r(valeur: float) -> float:
    return round(float(valeur), 2)


def appliquer_prix_final(ligne: dict, prix_final: float) -> dict:
    """Applique le prix de vente saisi et calcule le bénéfice (prix - coût de revient)."""
    if prix_final < 0:
        raise ErreurMetier("Le prix de vente ne peut pas être négatif.")
    ligne["prix_final"] = _r(prix_final)
    ligne["benefice"] = _r(ligne["prix_final"] - ligne["cout_total"])
    return ligne


def calculer_ligne(conn: sqlite3.Connection, flacon_id: int, parfum_id: int,
                   alcool_id: Optional[int] = None, flacon_client: bool = False) -> dict:
    """Calcule les COÛTS d'une combinaison et les avertissements de stock.

    Le prix de vente n'est pas calculé : il est saisi par le vendeur
    (voir appliquer_prix_final).

    Coût parfum = qnt_parfum (ml) × prix_achat_100ml / 100
    Coût alcool = qnt_alcool (ml) × prix_achat_litre / 1000
    Flacon apporté par le client : coût du flacon = 0, stock du flacon inchangé.
    """
    flacon = produits_repo.obtenir(conn, "FLACON", flacon_id)
    parfum = produits_repo.obtenir(conn, "PARFUM", parfum_id)
    if flacon is None or parfum is None:
        raise ErreurMetier("Flacon ou parfum introuvable (peut-être supprimé).")
    alcool = produits_repo.obtenir(conn, "ALCOOL", alcool_id) if alcool_id else None
    if alcool_id and alcool is None:
        raise ErreurMetier("Alcool introuvable (peut-être supprimé).")

    qte_parfum = flacon["qnt_parfum_necessaire"]
    qte_alcool = flacon["qnt_alcool_necessaire"] if alcool else 0.0

    cout_flacon = 0.0 if flacon_client else flacon["prix_achat"]
    cout_parfum = qte_parfum * parfum["prix_achat_100ml"] / 100
    cout_alcool = qte_alcool * alcool["prix_achat_litre"] / 1000 if alcool else 0.0

    avertissements: List[str] = []
    if not flacon_client and flacon["quantite_stock"] < 1:
        avertissements.append("Flacon en rupture de stock")
    if parfum["quantite_stock_ml"] < qte_parfum:
        avertissements.append("Parfum en rupture de stock")
    if alcool and alcool["quantite_stock_ml"] < qte_alcool:
        avertissements.append("Alcool en rupture de stock")

    return {
        "flacon_id": flacon_id, "parfum_id": parfum_id,
        "alcool_id": alcool["id"] if alcool else None,
        "flacon_client": bool(flacon_client),
        "flacon_nom": flacon["nom"], "parfum_nom": parfum["nom"],
        "alcool_nom": alcool["nom"] if alcool else None,
        "qnt_parfum_ml": qte_parfum, "qnt_alcool_ml": qte_alcool,
        "cout_flacon": _r(cout_flacon), "cout_parfum": _r(cout_parfum),
        "cout_alcool": _r(cout_alcool),
        "cout_total": _r(cout_flacon + cout_parfum + cout_alcool),
        "prix_final": None, "benefice": None,       # renseignés par appliquer_prix_final
        "avertissements": avertissements,
    }


def _libelle_produit(ligne: dict) -> str:
    suffixe = " (flacon client)" if ligne["flacon_client"] else ""
    return f"{ligne['flacon_nom']} + {ligne['parfum_nom']}{suffixe}"


def valider_vente(conn: sqlite3.Connection, lignes: List[dict],
                  client_id: Optional[int] = None, note: Optional[str] = None,
                  utilisateur=None) -> dict:
    """Enregistre une vente (1 ou plusieurs combinaisons) en une seule transaction.

    Chaque élément de `lignes` : flacon_id, parfum_id, alcool_id (ou None),
    flacon_client (bool), prix_final (OBLIGATOIRE : prix de vente saisi).
    Les stocks peuvent devenir négatifs : la vente est enregistrée avec un avertissement.
    """
    if not lignes:
        raise ErreurMetier("Le panier est vide : ajoutez au moins une combinaison.")
    # Avec un utilisateur connecté, la vente va dans la session de caisse ouverte (obligatoire)
    session = session_service.exiger_session_active(conn) if utilisateur is not None else None
    utilisateur_id = utilisateur["id"] if utilisateur is not None else None
    session_id = session["id"] if session is not None else None

    with transaction(conn):
        calculees: List[dict] = []
        for saisie in lignes:
            ligne = calculer_ligne(conn, saisie["flacon_id"], saisie["parfum_id"],
                                   saisie.get("alcool_id"), bool(saisie.get("flacon_client")))
            if saisie.get("prix_final") is None:
                raise ErreurMetier("Indiquez le prix de vente de chaque article.")
            appliquer_prix_final(ligne, float(saisie["prix_final"]))
            calculees.append(ligne)

        total = _r(sum(l["prix_final"] for l in calculees))
        cout = _r(sum(l["cout_total"] for l in calculees))
        benefice = _r(total - cout)

        nom_client = None
        if client_id:
            row = conn.execute("SELECT nom FROM clients WHERE id = ?", (client_id,)).fetchone()
            nom_client = row["nom"] if row else None
            if row is None:
                client_id = None

        vente_id = conn.execute(
            "INSERT INTO ventes (client_id, total, cout_total, benefice, note, utilisateur_id, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (client_id, total, cout, benefice, note, utilisateur_id, session_id)).lastrowid

        touches = set()
        for l in calculees:
            conn.execute(
                """INSERT INTO lignes_vente
                   (vente_id, flacon_id, parfum_id, alcool_id, flacon_client, flacon_nom,
                    parfum_nom, qnt_parfum_ml, qnt_alcool_ml, prix_calcule, prix_final,
                    cout_flacon, cout_parfum, cout_alcool, benefice)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (vente_id, l["flacon_id"], l["parfum_id"], l["alcool_id"], int(l["flacon_client"]),
                 l["flacon_nom"], l["parfum_nom"], l["qnt_parfum_ml"], l["qnt_alcool_ml"],
                 l["prix_final"], l["prix_final"], l["cout_flacon"], l["cout_parfum"],
                 l["cout_alcool"], l["benefice"]))

            if not l["flacon_client"]:
                produits_repo.ajuster_stock(conn, "FLACON", l["flacon_id"], -1)
                touches.add(("FLACON", l["flacon_id"]))
            produits_repo.ajuster_stock(conn, "PARFUM", l["parfum_id"], -l["qnt_parfum_ml"])
            touches.add(("PARFUM", l["parfum_id"]))
            if l["alcool_id"]:
                produits_repo.ajuster_stock(conn, "ALCOOL", l["alcool_id"], -l["qnt_alcool_ml"])
                touches.add(("ALCOOL", l["alcool_id"]))

            details = f"Vente #{vente_id}"
            if nom_client:
                details += f" — client : {nom_client}"
            logs_repo.ajouter(conn, "VENTE", None, None, _libelle_produit(l), quantite=1,
                              prix=l["prix_final"], benefice=l["benefice"],
                              vente_id=vente_id, details=details,
                              utilisateur_id=utilisateur_id, session_id=session_id)

        avertissements: List[str] = []
        for type_code, identifiant in sorted(touches):
            t = CATALOGUE[type_code]
            produit = produits_repo.obtenir(conn, type_code, identifiant, actif_seulement=False)
            if produit[t.colonne_stock] < 0:
                avertissements.append(
                    f"Stock négatif : {produit['nom']} ({fmt_nombre(produit[t.colonne_stock])} {t.unite_stock})")

    return {"vente_id": vente_id, "total": total, "benefice": benefice,
            "avertissements": avertissements}


def supprimer_vente(conn: sqlite3.Connection, vente_id: int, utilisateur=None) -> None:
    """Supprime une vente, remet les stocks et garde une trace dans les logs.

    Le flacon n'est pas remis en stock s'il avait été apporté par le client.
    Avec un utilisateur : réservé à l'ADMIN, et impossible si la session de la vente est clôturée
    (les sessions clôturées ne changent plus : faire un mouvement de caisse à la place).
    """
    vente = conn.execute("SELECT * FROM ventes WHERE id = ?", (vente_id,)).fetchone()
    if vente is None:
        raise ErreurMetier("Cette vente n'existe plus (déjà supprimée ?).")
    if utilisateur is not None:
        utilisateurs_service.exiger_admin(utilisateur, "La suppression d'une vente est réservée à l'administrateur.")
        if vente["session_id"] is not None:
            session = session_service.lire(conn, vente["session_id"])
            if session is not None and session["statut"] == "CLOTUREE":
                raise ErreurMetier("La session de cette vente est clôturée : elle ne peut plus être modifiée. "
                                   "Enregistrez plutôt un mouvement de caisse (remboursement).")
    lignes = conn.execute("SELECT * FROM lignes_vente WHERE vente_id = ?", (vente_id,)).fetchall()

    with transaction(conn):
        resume = []
        for l in lignes:
            if not l["flacon_client"]:
                produits_repo.ajuster_stock(conn, "FLACON", l["flacon_id"], +1)
            produits_repo.ajuster_stock(conn, "PARFUM", l["parfum_id"], +l["qnt_parfum_ml"])
            if l["alcool_id"]:
                produits_repo.ajuster_stock(conn, "ALCOOL", l["alcool_id"], +l["qnt_alcool_ml"])
            resume.append(f"{l['flacon_nom']} + {l['parfum_nom']} ({l['prix_final']})")
        logs_repo.ajouter(
            conn, "ANNULATION", None, None, f"Vente #{vente_id} supprimée", quantite=1,
            prix=-vente["total"], benefice=-vente["benefice"], vente_id=vente_id,
            details=f"Vente du {fmt_datetime(vente['date_vente'])} supprimée ; stocks remis. "
                    f"Contenu : " + " ; ".join(resume),
            utilisateur_id=utilisateur["id"] if utilisateur is not None else None,
            session_id=vente["session_id"])
        conn.execute("DELETE FROM ventes WHERE id = ?", (vente_id,))
