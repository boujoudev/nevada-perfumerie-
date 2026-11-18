"""Gestion des utilisateurs (administrateur) : liste, création, modification, mot de passe."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Optional

import customtkinter as ctk

from services import utilisateurs_service
from utils.erreurs import ErreurMetier
from views.dialogues_commun import DialogueMotDePasse
from views.widgets import FenetreModale, Tableau, afficher_erreur, afficher_info, ligne_boutons

journal = logging.getLogger(__name__)
ROLES = {"Caissier": "CAISSIER", "Administrateur": "ADMIN"}


class DialogueUtilisateur(FenetreModale):
    """Création (utilisateur_id=None) ou modification d'un utilisateur."""

    def __init__(self, master, conn: sqlite3.Connection, utilisateur_id: Optional[int], apres: Callable[[], None]):
        self.conn, self.utilisateur_id, self.apres = conn, utilisateur_id, apres
        creation = utilisateur_id is None
        super().__init__(master, "Nouvel utilisateur" if creation else "Modifier l'utilisateur", 480, 520 if creation else 400)
        utilisateur = None if creation else utilisateurs_service.obtenir(conn, utilisateur_id)
        ctk.CTkLabel(self, text="Nom affiché").pack(pady=(18, 2))
        self.nom = ctk.CTkEntry(self, width=300)
        self.nom.pack()
        ctk.CTkLabel(self, text="Identifiant de connexion").pack(pady=(10, 2))
        self.identifiant = ctk.CTkEntry(self, width=300)
        self.identifiant.pack()
        ctk.CTkLabel(self, text="Rôle").pack(pady=(10, 2))
        self.menu_role = ctk.CTkOptionMenu(self, values=list(ROLES), width=300)
        self.menu_role.pack()
        self.var_actif = ctk.BooleanVar(value=True)
        if creation:
            self.mot_de_passe = ctk.CTkEntry(self, show="•", width=300, placeholder_text="Mot de passe (4 caractères minimum)")
            self.mot_de_passe.pack(pady=(14, 4))
            self.confirmation = ctk.CTkEntry(self, show="•", width=300, placeholder_text="Confirmer le mot de passe")
            self.confirmation.pack(pady=4)
        else:
            self.nom.insert(0, utilisateur["nom"])
            self.identifiant.insert(0, utilisateur["identifiant"])
            self.identifiant.configure(state="disabled")
            self.menu_role.set(utilisateurs_service.LIBELLES_ROLE.get(utilisateur["role"], "Caissier"))
            self.var_actif.set(bool(utilisateur["actif"]))
            ctk.CTkCheckBox(self, text="Compte actif (décochez pour désactiver)", variable=self.var_actif
                            ).pack(pady=14)
        ligne_boutons(self, [("Enregistrer", self._enregistrer, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=18)

    def _enregistrer(self) -> None:
        role = ROLES.get(self.menu_role.get(), "CAISSIER")
        try:
            if self.utilisateur_id is None:
                utilisateurs_service.creer_utilisateur(self.conn, self.nom.get(), self.identifiant.get(),
                                                       self.mot_de_passe.get(), self.confirmation.get(), role)
            else:
                utilisateurs_service.modifier_utilisateur(self.conn, self.utilisateur_id, self.nom.get(), role,
                                                          bool(self.var_actif.get()))
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Enregistrement utilisateur")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.apres()
        self.destroy()


class DialogueUtilisateurs(FenetreModale):
    """Liste des utilisateurs avec les actions de gestion (réservé à l'administrateur)."""

    COLONNES = [("nom", "Nom", 200, "w"), ("identifiant", "Identifiant", 160, "w"), ("role", "Rôle", 140, "w"),
                ("etat", "État", 100, "center")]

    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, "Utilisateurs", 700, 500)
        self.conn = conn
        self.tableau = Tableau(self, self.COLONNES, hauteur=10)
        self.tableau.pack(fill="both", expand=True, padx=15, pady=(15, 5))
        self.tableau.lier_double_clic(self._modifier)
        ligne_boutons(self, [("Fermer", self.destroy, "#6b7280"), ("Mot de passe…", self._mot_de_passe, "#475569"),
                             ("Modifier", self._modifier, None), ("+ Nouvel utilisateur", self._nouveau, None)]
                      ).pack(fill="x", padx=15, pady=12)
        self._charger()

    def _charger(self) -> None:
        self.tableau.vider()
        for u in utilisateurs_service.lister_utilisateurs(self.conn):
            self.tableau.ajouter((u["nom"], u["identifiant"], utilisateurs_service.LIBELLES_ROLE[u["role"]],
                                  "Actif" if u["actif"] else "Désactivé"), iid=str(u["id"]),
                                 tags=() if u["actif"] else ("annulation",))

    def _selection(self) -> Optional[int]:
        iid = self.tableau.selection()
        if not iid:
            afficher_info(self, "Sélectionnez d'abord un utilisateur.")
            return None
        return int(iid)

    def _nouveau(self) -> None:
        DialogueUtilisateur(self, self.conn, None, self._charger)

    def _modifier(self) -> None:
        utilisateur_id = self._selection()
        if utilisateur_id is not None:
            DialogueUtilisateur(self, self.conn, utilisateur_id, self._charger)

    def _mot_de_passe(self) -> None:
        utilisateur_id = self._selection()
        if utilisateur_id is not None:
            utilisateur = utilisateurs_service.obtenir(self.conn, utilisateur_id)
            DialogueMotDePasse(self, self.conn, utilisateur_id, utilisateur["nom"], verifier_ancien=False)
