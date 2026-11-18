"""Point d'entrée : python main.py"""

from __future__ import annotations

import logging
import sys
import traceback


def configurer_journal() -> None:
    """Écrit les erreurs dans application.log (dossier des données)."""
    from database.connection import dossier_donnees
    logging.basicConfig(
        filename=str(dossier_donnees() / "application.log"), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s", encoding="utf-8")


def afficher_erreur_fatale(texte: str) -> None:
    """Dernier recours : message à l'écran même si l'interface n'a pas démarré."""
    try:
        import tkinter
        from tkinter import messagebox
        racine = tkinter.Tk()
        racine.withdraw()
        messagebox.showerror("Gestion Parfumerie", texte)
        racine.destroy()
    except Exception:
        print(texte, file=sys.stderr)


def main() -> int:
    try:
        configurer_journal()
        import customtkinter as ctk
        from database.connection import ouvrir_base
        from views.application import Application
        from views.style import appliquer_theme_nevada

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        appliquer_theme_nevada()          # couleurs du logo Nevada
        ouverture = ouvrir_base()
        Application(ouverture.connexion, ouverture.message).mainloop()
        return 0
    except Exception as erreur:  # noqa: BLE001 - dernier filet de sécurité
        logging.getLogger(__name__).exception("Erreur fatale au démarrage")
        afficher_erreur_fatale(
            f"L'application n'a pas pu démarrer :\n\n{erreur}\n\n"
            "Détails dans le fichier application.log (dossier des données).\n\n"
            + "".join(traceback.format_exception_only(type(erreur), erreur)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
