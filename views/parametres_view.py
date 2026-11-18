"""Paramètres du module parfum : sauvegardes et dossier des données."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import sqlite3

import customtkinter as ctk

from database import connection as base
from views.widgets import afficher_erreur, afficher_info

journal = logging.getLogger(__name__)


class ParametresView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection, ctx=None):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        ctk.CTkLabel(self, text="Paramètres", font=ctk.CTkFont(size=24, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(15, 10))
        cadre = ctk.CTkFrame(self)
        cadre.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(cadre, text="Données et sauvegardes", font=ctk.CTkFont(size=16, weight="bold")
                     ).pack(anchor="w", padx=15, pady=(12, 2))
        ctk.CTkLabel(cadre, text=("Une sauvegarde est créée automatiquement au démarrage, à la fermeture "
                                  "et toutes les 30 minutes (les 10 dernières sont conservées). Les mots de passe "
                                  "et les utilisateurs se gèrent depuis la page d'accueil."),
                     text_color="#6b7280", wraplength=700, justify="left").pack(anchor="w", padx=15)
        ctk.CTkLabel(cadre, text=f"Dossier des données : {base.dossier_donnees()}",
                     wraplength=700, justify="left").pack(anchor="w", padx=15, pady=6)
        boutons = ctk.CTkFrame(cadre, fg_color="transparent")
        boutons.pack(anchor="w", padx=15, pady=(4, 14))
        ctk.CTkButton(boutons, text="Sauvegarder maintenant", width=190, command=self._sauvegarder).pack(side="left", padx=(0, 8))
        ctk.CTkButton(boutons, text="Ouvrir le dossier", width=150, fg_color="#6b7280",
                      command=self._ouvrir_dossier).pack(side="left")

    def rafraichir(self) -> None:
        pass

    def _sauvegarder(self) -> None:
        try:
            chemin = base.sauvegarder(self.conn, "manuelle")
        except (sqlite3.Error, OSError) as erreur:
            journal.exception("Sauvegarde manuelle")
            afficher_erreur(self, f"La sauvegarde a échoué : {erreur}")
            return
        afficher_info(self, f"Sauvegarde créée :\n{chemin}", "Sauvegarde")

    def _ouvrir_dossier(self) -> None:
        dossier = str(base.dossier_donnees())
        try:
            if sys.platform.startswith("win"):
                os.startfile(dossier)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", dossier])
            else:
                subprocess.Popen(["xdg-open", dossier])
        except OSError as erreur:
            afficher_erreur(self, f"Impossible d'ouvrir le dossier : {erreur}")
