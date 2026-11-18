"""Base commune des deux modules (Parfum, Cosmétique) : menu latéral, vues, bouton « Accueil »."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

from services import utilisateurs_service
from utils.contexte import Contexte
from utils.ressources import charger_logo
from views.style import BLEU, VERT_CLAIR
from views.widgets import afficher_erreur, confirmer

journal = logging.getLogger(__name__)

# (clé, libellé du menu, permission nécessaire, fabrique(parent) -> vue)
Definition = Tuple[str, str, str, Callable]


class ModuleBase(ctk.CTkFrame):
    def __init__(self, master, app, ctx: Contexte, titre_module: str, definitions: List[Definition],
                 section_par_defaut: Tuple[str, ...]):
        super().__init__(master, fg_color="transparent")
        self.app, self.ctx = app, ctx
        self.section_courante: Optional[str] = None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        menu = ctk.CTkFrame(self, width=215, corner_radius=0)
        menu.grid(row=0, column=0, sticky="nsew")
        menu.grid_propagate(False)
        # Les éléments du bas sont placés en premier (pack side="bottom")
        ctk.CTkButton(menu, text="⬅  Retour à l'accueil", height=40, fg_color="#475569", hover_color="#334155",
                      command=self.retour_accueil).pack(side="bottom", fill="x", padx=10, pady=(4, 14))
        u = ctx.utilisateur
        ctk.CTkLabel(menu, text=f"👤 {u['nom']}\n{utilisateurs_service.LIBELLES_ROLE[u['role']]}",
                     text_color="#6b7280", justify="center").pack(side="bottom", pady=6)
        self.logo = charger_logo(150)
        if self.logo is not None:
            ctk.CTkLabel(menu, text="", image=self.logo).pack(pady=(14, 4), padx=10)
        ctk.CTkLabel(menu, text=titre_module, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(0, 12))

        contenu = ctk.CTkFrame(self, fg_color="transparent")
        contenu.grid(row=0, column=1, sticky="nsew")
        contenu.grid_columnconfigure(0, weight=1)
        contenu.grid_rowconfigure(0, weight=1)

        self.boutons: Dict[str, ctk.CTkButton] = {}
        self.vues: Dict[str, ctk.CTkFrame] = {}
        for cle, libelle, permission, fabrique in definitions:
            if not ctx.peut(permission):
                continue
            self.vues[cle] = fabrique(contenu)
            bouton = ctk.CTkButton(menu, text=libelle, anchor="w", height=42, fg_color="transparent",
                                   text_color=("gray10", "gray10"), hover_color=VERT_CLAIR,
                                   command=lambda c=cle: self.afficher(c))
            bouton.pack(fill="x", padx=10, pady=3)
            self.boutons[cle] = bouton
        self.section_par_defaut = next((c for c in section_par_defaut if c in self.vues), next(iter(self.vues), None))

    # ------------------------------------------------------------ navigation
    def afficher(self, cle: str) -> None:
        if cle not in self.vues:
            return
        self.section_courante = cle
        for nom, bouton in self.boutons.items():
            actif = nom == cle
            bouton.configure(fg_color=BLEU if actif else "transparent",
                             text_color=("white", "white") if actif else ("gray10", "gray10"))
        for nom, vue in self.vues.items():
            if nom != cle:
                vue.grid_remove()
        vue = self.vues[cle]
        vue.grid(row=0, column=0, sticky="nsew")
        try:
            vue.rafraichir()
        except sqlite3.Error as erreur:
            journal.exception("Rafraîchissement %s", cle)
            afficher_erreur(self, f"Erreur de base de données : {erreur}")

    def rafraichir_courant(self, section: Optional[str] = None) -> None:
        self.afficher(section if section in self.vues else (self.section_courante or self.section_par_defaut))

    # ------------------------------------------------------------------ sortie
    def panier_en_cours(self) -> bool:
        """Y a-t-il un panier ou un retour non terminé dans ce module ?"""
        return any(getattr(vue, "panier_en_cours", lambda: False)() for vue in self.vues.values())

    def retour_accueil(self) -> None:
        if self.panier_en_cours() and not confirmer(
                self, "Un panier (ou un retour) est en cours : il sera conservé tant que vous ne vous déconnectez "
                      "pas.\nRevenir à l'accueil ?"):
            return
        self.app.afficher_accueil()
