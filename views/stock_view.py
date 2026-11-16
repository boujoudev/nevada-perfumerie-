"""Section STOCK : recherche, modification, suppression, réapprovisionnement."""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional, Tuple

import customtkinter as ctk

from models.catalogue import CATALOGUE
from services import produits_service
from utils.erreurs import ErreurMetier
from views.dialogues import DialogueDetails, DialogueModifier, DialogueReappro
from views.widgets import Tableau, afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)

FILTRES_TYPE = {"Tous": None, "Flacon": "FLACON", "Parfum": "PARFUM", "Alcool": "ALCOOL"}

COLONNES = [
    ("id", "ID", 70, "center"), ("nom", "Nom", 220, "w"), ("type", "Type", 90, "center"),
    ("achat", "Prix d'achat", 150, "e"),
    ("stock", "Stock", 110, "e"), ("details", "Détails spécifiques", 470, "w"),
]


class StockView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text="Stock", font=ctk.CTkFont(size=24, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        barre = ctk.CTkFrame(self, fg_color="transparent")
        barre.grid(row=1, column=0, sticky="ew", padx=20, pady=5)
        self.recherche = ctk.CTkEntry(barre, width=260, placeholder_text="Rechercher…")
        self.recherche.pack(side="left", padx=(0, 8))
        self.recherche.bind("<KeyRelease>", lambda _e: self.rafraichir())
        ctk.CTkLabel(barre, text="par").pack(side="left", padx=4)
        self.menu_par = ctk.CTkOptionMenu(barre, values=["Nom", "ID"], width=80,
                                          command=lambda _v: self.rafraichir())
        self.menu_par.pack(side="left", padx=4)
        ctk.CTkLabel(barre, text="Type").pack(side="left", padx=(12, 4))
        self.menu_type = ctk.CTkOptionMenu(barre, values=list(FILTRES_TYPE), width=100,
                                           command=lambda _v: self.rafraichir())
        self.menu_type.pack(side="left", padx=4)

        self.tableau = Tableau(self, COLONNES)
        self.tableau.grid(row=2, column=0, sticky="nsew", padx=20, pady=8)
        self.tableau.lier_double_clic(self._modifier)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 10))
        ctk.CTkButton(actions, text="+ Ajouter du stock", width=150, command=self._reappro).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Détails", width=100, command=self._details).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Modifier", width=100, command=self._modifier).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Supprimer", width=100, fg_color="#dc2626", hover_color="#b91c1c",
                      command=self._supprimer).pack(side="left", padx=4)
        self.resume = ctk.CTkLabel(actions, text="", text_color="#6b7280")
        self.resume.pack(side="right")

    # ------------------------------------------------------------ affichage
    def rafraichir(self) -> None:
        try:
            lignes = produits_service.rechercher(
                self.conn, self.recherche.get(), self.menu_par.get(),
                FILTRES_TYPE.get(self.menu_type.get()))
        except sqlite3.Error as erreur:
            journal.exception("Recherche stock")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.tableau.vider()
        bas = 0
        for l in lignes:
            if l["bas"]:
                bas += 1
            self.tableau.ajouter(
                (l["code"], l["nom"], l["type_libelle"], l["prix_achat_txt"],
                 l["stock_txt"], l["details"]),
                iid=f"{l['type']}:{l['id']}", tags=("bas",) if l["bas"] else ())
        self.resume.configure(
            text=f"{len(lignes)} produit(s)" + (f" — {bas} en stock bas (rouge)" if bas else ""))

    # -------------------------------------------------------------- actions
    def _selection(self) -> Optional[Tuple[str, int]]:
        iid = self.tableau.selection()
        if not iid:
            afficher_info(self, "Sélectionnez d'abord un produit dans le tableau.")
            return None
        type_code, identifiant = iid.split(":")
        return type_code, int(identifiant)

    def _modifier(self) -> None:
        choix = self._selection()
        if choix:
            DialogueModifier(self.winfo_toplevel(), self.conn, *choix, self.rafraichir)

    def _reappro(self) -> None:
        choix = self._selection()
        if choix:
            DialogueReappro(self.winfo_toplevel(), self.conn, *choix, self.rafraichir)

    def _details(self) -> None:
        choix = self._selection()
        if choix:
            DialogueDetails(self.winfo_toplevel(), self.conn, *choix)

    def _supprimer(self) -> None:
        choix = self._selection()
        if not choix:
            return
        type_code, identifiant = choix
        nom = self.tableau.arbre.item(self.tableau.selection(), "values")[1]
        if not confirmer(self, f"Supprimer « {nom} » ?\n\nIl disparaîtra du stock "
                               "(l'historique des ventes est conservé)."):
            return
        try:
            produits_service.supprimer_produit(self.conn, type_code, identifiant)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
        except sqlite3.Error as erreur:
            journal.exception("Suppression produit")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
        self.rafraichir()
