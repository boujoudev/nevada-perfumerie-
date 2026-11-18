"""Écran de connexion, et création du premier administrateur au tout premier lancement."""

from __future__ import annotations

import sqlite3

import customtkinter as ctk

from services import utilisateurs_service
from utils.erreurs import ErreurMetier
from utils.ressources import charger_logo
from views.style import ROUGE
from views.widgets import afficher_erreur


class LoginView(ctk.CTkFrame):
    def __init__(self, master, app, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.app, self.conn = app, conn
        carte = ctk.CTkFrame(self)
        carte.place(relx=0.5, rely=0.5, anchor="center")
        self.logo = charger_logo(240)
        if self.logo is not None:
            ctk.CTkLabel(carte, text="", image=self.logo).pack(padx=60, pady=(30, 10))
        else:
            ctk.CTkLabel(carte, text="NEVADA", font=ctk.CTkFont(size=28, weight="bold")).pack(padx=60, pady=(30, 10))
        ctk.CTkLabel(carte, text="Connexion", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(4, 8))
        self.identifiant = ctk.CTkEntry(carte, width=260, height=40, placeholder_text="Identifiant")
        self.identifiant.pack(pady=5)
        self.mot_de_passe = ctk.CTkEntry(carte, width=260, height=40, show="•", placeholder_text="Mot de passe")
        self.mot_de_passe.pack(pady=5)
        self.identifiant.bind("<Return>", lambda _e: self.mot_de_passe.focus_set())
        self.mot_de_passe.bind("<Return>", lambda _e: self._valider())
        self.message = ctk.CTkLabel(carte, text="", text_color=ROUGE)
        self.message.pack()
        ctk.CTkButton(carte, text="Se connecter", width=260, height=42, command=self._valider).pack(pady=(8, 8))
        ctk.CTkButton(carte, text="Quitter", width=260, fg_color="#6b7280", command=app.quitter).pack(pady=(0, 30))

    def rafraichir(self) -> None:
        self.after(200, self.identifiant.focus_set)

    def _valider(self) -> None:
        utilisateur = utilisateurs_service.authentifier(self.conn, self.identifiant.get(), self.mot_de_passe.get())
        if utilisateur is None:
            self.message.configure(text="Identifiant ou mot de passe incorrect")
            self.mot_de_passe.delete(0, "end")
            return
        self.app.connecter(utilisateur)


class PremierDemarrageView(ctk.CTkFrame):
    """Aucun utilisateur n'existe encore : on crée le premier administrateur."""

    def __init__(self, master, app, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.app, self.conn = app, conn
        carte = ctk.CTkFrame(self)
        carte.place(relx=0.5, rely=0.5, anchor="center")
        self.logo = charger_logo(220)
        if self.logo is not None:
            ctk.CTkLabel(carte, text="", image=self.logo).pack(padx=60, pady=(26, 8))
        ctk.CTkLabel(carte, text="Bienvenue !", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(4, 2))
        ctk.CTkLabel(carte, text="Créez le compte administrateur (vous pourrez ajouter\nles employés ensuite).",
                     justify="center", text_color="#6b7280").pack(pady=(0, 8))
        self.nom = ctk.CTkEntry(carte, width=280, height=38, placeholder_text="Votre nom")
        self.nom.pack(pady=4)
        self.identifiant = ctk.CTkEntry(carte, width=280, height=38, placeholder_text="Identifiant de connexion")
        self.identifiant.pack(pady=4)
        self.identifiant.insert(0, "admin")
        self.mot_de_passe = ctk.CTkEntry(carte, width=280, height=38, show="•", placeholder_text="Mot de passe (4 caractères min.)")
        self.mot_de_passe.pack(pady=4)
        self.confirmation = ctk.CTkEntry(carte, width=280, height=38, show="•", placeholder_text="Confirmer le mot de passe")
        self.confirmation.pack(pady=4)
        self.confirmation.bind("<Return>", lambda _e: self._creer())
        ctk.CTkButton(carte, text="Créer le compte et commencer", width=280, height=42,
                      command=self._creer).pack(pady=(12, 30))

    def rafraichir(self) -> None:
        self.after(200, self.nom.focus_set)

    def _creer(self) -> None:
        try:
            utilisateurs_service.creer_utilisateur(self.conn, self.nom.get(), self.identifiant.get(),
                                                   self.mot_de_passe.get(), self.confirmation.get(), "ADMIN")
            utilisateur = utilisateurs_service.authentifier(self.conn, self.identifiant.get(), self.mot_de_passe.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        self.app.connecter(utilisateur)
