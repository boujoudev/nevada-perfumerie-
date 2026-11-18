"""Fenêtres de dialogue : modification, réapprovisionnement, détails, client, connexion."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Optional

import customtkinter as ctk

from models.catalogue import CATALOGUE
from repositories import produits_repo
from services import clients_service, produits_service
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_nombre
from views.widgets import (FenetreModale, FormulaireProduit, afficher_avertissement,
                           afficher_erreur, afficher_info, ligne_boutons)

journal = logging.getLogger(__name__)


def _erreur_base(parent, erreur: Exception) -> None:
    journal.exception("Erreur base de données")
    afficher_erreur(parent, f"Erreur de base de données : {erreur}")


class DialogueModifier(FenetreModale):
    """Modification d'un produit (ouverte par double-clic dans le stock)."""

    def __init__(self, master, conn: sqlite3.Connection, type_code: str, identifiant: int,
                 apres_enregistrement: Callable[[], None]):
        self.conn, self.type_code, self.identifiant = conn, type_code, identifiant
        self.apres = apres_enregistrement
        t = CATALOGUE[type_code]
        super().__init__(master, f"Modifier {t.libelle.lower()} "
                         f"{t.code_de(produits_repo.obtenir(conn, type_code, identifiant) or {'id': identifiant})}",
                         560, 130 + 46 * (len(t.champs) + 1))
        self.formulaire = FormulaireProduit(self, type_code)
        self.formulaire.pack(fill="x", padx=15, pady=(15, 5))
        produit = produits_repo.obtenir(conn, type_code, identifiant)
        if produit is not None:
            self.formulaire.remplir(produit)
        ligne_boutons(self, [("Enregistrer", self._enregistrer, None),
                             ("Annuler", self.destroy, "#6b7280")]).pack(fill="x", padx=15, pady=15)

    def _enregistrer(self) -> None:
        try:
            resultat = produits_service.modifier_produit(
                self.conn, self.type_code, self.identifiant, self.formulaire.valeurs())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        for message in resultat["avertissements"]:
            afficher_avertissement(self, message)
        self.apres()
        self.destroy()


class DialogueReappro(FenetreModale):
    """Ajout de stock (réapprovisionnement)."""

    def __init__(self, master, conn: sqlite3.Connection, type_code: str, identifiant: int,
                 apres_enregistrement: Callable[[], None]):
        self.conn, self.type_code, self.identifiant = conn, type_code, identifiant
        self.apres = apres_enregistrement
        t = CATALOGUE[type_code]
        produit = produits_repo.obtenir(conn, type_code, identifiant)
        super().__init__(master, "Réapprovisionner", 440, 250)
        ctk.CTkLabel(self, text=f"{t.code_de(produit)} · {produit['nom']}",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(20, 4))
        ctk.CTkLabel(self, text=f"Stock actuel : {fmt_nombre(produit[t.colonne_stock])} {t.unite_stock}"
                     ).pack(pady=2)
        ctk.CTkLabel(self, text=f"Quantité à ajouter ({t.unite_stock}) :").pack(pady=(12, 2))
        self.entree = ctk.CTkEntry(self, width=200, justify="center")
        self.entree.pack()
        self.entree.bind("<Return>", lambda _e: self._valider())
        ligne_boutons(self, [("Ajouter", self._valider, None),
                             ("Annuler", self.destroy, "#6b7280")]).pack(fill="x", padx=15, pady=20)
        self.after(200, self.entree.focus_set)

    def _valider(self) -> None:
        try:
            produits_service.reapprovisionner(self.conn, self.type_code, self.identifiant,
                                              self.entree.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        self.apres()
        self.destroy()


class DialogueDetails(FenetreModale):
    """Toutes les informations d'un produit (lecture seule)."""

    def __init__(self, master, conn: sqlite3.Connection, type_code: str, identifiant: int):
        t = CATALOGUE[type_code]
        produit = produits_repo.obtenir(conn, type_code, identifiant)
        super().__init__(master, f"Détails — {t.code_de(produit or {'id': identifiant})}", 520, 150 + 34 * len(t.champs))
        texte = ctk.CTkTextbox(self, width=480, height=60 + 34 * len(t.champs))
        texte.pack(padx=15, pady=15, fill="both", expand=True)
        lignes = [f"Type : {t.libelle}", f"ID : {t.code_de(produit or {'id': identifiant})}"]
        if produit is not None:
            for champ in t.champs:
                if champ.cle == "code":
                    continue
                valeur = produit[champ.cle]
                lignes.append(f"{champ.libelle} : "
                              f"{valeur if champ.genre == 'texte' else fmt_nombre(valeur)}")
            if type_code == "FLACON":
                lignes.append(f"Alcool par flacon (automatique) : {fmt_nombre(produit['qnt_alcool_necessaire'])} ml")
            lignes.append(f"Créé le : {fmt_datetime(produit['date_creation'])}")
        texte.insert("1.0", "\n".join(lignes))
        texte.configure(state="disabled")
        ligne_boutons(self, [("Fermer", self.destroy, None)]).pack(fill="x", padx=15, pady=(0, 15))


class DialogueClient(FenetreModale):
    """Création rapide d'un client depuis l'écran de vente."""

    def __init__(self, master, conn: sqlite3.Connection, apres_creation: Callable[[int], None]):
        self.conn, self.apres = conn, apres_creation
        super().__init__(master, "Nouveau client", 420, 270)
        ctk.CTkLabel(self, text="Nom du client").pack(pady=(20, 2))
        self.nom = ctk.CTkEntry(self, width=260)
        self.nom.pack()
        ctk.CTkLabel(self, text="Téléphone (facultatif)").pack(pady=(12, 2))
        self.telephone = ctk.CTkEntry(self, width=260)
        self.telephone.pack()
        ligne_boutons(self, [("Créer", self._creer, None),
                             ("Annuler", self.destroy, "#6b7280")]).pack(fill="x", padx=15, pady=20)
        self.after(200, self.nom.focus_set)

    def _creer(self) -> None:
        try:
            identifiant = clients_service.creer_client(self.conn, self.nom.get(), self.telephone.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        self.apres(identifiant)
        self.destroy()
