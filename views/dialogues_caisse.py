"""Boîtes de dialogue du module cosmétique : fiche produit, réception, inventaire, tickets en attente."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Optional

import customtkinter as ctk

from models.catalogue_caisse import CHAMPS_PRODUIT
from services import caisse_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_brut, fmt_datetime, fmt_prix
from views.widgets import (FenetreModale, FormulaireChamps, Tableau, afficher_avertissement, afficher_erreur,
                           afficher_info, confirmer, ligne_boutons)

journal = logging.getLogger(__name__)


def _erreur_base(parent, erreur: Exception) -> None:
    journal.exception("Erreur base de données (caisse)")
    afficher_erreur(parent, f"Erreur de base de données : {erreur}")


class DialogueProduitCaisse(FenetreModale):
    """Création (produit_id=None) ou modification d'un produit cosmétique."""

    def __init__(self, master, ctx: Contexte, produit_id: Optional[int], apres: Callable[[], None]):
        self.ctx, self.produit_id, self.apres = ctx, produit_id, apres
        titre = "Nouveau produit" if produit_id is None else "Modifier le produit"
        super().__init__(master, titre, 600, 130 + 48 * len(CHAMPS_PRODUIT))
        self.formulaire = FormulaireChamps(self, CHAMPS_PRODUIT, largeur=320)
        self.formulaire.pack(fill="x", padx=15, pady=(15, 5))
        if produit_id is not None:
            produit = caisse_service.obtenir(ctx.conn, produit_id)
            if produit is not None:
                valeurs = dict(produit)
                valeurs["code"] = caisse_service.code_affiche(produit)
                valeurs["codes_barres"] = produit["codes_barres"] or ""
                self.formulaire.remplir(valeurs)
        ligne_boutons(self, [("Enregistrer", self._enregistrer, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=15)
        self.after(250, lambda: self.formulaire.entrees["codes_barres"].focus_set())

    def _enregistrer(self) -> None:
        try:
            if self.produit_id is None:
                resultat = caisse_service.creer_produit(self.ctx.conn, self.formulaire.valeurs(), self.ctx.utilisateur)
            else:
                resultat = caisse_service.modifier_produit(self.ctx.conn, self.produit_id, self.formulaire.valeurs(),
                                                           self.ctx.utilisateur)
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


class DialogueReapproCaisse(FenetreModale):
    """Réception de marchandise : quantité reçue et prix d'achat (devient le dernier prix d'achat)."""

    def __init__(self, master, ctx: Contexte, produit_id: int, apres: Callable[[], None]):
        super().__init__(master, "Réception de marchandise", 460, 360)
        self.ctx, self.produit_id, self.apres = ctx, produit_id, apres
        produit = caisse_service.obtenir(ctx.conn, produit_id)
        ctk.CTkLabel(self, text=produit["nom"], font=ctk.CTkFont(size=15, weight="bold"), wraplength=420).pack(pady=(20, 4))
        ctk.CTkLabel(self, text=f"Stock actuel : {produit['quantite_stock']}").pack()
        ctk.CTkLabel(self, text="Quantité reçue :").pack(pady=(12, 2))
        self.quantite = ctk.CTkEntry(self, width=200, justify="center")
        self.quantite.pack()
        ctk.CTkLabel(self, text="Prix d'achat unitaire (DA) :").pack(pady=(10, 2))
        self.prix = ctk.CTkEntry(self, width=200, justify="center")
        self.prix.pack()
        self.prix.insert(0, fmt_brut(produit["prix_achat"]))
        self.prix.bind("<Return>", lambda _e: self._valider())
        ligne_boutons(self, [("Enregistrer", self._valider, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=20)
        self.after(200, self.quantite.focus_set)

    def _valider(self) -> None:
        try:
            caisse_service.reapprovisionner(self.ctx.conn, self.produit_id, self.quantite.get(), self.prix.get(),
                                            self.ctx.utilisateur)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        self.apres()
        self.destroy()


class DialogueAjustement(FenetreModale):
    """Inventaire : on saisit la quantité réellement comptée ; l'écart est tracé dans les logs."""

    def __init__(self, master, ctx: Contexte, produit_id: int, apres: Callable[[], None]):
        super().__init__(master, "Inventaire / ajustement du stock", 460, 360)
        self.ctx, self.produit_id, self.apres = ctx, produit_id, apres
        produit = caisse_service.obtenir(ctx.conn, produit_id)
        ctk.CTkLabel(self, text=produit["nom"], font=ctk.CTkFont(size=15, weight="bold"), wraplength=420).pack(pady=(20, 4))
        ctk.CTkLabel(self, text=f"Stock dans l'application : {produit['quantite_stock']}").pack()
        ctk.CTkLabel(self, text="Quantité réellement comptée :").pack(pady=(12, 2))
        self.quantite = ctk.CTkEntry(self, width=200, justify="center")
        self.quantite.pack()
        ctk.CTkLabel(self, text="Motif (facultatif) :").pack(pady=(10, 2))
        self.motif = ctk.CTkEntry(self, width=300)
        self.motif.pack()
        self.motif.bind("<Return>", lambda _e: self._valider())
        ligne_boutons(self, [("Corriger le stock", self._valider, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=20)
        self.after(200, self.quantite.focus_set)

    def _valider(self) -> None:
        try:
            ecart = caisse_service.ajuster_stock(self.ctx.conn, self.produit_id, self.quantite.get(),
                                                 self.ctx.utilisateur, self.motif.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        self.apres()
        self.destroy()
        afficher_info(self.master, f"Stock corrigé (écart {ecart:+d}).", "Inventaire")


class DialogueAttentes(FenetreModale):
    """Liste des tickets mis en attente : reprendre ou supprimer."""

    COLONNES = [("id", "N°", 50, "center"), ("heure", "Mis de côté", 130, "center"), ("employe", "Employé", 120, "w"),
                ("libelle", "Libellé", 150, "w"), ("articles", "Articles", 70, "e"), ("total", "Total", 110, "e")]

    def __init__(self, master, ctx: Contexte, quand_reprise: Callable[[dict], None]):
        super().__init__(master, "Tickets en attente", 700, 450)
        self.ctx, self.quand_reprise = ctx, quand_reprise
        self.tableau = Tableau(self, self.COLONNES, hauteur=10)
        self.tableau.pack(fill="both", expand=True, padx=15, pady=(15, 5))
        self.tableau.lier_double_clic(self._reprendre)
        ligne_boutons(self, [("Fermer", self.destroy, "#6b7280"), ("Supprimer", self._supprimer, "#dc2626"),
                             ("Reprendre", self._reprendre, None)]).pack(fill="x", padx=15, pady=12)
        self._charger()

    def _charger(self) -> None:
        self.tableau.vider()
        for a in caisse_service.lister_attentes(self.ctx.conn):
            self.tableau.ajouter((a["id"], fmt_datetime(a["date"]), a["utilisateur_nom"], a["libelle"] or "",
                                  a["nb_articles"], fmt_prix(a["total"])), iid=str(a["id"]))

    def _reprendre(self) -> None:
        iid = self.tableau.selection()
        if not iid:
            afficher_info(self, "Sélectionnez un ticket en attente.")
            return
        try:
            panier = caisse_service.reprendre_attente(self.ctx.conn, int(iid))
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            self._charger()
            return
        for message in panier["avertissements"]:
            afficher_avertissement(self, message)
        self.destroy()
        self.quand_reprise(panier)

    def _supprimer(self) -> None:
        iid = self.tableau.selection()
        if iid and confirmer(self, "Supprimer ce ticket en attente ?"):
            caisse_service.supprimer_attente(self.ctx.conn, int(iid))
            self._charger()
