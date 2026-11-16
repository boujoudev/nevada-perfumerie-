"""Accès SQL aux produits (flacons, parfums, alcools). Aucune règle métier ici."""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from models.catalogue import CATALOGUE


def _verifier_cles(type_code: str, valeurs: Dict[str, object]) -> None:
    """Sécurité : seules les colonnes connues du catalogue sont acceptées."""
    autorisees = set(CATALOGUE[type_code].cles)
    inconnues = set(valeurs) - autorisees
    if inconnues:
        raise ValueError(f"Colonnes inconnues : {sorted(inconnues)}")


def inserer(conn: sqlite3.Connection, type_code: str, valeurs: Dict[str, object]) -> int:
    _verifier_cles(type_code, valeurs)
    colonnes = list(valeurs)
    sql = (f"INSERT INTO {CATALOGUE[type_code].table} ({', '.join(colonnes)}) "
           f"VALUES ({', '.join('?' for _ in colonnes)})")
    return conn.execute(sql, [valeurs[c] for c in colonnes]).lastrowid


def modifier(conn: sqlite3.Connection, type_code: str, identifiant: int,
             valeurs: Dict[str, object]) -> None:
    _verifier_cles(type_code, valeurs)
    affectations = ", ".join(f"{c} = ?" for c in valeurs)
    sql = f"UPDATE {CATALOGUE[type_code].table} SET {affectations} WHERE id = ?"
    conn.execute(sql, [*valeurs.values(), identifiant])


def obtenir(conn: sqlite3.Connection, type_code: str, identifiant: int,
            actif_seulement: bool = True) -> Optional[sqlite3.Row]:
    sql = f"SELECT * FROM {CATALOGUE[type_code].table} WHERE id = ?"
    if actif_seulement:
        sql += " AND actif = 1"
    return conn.execute(sql, (identifiant,)).fetchone()


def lister(conn: sqlite3.Connection, type_code: str) -> List[sqlite3.Row]:
    sql = (f"SELECT * FROM {CATALOGUE[type_code].table} "
           "WHERE actif = 1 ORDER BY nom COLLATE NOCASE")
    return conn.execute(sql).fetchall()


def desactiver(conn: sqlite3.Connection, type_code: str, identifiant: int) -> None:
    conn.execute(f"UPDATE {CATALOGUE[type_code].table} SET actif = 0 WHERE id = ?",
                 (identifiant,))


def ajuster_stock(conn: sqlite3.Connection, type_code: str, identifiant: int,
                  delta: float) -> None:
    """Ajoute (delta > 0) ou retire (delta < 0) du stock, de façon atomique."""
    t = CATALOGUE[type_code]
    conn.execute(f"UPDATE {t.table} SET {t.colonne_stock} = {t.colonne_stock} + ? WHERE id = ?",
                 (delta, identifiant))
