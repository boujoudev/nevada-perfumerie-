"""Section CRÉATION : ajouter flacons, parfums et alcools."""

from __future__ import annotations

import logging
import sqlite3

import customtkinter as ctk

from models.catalogue import CATALOGUE, ORDRE_TYPES
from services import produits_service
from utils.erreurs import ErreurMetier
from views.widgets import (FormulaireProduit, afficher_avertissement, afficher_erreur,
                           afficher_info)

journal = logging.getLogger(__name__)

AIDES = {
    "FLACON": "Saisissez le parfum : l'alcool est calculé automatiquement (capacité − parfum). Pas de prix de vente : il est fixé à chaque vente.",
    "PARFUM": "Le concentré est ajouté au stock (quantité en ml). Pas de prix de vente : il est fixé à chaque vente.",
    "ALCOOL": "Composant de base, utilisé pour remplir les flacons (quantités en ml).",
}


class CreationView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        self.formulaires = {}
        ctk.CTkLabel(self, text="Création de produits", font=ctk.CTkFont(size=24, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(15, 5))
        self.onglets = ctk.CTkTabview(self)
        self.onglets.pack(fill="both", expand=True, padx=20, pady=10)
        for code in ORDRE_TYPES:
            t = CATALOGUE[code]
            onglet = self.onglets.add(t.libelle)
            ctk.CTkLabel(onglet, text=AIDES[code], text_color="#6b7280").pack(anchor="w", padx=10, pady=(5, 0))
            formulaire = FormulaireProduit(onglet, code)
            formulaire.pack(fill="x", padx=10, pady=10)
            self.formulaires[code] = formulaire
            ctk.CTkButton(onglet, text=f"Créer le {t.libelle.lower()}", width=200,
                          command=lambda c=code: self._creer(c)).pack(anchor="w", padx=20, pady=10)

    def _creer(self, code: str) -> None:
        t = CATALOGUE[code]
        formulaire = self.formulaires[code]
        try:
            resultat = produits_service.creer_produit(self.conn, code, formulaire.valeurs())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Création produit")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        for message in resultat["avertissements"]:
            afficher_avertissement(self, message)
        afficher_info(self, f"{t.libelle} « {resultat['nom']} » créé ({resultat['code']}) et ajouté au stock.",
                      "Produit créé")
        formulaire.vider()

    def rafraichir(self) -> None:
        pass
