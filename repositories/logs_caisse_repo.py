"""Accès SQL au journal de la caisse (table logs_caisse)."""

from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence


def ajouter(conn: sqlite3.Connection, type_log: str, utilisateur_id: Optional[int] = None,
            session_id: Optional[int] = None, produit_id: Optional[int] = None,
            produit_nom: Optional[str] = None, quantite: Optional[float] = None,
            prix: Optional[float] = None, benefice: Optional[float] = None,
            ticket_id: Optional[int] = None, details: Optional[str] = None) -> int:
    return conn.execute(
        """INSERT INTO logs_caisse (type, utilisateur_id, session_id, produit_id, produit_nom,
                                    quantite, prix, benefice, ticket_id, details)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (type_log, utilisateur_id, session_id, produit_id, produit_nom, quantite, prix,
         benefice, ticket_id, details)).lastrowid


def lister(conn: sqlite3.Connection, debut: Optional[str], fin: Optional[str],
           types: Optional[Sequence[str]] = None,
           ventes_valides_seulement: bool = False) -> List[sqlite3.Row]:
    """Logs entre debut (inclus) et fin (exclu), avec le nom de l'utilisateur, du plus récent au plus ancien.

    ventes_valides_seulement : les lignes « Vente » dont le ticket a été annulé sont masquées.
    """
    sql = ("SELECT l.*, u.nom AS utilisateur_nom FROM logs_caisse l "
           "LEFT JOIN utilisateurs u ON u.id = l.utilisateur_id "
           "WHERE (? IS NULL OR l.date_log >= ?) AND (? IS NULL OR l.date_log < ?)")
    params: list = [debut, debut, fin, fin]
    if types:
        sql += f" AND l.type IN ({', '.join('?' for _ in types)})"
        params.extend(types)
    if ventes_valides_seulement:
        sql += " AND (l.type != 'VENTE' OR l.ticket_id IN (SELECT id FROM tickets WHERE statut = 'VALIDE'))"
    sql += " ORDER BY l.date_log DESC, l.id DESC"
    return conn.execute(sql, params).fetchall()
