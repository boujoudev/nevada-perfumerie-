"""Accès SQL au journal (table logs)."""

from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence


def ajouter(conn: sqlite3.Connection, type_log: str, produit_type: Optional[str] = None,
            produit_id: Optional[int] = None, produit_nom: Optional[str] = None,
            quantite: Optional[float] = None, prix: Optional[float] = None,
            benefice: Optional[float] = None, vente_id: Optional[int] = None,
            details: Optional[str] = None, utilisateur_id: Optional[int] = None,
            session_id: Optional[int] = None) -> int:
    return conn.execute(
        """INSERT INTO logs (type, produit_type, produit_id, produit_nom, quantite,
                             prix, benefice, vente_id, details, utilisateur_id, session_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (type_log, produit_type, produit_id, produit_nom, quantite, prix,
         benefice, vente_id, details, utilisateur_id, session_id),
    ).lastrowid


def lister(conn: sqlite3.Connection, debut: Optional[str], fin: Optional[str],
           types: Optional[Sequence[str]], ventes_existantes_seulement: bool = False) -> List[sqlite3.Row]:
    """Logs entre debut (inclus) et fin (exclu), filtrés par types, du plus récent au plus ancien.

    ventes_existantes_seulement : les lignes « Vente » dont la vente a été supprimée sont masquées.
    """
    sql = ("SELECT logs.*, u.nom AS utilisateur_nom FROM logs LEFT JOIN utilisateurs u "
           "ON u.id = logs.utilisateur_id WHERE (? IS NULL OR logs.date_log >= ?) "
           "AND (? IS NULL OR logs.date_log < ?)")
    params: list = [debut, debut, fin, fin]
    if types:
        sql += f" AND logs.type IN ({', '.join('?' for _ in types)})"
        params.extend(types)
    if ventes_existantes_seulement:
        sql += " AND (logs.type != 'VENTE' OR logs.vente_id IN (SELECT id FROM ventes))"
    sql += " ORDER BY logs.date_log DESC, logs.id DESC"
    return conn.execute(sql, params).fetchall()
