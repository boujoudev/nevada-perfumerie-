"""Paramètres : mot de passe, sauvegardes, dossier des données."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import sqlite3

import customtkinter as ctk

from database import connection as base
from services import auth_service
from utils.erreurs import ErreurMetier
from views.widgets import afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)


class ParametresView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        ctk.CTkLabel(self, text="Paramètres", font=ctk.CTkFont(size=24, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(15, 10))

        # --- mot de passe
        cadre = ctk.CTkFrame(self)
        cadre.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(cadre, text="Mot de passe de l'application", font=ctk.CTkFont(size=16, weight="bold")
                     ).pack(anchor="w", padx=15, pady=(12, 2))
        self.lbl_etat = ctk.CTkLabel(cadre, text="", text_color="#6b7280")
        self.lbl_etat.pack(anchor="w", padx=15)
        self.nouveau = ctk.CTkEntry(cadre, show="•", width=260, placeholder_text="Nouveau mot de passe")
        self.nouveau.pack(anchor="w", padx=15, pady=(10, 4))
        self.confirmation = ctk.CTkEntry(cadre, show="•", width=260, placeholder_text="Confirmer")
        self.confirmation.pack(anchor="w", padx=15, pady=4)
        boutons = ctk.CTkFrame(cadre, fg_color="transparent")
        boutons.pack(anchor="w", padx=15, pady=(6, 14))
        ctk.CTkButton(boutons, text="Définir / changer", width=150, command=self._definir).pack(side="left", padx=(0, 8))
        ctk.CTkButton(boutons, text="Supprimer le mot de passe", width=200, fg_color="#dc2626",
                      hover_color="#b91c1c", command=self._supprimer).pack(side="left")

        # --- sauvegardes
        cadre2 = ctk.CTkFrame(self)
        cadre2.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(cadre2, text="Données et sauvegardes", font=ctk.CTkFont(size=16, weight="bold")
                     ).pack(anchor="w", padx=15, pady=(12, 2))
        ctk.CTkLabel(cadre2, text=("Une sauvegarde est créée automatiquement au démarrage, à la fermeture "
                                   "et toutes les 30 minutes (les 10 dernières sont conservées)."),
                     text_color="#6b7280", wraplength=700, justify="left").pack(anchor="w", padx=15)
        ctk.CTkLabel(cadre2, text=f"Dossier des données : {base.dossier_donnees()}",
                     wraplength=700, justify="left").pack(anchor="w", padx=15, pady=6)
        boutons2 = ctk.CTkFrame(cadre2, fg_color="transparent")
        boutons2.pack(anchor="w", padx=15, pady=(4, 14))
        ctk.CTkButton(boutons2, text="Sauvegarder maintenant", width=190, command=self._sauvegarder).pack(side="left", padx=(0, 8))
        ctk.CTkButton(boutons2, text="Ouvrir le dossier", width=150, fg_color="#6b7280",
                      command=self._ouvrir_dossier).pack(side="left")

    def rafraichir(self) -> None:
        self.lbl_etat.configure(text="Un mot de passe est demandé au démarrage."
                                if auth_service.a_mot_de_passe(self.conn)
                                else "Aucun mot de passe : l'application s'ouvre directement.")

    def _definir(self) -> None:
        try:
            auth_service.definir_mot_de_passe(self.conn, self.nouveau.get(), self.confirmation.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        self.nouveau.delete(0, "end")
        self.confirmation.delete(0, "end")
        afficher_info(self, "Mot de passe enregistré. Notez-le bien : il ne peut pas être récupéré.")
        self.rafraichir()

    def _supprimer(self) -> None:
        if not auth_service.a_mot_de_passe(self.conn):
            afficher_info(self, "Aucun mot de passe n'est défini.")
            return
        if confirmer(self, "Supprimer le mot de passe ? L'application s'ouvrira sans protection."):
            auth_service.supprimer_mot_de_passe(self.conn)
            self.rafraichir()

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
