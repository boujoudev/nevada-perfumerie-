"""Base commune des deux modules (Parfum, Cosmétique) : menu latéral, vues, bouton « Accueil ».

Performance : les écrans sont construits À LA DEMANDE (à la première ouverture de la section) et ne sont
rechargés depuis la base que si des données ont changé depuis leur dernier affichage.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

from services import utilisateurs_service
from utils import perf
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
        self.titre = titre_module
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

        self.contenu = ctk.CTkFrame(self, fg_color="transparent")
        self.contenu.grid(row=0, column=1, sticky="nsew")
        self.contenu.grid_columnconfigure(0, weight=1)
        self.contenu.grid_rowconfigure(0, weight=1)

        self.boutons: Dict[str, ctk.CTkButton] = {}
        self.vues: Dict[str, ctk.CTkFrame] = {}                 # vues déjà construites
        self._fabriques: Dict[str, Callable] = {}
        self._version: Dict[str, int] = {}                      # état de la base au dernier rafraîchissement
        for cle, libelle, permission, fabrique in definitions:
            if not ctx.peut(permission):
                continue
            self._fabriques[cle] = fabrique
            bouton = ctk.CTkButton(menu, text=libelle, anchor="w", height=42, fg_color="transparent",
                                   text_color=("gray10", "gray10"), hover_color=VERT_CLAIR,
                                   command=lambda c=cle: self.afficher(c))
            bouton.pack(fill="x", padx=10, pady=3)
            self.boutons[cle] = bouton
        self.sections: Tuple[str, ...] = tuple(self._fabriques)  # sections autorisées pour cet utilisateur
        self.section_par_defaut = next((c for c in section_par_defaut if c in self._fabriques),
                                       next(iter(self._fabriques), None))

    # ------------------------------------------------------------ navigation
    def vue(self, cle: str):
        """La vue d'une section (construite à la première demande)."""
        if cle not in self.vues:
            self.vues[cle] = self._fabriques[cle](self.contenu)
        return self.vues[cle]

    def afficher(self, cle: str, forcer: bool = False) -> None:
        if cle not in self._fabriques:
            return
        chrono = perf.Chrono(f"{self.titre} › {cle}")
        self.section_courante = cle
        for nom, bouton in self.boutons.items():
            actif = nom == cle
            bouton.configure(fg_color=BLEU if actif else "transparent",
                             text_color=("white", "white") if actif else ("gray10", "gray10"))
        vue = self.vue(cle)                                       # construit à la première demande
        chrono.etape("construction")
        if perf.EMPILER:                                          # mode alternatif : écrans empilés
            vue.grid(row=0, column=0, sticky="nsew")
            vue.tkraise()
        else:
            for nom, autre in self.vues.items():
                if nom != cle:
                    autre.grid_remove()
            vue.grid(row=0, column=0, sticky="nsew")
        chrono.etape("affichage")
        # Rechargement depuis la base seulement si quelque chose a changé depuis le dernier affichage
        if forcer or self._version.get(cle) != self.ctx.conn.total_changes:
            try:
                vue.rafraichir()
            except sqlite3.Error as erreur:
                journal.exception("Rafraîchissement %s", cle)
                afficher_erreur(self, f"Erreur de base de données : {erreur}")
            self._version[cle] = self.ctx.conn.total_changes
        chrono.etape("données")
        hook = getattr(vue, "au_premier_plan", None)             # ex. remettre le curseur dans le champ de scan
        if callable(hook):
            hook()
        self.update_idletasks()                                   # force la mise en page : on mesure aussi le dessin
        chrono.etape("mise en page")
        chrono.fin()

    def rafraichir_courant(self, section: Optional[str] = None) -> None:
        self.afficher(section if section in self._fabriques else (self.section_courante or self.section_par_defaut))

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
