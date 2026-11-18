"""Réinitialise le mot de passe d'un utilisateur (ex. administrateur qui a oublié le sien).

Les mots de passe sont stockés chiffrés : on ne peut pas les relire, seulement en définir un nouveau.
À lancer sur l'ordinateur où se trouvent les données, APPLICATION FERMÉE :

    python outils/reinitialiser_mot_de_passe.py                  (mode guidé)
    python outils/reinitialiser_mot_de_passe.py --db chemin.db   (autre fichier de base)

Une copie de sécurité de la base est faite avant toute modification.
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.connection import chemin_base  # noqa: E402
from utils.erreurs import ErreurMetier  # noqa: E402
from utils.securite import hacher  # noqa: E402

LONGUEUR_MIN = 4


def lister_utilisateurs(chemin_db: Path) -> list:
    conn = sqlite3.connect(str(chemin_db))
    try:
        return conn.execute("SELECT nom, identifiant, role, actif FROM utilisateurs ORDER BY role, nom").fetchall()
    except sqlite3.DatabaseError as erreur:
        raise ErreurMetier(f"Base de données illisible : {erreur}") from None
    finally:
        conn.close()


def reinitialiser(chemin_db: Path, identifiant: str, nouveau_mot_de_passe: str) -> Path:
    """Change le mot de passe de `identifiant`. Retourne le chemin de la copie de sécurité."""
    chemin_db = Path(chemin_db)
    if not chemin_db.is_file():
        raise ErreurMetier(f"Fichier introuvable : {chemin_db}")
    if len(nouveau_mot_de_passe or "") < LONGUEUR_MIN:
        raise ErreurMetier(f"Le mot de passe doit contenir au moins {LONGUEUR_MIN} caractères.")
    copie = chemin_db.with_name(f"{chemin_db.stem}_avant_reinit_{datetime.now():%Y%m%d_%H%M%S}.db")
    source = sqlite3.connect(str(chemin_db))
    try:
        utilisateur = source.execute("SELECT id FROM utilisateurs WHERE identifiant = ? COLLATE NOCASE",
                                     ((identifiant or "").strip(),)).fetchone()
        if utilisateur is None:
            connus = ", ".join(r[0] for r in source.execute("SELECT identifiant FROM utilisateurs"))
            raise ErreurMetier(f"Identifiant « {identifiant} » inconnu. Identifiants existants : {connus or '(aucun)'}")
        sauvegarde = sqlite3.connect(str(copie))                       # copie de sécurité cohérente
        try:
            source.backup(sauvegarde)
        finally:
            sauvegarde.close()
        empreinte, sel = hacher(nouveau_mot_de_passe)
        source.execute("UPDATE utilisateurs SET mot_de_passe_hash = ?, mot_de_passe_sel = ? WHERE id = ?",
                       (empreinte, sel, utilisateur[0]))
        source.commit()
    except sqlite3.DatabaseError as erreur:
        raise ErreurMetier(f"Impossible de modifier la base : {erreur}") from None
    finally:
        source.close()
    return copie


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Réinitialise un mot de passe de l'application.")
    analyseur.add_argument("--db", help="chemin du fichier parfumerie.db (par défaut : le dossier de données)")
    args = analyseur.parse_args()
    chemin = Path(args.db) if args.db else chemin_base()
    print(f"Base de données : {chemin}")
    print("⚠ Fermez l'application avant de continuer.\n")
    try:
        utilisateurs = lister_utilisateurs(chemin)
        if not utilisateurs:
            print("Aucun utilisateur : lancez simplement l'application, elle proposera de créer l'administrateur.")
            return 0
        print("Utilisateurs :")
        for nom, identifiant, role, actif in utilisateurs:
            print(f"  - {identifiant:<15} {nom:<20} {role}{'' if actif else '  (désactivé)'}")
        defaut = next((u[1] for u in utilisateurs if u[2] == "ADMIN"), utilisateurs[0][1])
        identifiant = input(f"\nIdentifiant à réinitialiser [{defaut}] : ").strip() or defaut
        mot_de_passe = getpass.getpass("Nouveau mot de passe : ")
        if mot_de_passe != getpass.getpass("Confirmer le mot de passe : "):
            print("Les deux mots de passe ne correspondent pas.")
            return 1
        copie = reinitialiser(chemin, identifiant, mot_de_passe)
    except ErreurMetier as erreur:
        print(f"Erreur : {erreur}")
        return 1
    print(f"\n✔ Mot de passe de « {identifiant} » modifié.\n  Copie de sécurité : {copie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
