"""Gestion de la connexion SQLite : emplacement des données, création du
schéma, sauvegardes automatiques et récupération en cas de corruption.

Les données sont stockées dans le dossier utilisateur (jamais dans
Program Files) :
    Windows : %APPDATA%\\GestionParfumerie\\
    Autres  : ~/.local/share/GestionParfumerie/
La variable d'environnement PARFUMERIE_DATA_DIR permet de forcer un autre
dossier (utile pour les tests).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

NOM_APP = "GestionParfumerie"
NOM_FICHIER_DB = "parfumerie.db"
NB_SAUVEGARDES_MAX = 10
VERSION_SCHEMA = 3


# --------------------------------------------------------------------------
# Chemins
# --------------------------------------------------------------------------
def dossier_donnees() -> Path:
    """Retourne (et crée si besoin) le dossier de données de l'application."""
    surcharge = os.environ.get("PARFUMERIE_DATA_DIR")
    if surcharge:
        base = Path(surcharge)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / NOM_APP
    else:
        base = Path.home() / ".local" / "share" / NOM_APP
    base.mkdir(parents=True, exist_ok=True)
    return base


def chemin_base() -> Path:
    """Chemin complet du fichier de base de données."""
    return dossier_donnees() / NOM_FICHIER_DB


def dossier_sauvegardes() -> Path:
    """Dossier des copies de sécurité."""
    dossier = dossier_donnees() / "sauvegardes"
    dossier.mkdir(exist_ok=True)
    return dossier


def _chemin_schema() -> Path:
    """Chemin de schema.sql, compatible PyInstaller (sys._MEIPASS)."""
    racine = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidat = racine / "database" / "schema.sql"
    return candidat if candidat.exists() else Path(__file__).with_name("schema.sql")


# --------------------------------------------------------------------------
# Connexion
# --------------------------------------------------------------------------
def creer_connexion(chemin: Optional[Path] = None) -> sqlite3.Connection:
    """Ouvre une connexion configurée (clés étrangères, lignes nommées).

    isolation_level=None : mode autocommit ; les opérations à plusieurs
    étapes utilisent transaction() pour être atomiques.
    """
    chemin = Path(chemin) if chemin else chemin_base()
    conn = sqlite3.connect(str(chemin), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Exécute un bloc dans une transaction : tout passe ou rien.

    Exemple :
        with transaction(conn):
            conn.execute(...)
            conn.execute(...)
    """
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def creer_schema(conn: sqlite3.Connection) -> None:
    """Crée les tables manquantes à partir de schema.sql, puis migre si besoin (idempotent)."""
    sql = _chemin_schema().read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    _migrer(conn)


def _colonnes(conn: sqlite3.Connection, table: str) -> set:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrer(conn: sqlite3.Connection) -> None:
    """Met à niveau une base créée avec une ancienne version de l'application.

    v1 -> v2 : prix de l'alcool au ml -> au litre (valeurs x 1000).
    v2 -> v3 : prix du parfum au ml / 10 ml -> pour 100 ml. Les nombres déjà saisis sont
               conservés tels quels : ils étaient destinés à être des prix pour 100 ml.
    """
    ligne = conn.execute("SELECT valeur FROM parametres WHERE cle = 'schema_version'").fetchone()
    version = int(ligne["valeur"]) if ligne else 1
    if version >= VERSION_SCHEMA:
        return
    with transaction(conn):
        if version < 2 and "prix_achat_ml" in _colonnes(conn, "alcools"):
            conn.execute("ALTER TABLE alcools RENAME COLUMN prix_achat_ml TO prix_achat_litre")
            conn.execute("ALTER TABLE alcools RENAME COLUMN prix_vente_ml TO prix_vente_litre")
            conn.execute("UPDATE alcools SET prix_achat_litre = prix_achat_litre * 1000, "
                         "prix_vente_litre = prix_vente_litre * 1000")
        if version < 3 and "prix_achat_ml" in _colonnes(conn, "parfums"):
            conn.execute("ALTER TABLE parfums RENAME COLUMN prix_achat_ml TO prix_achat_100ml")
            conn.execute("ALTER TABLE parfums RENAME COLUMN prix_vente_10ml TO prix_vente_100ml")
        conn.execute("INSERT OR REPLACE INTO parametres (cle, valeur) VALUES ('schema_version', ?)",
                     (str(VERSION_SCHEMA),))


# --------------------------------------------------------------------------
# Intégrité et sauvegardes
# --------------------------------------------------------------------------
def verifier_integrite(chemin: Path) -> bool:
    """True si le fichier est une base SQLite saine."""
    try:
        conn = sqlite3.connect(str(chemin))
        try:
            resultat = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(resultat) and resultat[0] == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def sauvegarder(conn: sqlite3.Connection, etiquette: str = "auto") -> Path:
    """Crée une copie cohérente de la base (API backup de SQLite).

    Conserve uniquement les NB_SAUVEGARDES_MAX copies les plus récentes.
    """
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = dossier_sauvegardes() / f"parfumerie_{etiquette}_{horodatage}.db"
    copie = sqlite3.connect(str(destination))
    try:
        conn.backup(copie)
    finally:
        copie.close()
    _purger_anciennes_sauvegardes()
    return destination


def _purger_anciennes_sauvegardes() -> None:
    fichiers = sorted(dossier_sauvegardes().glob("parfumerie_*.db"))
    for ancien in fichiers[:-NB_SAUVEGARDES_MAX]:
        try:
            ancien.unlink()
        except OSError:
            pass  # pas bloquant


def derniere_sauvegarde_saine() -> Optional[Path]:
    """Retourne la sauvegarde la plus récente qui passe le contrôle d'intégrité."""
    for fichier in sorted(dossier_sauvegardes().glob("parfumerie_*.db"), reverse=True):
        if verifier_integrite(fichier):
            return fichier
    return None


# --------------------------------------------------------------------------
# Ouverture sécurisée (point d'entrée de l'application)
# --------------------------------------------------------------------------
@dataclass
class ResultatOuverture:
    """Résultat de l'ouverture de la base, avec un message pour l'utilisateur."""

    connexion: sqlite3.Connection
    message: Optional[str] = None   # None = tout va bien
    restauree: bool = False         # True si restaurée depuis une sauvegarde
    reinitialisee: bool = False     # True si base neuve créée après corruption


def ouvrir_base() -> ResultatOuverture:
    """Ouvre la base en la protégeant contre la corruption.

    1. Fichier absent        -> création d'une base neuve.
    2. Fichier sain          -> sauvegarde auto puis ouverture.
    3. Fichier corrompu      -> mis de côté (jamais supprimé), puis
                                restauration de la dernière sauvegarde saine,
                                ou base neuve en dernier recours.
    """
    chemin = chemin_base()

    if not chemin.exists():
        conn = creer_connexion(chemin)
        creer_schema(conn)
        return ResultatOuverture(conn)

    if verifier_integrite(chemin):
        conn = creer_connexion(chemin)
        creer_schema(conn)  # ajoute d'éventuelles tables manquantes
        try:
            sauvegarder(conn, "demarrage")
        except (sqlite3.Error, OSError):
            pass  # une sauvegarde ratée ne doit pas empêcher de travailler
        return ResultatOuverture(conn)

    # --- Base corrompue : on la garde de côté pour analyse ---
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    corrompue = chemin.with_name(f"parfumerie_corrompue_{horodatage}.db")
    for suffixe in ("", "-wal", "-shm"):
        source = Path(str(chemin) + suffixe)
        if source.exists():
            shutil.move(str(source), str(corrompue) + suffixe)

    sauvegarde = derniere_sauvegarde_saine()
    if sauvegarde is not None:
        shutil.copy2(sauvegarde, chemin)
        conn = creer_connexion(chemin)
        creer_schema(conn)
        return ResultatOuverture(
            conn,
            message=(
                "La base de données était endommagée. Elle a été restaurée "
                f"depuis la sauvegarde du {sauvegarde.stem[-22:-7]}. "
                "Les opérations récentes ont pu être perdues."
            ),
            restauree=True,
        )

    conn = creer_connexion(chemin)
    creer_schema(conn)
    return ResultatOuverture(
        conn,
        message=(
            "La base de données était endommagée et aucune sauvegarde n'était "
            "disponible. Une base vide a été créée. L'ancien fichier est "
            f"conservé : {corrompue.name}"
        ),
        reinitialisee=True,
    )
