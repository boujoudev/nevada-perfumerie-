"""Utilisateurs, mots de passe et droits d'accès (ADMIN / CAISSIER)."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from database.connection import transaction
from utils.erreurs import ErreurMetier
from utils.securite import hacher, verifier

ROLES = ("ADMIN", "CAISSIER")
LIBELLES_ROLE = {"ADMIN": "Administrateur", "CAISSIER": "Caissier"}
LONGUEUR_MIN_MOT_DE_PASSE = 4

# Ce que peut faire un caissier. L'administrateur peut tout faire.
PERMISSIONS_CAISSIER = frozenset({
    "parfum_vente", "caisse_vente", "caisse_retour", "caisse_stock_lecture",
    "session", "mouvement_caisse",
})


def autorise(role: str, action: str) -> bool:
    """True si ce rôle a le droit d'effectuer cette action."""
    return role == "ADMIN" or action in PERMISSIONS_CAISSIER


def exiger_admin(utilisateur, message: str = "Action réservée à l'administrateur.") -> None:
    if utilisateur is None or utilisateur["role"] != "ADMIN":
        raise ErreurMetier(message)


# ------------------------------------------------------------------ validation
def _nettoyer_identifiant(identifiant: str) -> str:
    identifiant = (identifiant or "").strip()
    if not identifiant:
        raise ErreurMetier("L'identifiant est obligatoire.")
    if len(identifiant) > 30 or any(c.isspace() for c in identifiant):
        raise ErreurMetier("L'identifiant ne doit pas contenir d'espace (30 caractères maximum).")
    return identifiant


def _verifier_mot_de_passe(mot_de_passe: str, confirmation: str) -> None:
    if len(mot_de_passe or "") < LONGUEUR_MIN_MOT_DE_PASSE:
        raise ErreurMetier(f"Le mot de passe doit contenir au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères.")
    if mot_de_passe != confirmation:
        raise ErreurMetier("Les deux mots de passe ne correspondent pas.")


def _nb_admins_actifs(conn: sqlite3.Connection, exclure: Optional[int] = None) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM utilisateurs WHERE role = 'ADMIN' AND actif = 1 AND id != ?",
        (exclure or 0,)).fetchone()[0]


# ---------------------------------------------------------------------- lecture
def a_des_utilisateurs(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0] > 0


def obtenir(conn: sqlite3.Connection, utilisateur_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM utilisateurs WHERE id = ?", (utilisateur_id,)).fetchone()


def lister_utilisateurs(conn: sqlite3.Connection, actifs_seulement: bool = False) -> List[sqlite3.Row]:
    sql = "SELECT * FROM utilisateurs"
    if actifs_seulement:
        sql += " WHERE actif = 1"
    return conn.execute(sql + " ORDER BY nom COLLATE NOCASE").fetchall()


def authentifier(conn: sqlite3.Connection, identifiant: str, mot_de_passe: str) -> Optional[sqlite3.Row]:
    """Retourne l'utilisateur si identifiant + mot de passe sont corrects (et le compte actif)."""
    utilisateur = conn.execute(
        "SELECT * FROM utilisateurs WHERE identifiant = ? COLLATE NOCASE AND actif = 1",
        ((identifiant or "").strip(),)).fetchone()
    if utilisateur and verifier(mot_de_passe or "", utilisateur["mot_de_passe_hash"],
                                utilisateur["mot_de_passe_sel"]):
        return utilisateur
    return None


# --------------------------------------------------------------------- écriture
def creer_utilisateur(conn: sqlite3.Connection, nom: str, identifiant: str, mot_de_passe: str,
                      confirmation: str, role: str = "CAISSIER") -> int:
    nom = (nom or "").strip()
    if not nom:
        raise ErreurMetier("Le nom est obligatoire.")
    if role not in ROLES:
        raise ErreurMetier("Rôle inconnu.")
    identifiant = _nettoyer_identifiant(identifiant)
    _verifier_mot_de_passe(mot_de_passe, confirmation)
    if conn.execute("SELECT 1 FROM utilisateurs WHERE identifiant = ? COLLATE NOCASE",
                    (identifiant,)).fetchone():
        raise ErreurMetier(f"L'identifiant « {identifiant} » est déjà utilisé.")
    empreinte, sel = hacher(mot_de_passe)
    return conn.execute(
        "INSERT INTO utilisateurs (nom, identifiant, mot_de_passe_hash, mot_de_passe_sel, role) "
        "VALUES (?, ?, ?, ?, ?)", (nom, identifiant, empreinte, sel, role)).lastrowid


def modifier_utilisateur(conn: sqlite3.Connection, utilisateur_id: int, nom: str, role: str,
                         actif: bool = True) -> None:
    """Change le nom, le rôle ou l'état (actif/désactivé). Il doit toujours rester un admin actif."""
    utilisateur = obtenir(conn, utilisateur_id)
    if utilisateur is None:
        raise ErreurMetier("Utilisateur introuvable.")
    nom = (nom or "").strip()
    if not nom:
        raise ErreurMetier("Le nom est obligatoire.")
    if role not in ROLES:
        raise ErreurMetier("Rôle inconnu.")
    if utilisateur["role"] == "ADMIN" and utilisateur["actif"] and (role != "ADMIN" or not actif):
        if _nb_admins_actifs(conn, exclure=utilisateur_id) == 0:
            raise ErreurMetier("Il doit rester au moins un administrateur actif.")
    if utilisateur["actif"] and not actif:
        ouverte = conn.execute(
            "SELECT 1 FROM sessions_caisse WHERE utilisateur_id = ? AND statut != 'CLOTUREE'",
            (utilisateur_id,)).fetchone()
        if ouverte:
            raise ErreurMetier("Cet utilisateur a une session de caisse non clôturée : clôturez-la d'abord.")
    conn.execute("UPDATE utilisateurs SET nom = ?, role = ?, actif = ? WHERE id = ?",
                 (nom, role, 1 if actif else 0, utilisateur_id))


def changer_mot_de_passe(conn: sqlite3.Connection, utilisateur_id: int, mot_de_passe: str,
                         confirmation: str) -> None:
    if obtenir(conn, utilisateur_id) is None:
        raise ErreurMetier("Utilisateur introuvable.")
    _verifier_mot_de_passe(mot_de_passe, confirmation)
    empreinte, sel = hacher(mot_de_passe)
    with transaction(conn):
        conn.execute("UPDATE utilisateurs SET mot_de_passe_hash = ?, mot_de_passe_sel = ? WHERE id = ?",
                     (empreinte, sel, utilisateur_id))
