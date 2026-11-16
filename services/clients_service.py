"""Gestion simple des clients (facultatifs sur une vente)."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from utils.erreurs import ErreurMetier


def creer_client(conn: sqlite3.Connection, nom: str, telephone: str = "",
                 note: str = "") -> int:
    nom = (nom or "").strip()
    if not nom:
        raise ErreurMetier("Le nom du client est obligatoire.")
    return conn.execute(
        "INSERT INTO clients (nom, telephone, note) VALUES (?, ?, ?)",
        (nom, (telephone or "").strip() or None, (note or "").strip() or None)).lastrowid


def lister_clients(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clients WHERE actif = 1 ORDER BY nom COLLATE NOCASE").fetchall()
