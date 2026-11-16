"""Mot de passe facultatif de l'application."""

from __future__ import annotations

import sqlite3

from database.connection import transaction
from utils.erreurs import ErreurMetier
from utils.securite import hacher, verifier


def _lire(conn: sqlite3.Connection, cle: str) -> str:
    row = conn.execute("SELECT valeur FROM parametres WHERE cle = ?", (cle,)).fetchone()
    return row["valeur"] if row else ""


def a_mot_de_passe(conn: sqlite3.Connection) -> bool:
    return bool(_lire(conn, "mot_de_passe_hash"))


def verifier_mot_de_passe(conn: sqlite3.Connection, mot_de_passe: str) -> bool:
    return verifier(mot_de_passe, _lire(conn, "mot_de_passe_hash"), _lire(conn, "mot_de_passe_sel"))


def definir_mot_de_passe(conn: sqlite3.Connection, mot_de_passe: str, confirmation: str) -> None:
    if len(mot_de_passe) < 4:
        raise ErreurMetier("Le mot de passe doit contenir au moins 4 caractères.")
    if mot_de_passe != confirmation:
        raise ErreurMetier("Les deux mots de passe ne correspondent pas.")
    empreinte, sel = hacher(mot_de_passe)
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO parametres (cle, valeur) VALUES ('mot_de_passe_hash', ?)", (empreinte,))
        conn.execute("INSERT OR REPLACE INTO parametres (cle, valeur) VALUES ('mot_de_passe_sel', ?)", (sel,))


def supprimer_mot_de_passe(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("UPDATE parametres SET valeur = '' WHERE cle IN ('mot_de_passe_hash', 'mot_de_passe_sel')")
