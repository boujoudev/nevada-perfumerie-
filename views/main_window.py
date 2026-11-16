"""Fenêtre principale : menu latéral + sections."""

from __future__ import annotations

import logging
import sqlite3
import sys
from typing import Dict, Optional

import customtkinter as ctk

from database import connection as base
from services import auth_service, produits_service
from utils.ressources import charger_logo, chemin_ressource
from views.creation_view import CreationView
from views.dialogues import DialogueConnexion
from views.logs_view import LogsView
from views.parametres_view import ParametresView
from views.stock_view import StockView
from views.style import BLEU, VERT_CLAIR, appliquer_style_tableaux
from views.vente_view import VenteView
from views.widgets import afficher_avertissement, afficher_erreur, afficher_info

journal = logging.getLogger(__name__)
INTERVALLE_SAUVEGARDE_MS = 30 * 60 * 1000


class FenetrePrincipale(ctk.CTk):
    SECTIONS = [("Création", "➕  Création"), ("Stock", "📦  Stock"), ("Vente", "🛒  Vente"),
                ("Logs", "📊  Logs & Stats"), ("Paramètres", "⚙  Paramètres")]

    def __init__(self, conn: sqlite3.Connection, message_demarrage: Optional[str] = None):
        super().__init__()
        self.conn = conn
        self.message_demarrage = message_demarrage
        self.title("Nevada Parfumerie — Gestion")
        # La fenêtre s'adapte à l'écran (petits portables) au lieu de dépasser
        largeur = min(1280, max(self.winfo_screenwidth() - 60, 900))
        hauteur = min(760, max(self.winfo_screenheight() - 140, 560))
        self.geometry(f"{largeur}x{hauteur}+30+30")
        self.minsize(900, 560)
        self.withdraw()                                   # cachée jusqu'à la connexion
        self.report_callback_exception = self._erreur_inattendue
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        appliquer_style_tableaux()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        menu = ctk.CTkFrame(self, width=200, corner_radius=0)
        menu.grid(row=0, column=0, sticky="nsew")
        menu.grid_propagate(False)
        self.logo = charger_logo(165)                      # logo Nevada (garder la référence)
        if self.logo is not None:
            ctk.CTkLabel(menu, text="", image=self.logo).pack(pady=(18, 14), padx=10)
        else:
            ctk.CTkLabel(menu, text="NEVADA", font=ctk.CTkFont(size=22, weight="bold")
                         ).pack(pady=(25, 25), padx=15)
        self._appliquer_icone()
        self.boutons: Dict[str, ctk.CTkButton] = {}
        for nom, libelle in self.SECTIONS:
            bouton = ctk.CTkButton(menu, text=libelle, anchor="w", height=42, fg_color="transparent",
                                   text_color=("gray10", "gray10"), hover_color=VERT_CLAIR,
                                   command=lambda n=nom: self.afficher(n))
            bouton.pack(fill="x", padx=10, pady=3)
            self.boutons[nom] = bouton

        contenu = ctk.CTkFrame(self, fg_color="transparent")
        contenu.grid(row=0, column=1, sticky="nsew")
        contenu.grid_columnconfigure(0, weight=1)
        contenu.grid_rowconfigure(0, weight=1)
        self.vues = {
            "Création": CreationView(contenu, conn), "Stock": StockView(contenu, conn),
            "Vente": VenteView(contenu, conn), "Logs": LogsView(contenu, conn),
            "Paramètres": ParametresView(contenu, conn),
        }
        self.after(100, self._demarrer)

    def _appliquer_icone(self) -> None:
        """Icône de la fenêtre / barre des tâches (sans importance si elle échoue)."""
        try:
            if sys.platform.startswith("win"):
                ico = str(chemin_ressource("assets/icone.ico"))
                # CustomTkinter remet son icône par défaut ~200 ms après l'ouverture : on la remplace après
                self.after(300, lambda: self.iconbitmap(ico))
            else:
                import tkinter
                self._icone = tkinter.PhotoImage(file=str(chemin_ressource("assets/icone.png")))
                self.iconphoto(True, self._icone)
        except Exception:  # noqa: BLE001
            journal.warning("Icône de fenêtre non appliquée", exc_info=True)

    # ------------------------------------------------------------- démarrage
    def _demarrer(self) -> None:
        if auth_service.a_mot_de_passe(self.conn):
            dialogue = DialogueConnexion(self, self.conn)
            self.wait_window(dialogue)
            if not dialogue.ok:
                self._fermer(sauvegarder=False)
                return
        self.deiconify()
        self.afficher("Stock")
        if self.message_demarrage:
            afficher_avertissement(self, self.message_demarrage)
        self.after(600, self._notifier_stock_bas)
        self.after(INTERVALLE_SAUVEGARDE_MS, self._sauvegarde_periodique)

    def _notifier_stock_bas(self) -> None:
        try:
            alertes = produits_service.produits_en_alerte(self.conn)
        except sqlite3.Error:
            journal.exception("Alertes stock")
            return
        if alertes:
            lignes = [f"• {a['code']} {a['nom']} : {a['stock_txt']}" for a in alertes[:12]]
            if len(alertes) > 12:
                lignes.append(f"… et {len(alertes) - 12} autre(s)")
            afficher_avertissement(self, "Stock bas :\n\n" + "\n".join(lignes))

    # ------------------------------------------------------------ navigation
    def afficher(self, nom: str) -> None:
        for cle, bouton in self.boutons.items():
            actif = cle == nom
            bouton.configure(fg_color=BLEU if actif else "transparent",
                             text_color=("white", "white") if actif else ("gray10", "gray10"))
        for cle, autre in self.vues.items():
            if cle != nom:
                autre.grid_remove()
        vue = self.vues[nom]
        vue.grid(row=0, column=0, sticky="nsew")
        try:
            vue.rafraichir()
        except sqlite3.Error as erreur:
            journal.exception("Rafraîchissement %s", nom)
            afficher_erreur(self, f"Erreur de base de données : {erreur}")

    # ---------------------------------------------------------------- vie
    def _sauvegarde_periodique(self) -> None:
        try:
            base.sauvegarder(self.conn, "auto")
        except (sqlite3.Error, OSError):
            journal.exception("Sauvegarde périodique")
        self.after(INTERVALLE_SAUVEGARDE_MS, self._sauvegarde_periodique)

    def _fermer(self, sauvegarder: bool = True) -> None:
        if sauvegarder:
            try:
                base.sauvegarder(self.conn, "fermeture")
            except (sqlite3.Error, OSError):
                journal.exception("Sauvegarde à la fermeture")
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
        self.destroy()

    def _erreur_inattendue(self, type_erreur, valeur, trace) -> None:
        """Évite le crash : l'erreur est journalisée et l'utilisateur prévenu."""
        journal.error("Erreur inattendue", exc_info=(type_erreur, valeur, trace))
        try:
            afficher_erreur(self, "Une erreur inattendue s'est produite.\nVos données ne sont pas "
                                  f"affectées.\n\nDétail : {valeur}")
        except Exception:
            pass
