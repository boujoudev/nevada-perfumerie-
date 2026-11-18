"""Petites boîtes de dialogue réutilisables : nombre, remise, rapport texte, mot de passe."""

from __future__ import annotations

import sqlite3
from typing import Callable, Optional, Tuple

import customtkinter as ctk
from tkinter import filedialog

from services import utilisateurs_service
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_brut, parse_nombre
from views.widgets import FenetreModale, afficher_erreur, afficher_info, ligne_boutons


class DialogueNombre(FenetreModale):
    """Demande un nombre (quantité, prix...). quand_ok(valeur) est appelé si la saisie est valide."""

    def __init__(self, master, titre: str, libelle: str, valeur_initiale, quand_ok: Callable,
                 entier: bool = False, minimum: Optional[float] = 0, strict: bool = False):
        super().__init__(master, titre, 400, 230)
        self.quand_ok, self.libelle, self.entier, self.minimum, self.strict = quand_ok, libelle, entier, minimum, strict
        ctk.CTkLabel(self, text=libelle, wraplength=360).pack(pady=(25, 8))
        self.entree = ctk.CTkEntry(self, width=200, height=40, justify="center", font=ctk.CTkFont(size=18))
        self.entree.pack()
        self.entree.insert(0, fmt_brut(valeur_initiale))
        self.entree.bind("<Return>", lambda _e: self._valider())
        ligne_boutons(self, [("OK", self._valider, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=25)
        self.after(200, lambda: (self.entree.focus_set(), self.entree.select_range(0, "end")))

    def _valider(self) -> None:
        try:
            valeur = parse_nombre(self.entree.get(), self.libelle, minimum=self.minimum,
                                  entier=self.entier, strictement_positif=self.strict)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        self.destroy()
        self.quand_ok(valeur)


class DialogueRemise(FenetreModale):
    """Remise en montant (DA) ou en pourcentage. quand_ok(type|None, valeur) ; None = pas de remise."""

    CHOIX = {"Montant (DA)": "MONTANT", "Pourcentage (%)": "POURCENT"}

    def __init__(self, master, titre: str, quand_ok: Callable, actuelle: Tuple[Optional[str], float] = (None, 0)):
        super().__init__(master, titre, 420, 290)
        self.quand_ok = quand_ok
        ctk.CTkLabel(self, text=titre, font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(20, 8))
        inverse = {v: k for k, v in self.CHOIX.items()}
        self.menu = ctk.CTkOptionMenu(self, values=list(self.CHOIX), width=200)
        self.menu.pack(pady=4)
        self.menu.set(inverse.get(actuelle[0], "Pourcentage (%)"))
        self.entree = ctk.CTkEntry(self, width=200, height=40, justify="center", font=ctk.CTkFont(size=18))
        self.entree.pack(pady=8)
        if actuelle[0]:
            self.entree.insert(0, fmt_brut(actuelle[1]))
        self.entree.bind("<Return>", lambda _e: self._appliquer())
        ligne_boutons(self, [("Appliquer", self._appliquer, None), ("Aucune remise", self._supprimer, "#dc2626"),
                             ("Annuler", self.destroy, "#6b7280")]).pack(fill="x", padx=10, pady=18)
        self.after(200, self.entree.focus_set)

    def _appliquer(self) -> None:
        type_remise = self.CHOIX.get(self.menu.get(), "POURCENT")
        try:
            valeur = parse_nombre(self.entree.get(), "Remise", minimum=0, strictement_positif=True)
            if type_remise == "POURCENT" and valeur > 100:
                raise ErreurMetier("Une remise ne peut pas dépasser 100 %.")
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        self.destroy()
        self.quand_ok(type_remise, valeur)

    def _supprimer(self) -> None:
        self.destroy()
        self.quand_ok(None, 0)


class DialogueRapport(FenetreModale):
    """Affiche un rapport texte, avec enregistrement en .txt."""

    def __init__(self, master, titre: str, texte: str):
        super().__init__(master, titre, 720, 560)
        self.texte = texte
        zone = ctk.CTkTextbox(self, width=680, height=440, font=ctk.CTkFont(family="Courier", size=13))
        zone.pack(padx=15, pady=(15, 5), fill="both", expand=True)
        zone.insert("1.0", texte)
        zone.configure(state="disabled")
        ligne_boutons(self, [("Fermer", self.destroy, None), ("Enregistrer en .txt", self._enregistrer, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=10)

    def _enregistrer(self) -> None:
        chemin = filedialog.asksaveasfilename(parent=self, title="Enregistrer le rapport", defaultextension=".txt",
                                              initialfile="rapport.txt", filetypes=[("Texte", "*.txt")])
        if not chemin:
            return
        try:
            with open(chemin, "w", encoding="utf-8") as fichier:
                fichier.write(self.texte)
        except OSError as erreur:
            afficher_erreur(self, f"Impossible d'enregistrer : {erreur}")
            return
        afficher_info(self, f"Rapport enregistré :\n{chemin}")


class DialogueMotDePasse(FenetreModale):
    """Changer son propre mot de passe (l'ancien est demandé) ou celui d'un autre (administrateur)."""

    def __init__(self, master, conn: sqlite3.Connection, utilisateur_id: int, nom: str,
                 verifier_ancien: bool = True, apres: Optional[Callable] = None):
        super().__init__(master, "Mot de passe", 420, 380 if verifier_ancien else 320)
        self.conn, self.utilisateur_id, self.verifier_ancien, self.apres = conn, utilisateur_id, verifier_ancien, apres
        ctk.CTkLabel(self, text=f"Mot de passe de {nom}", font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(20, 6))
        self.ancien = None
        if verifier_ancien:
            self.ancien = ctk.CTkEntry(self, show="•", width=240, placeholder_text="Mot de passe actuel")
            self.ancien.pack(pady=6)
        self.nouveau = ctk.CTkEntry(self, show="•", width=240, placeholder_text="Nouveau mot de passe")
        self.nouveau.pack(pady=6)
        self.confirmation = ctk.CTkEntry(self, show="•", width=240, placeholder_text="Confirmer")
        self.confirmation.pack(pady=6)
        ligne_boutons(self, [("Enregistrer", self._enregistrer, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=20)

    def _enregistrer(self) -> None:
        try:
            if self.verifier_ancien:
                utilisateur = utilisateurs_service.obtenir(self.conn, self.utilisateur_id)
                if utilisateurs_service.authentifier(self.conn, utilisateur["identifiant"], self.ancien.get()) is None:
                    raise ErreurMetier("Le mot de passe actuel est incorrect.")
            utilisateurs_service.changer_mot_de_passe(self.conn, self.utilisateur_id, self.nouveau.get(),
                                                      self.confirmation.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        afficher_info(self, "Mot de passe modifié.")
        if self.apres:
            self.apres()
        self.destroy()
