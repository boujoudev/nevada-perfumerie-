"""Boîtes de dialogue des sessions de caisse : ouverture, clôture, mouvements."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Optional

import customtkinter as ctk

from services import session_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_brut, fmt_prix
from views.dialogues_commun import DialogueRapport
from views.widgets import (FenetreModale, afficher_avertissement, afficher_erreur, afficher_info,
                           confirmer, ligne_boutons)

journal = logging.getLogger(__name__)


def _erreur_base(parent, erreur: Exception) -> None:
    journal.exception("Erreur base de données (session)")
    afficher_erreur(parent, f"Erreur de base de données : {erreur}")


class DialogueOuvertureSession(FenetreModale):
    """Ouvre la session de l'utilisateur connecté : on compte le fond de caisse."""

    def __init__(self, master, ctx: Contexte, apres: Optional[Callable[[int], None]] = None):
        super().__init__(master, "Ouvrir ma session de caisse", 480, 380)
        self.ctx, self.apres = ctx, apres
        active = session_service.session_active(ctx.conn)
        ctk.CTkLabel(self, text=f"Session de {ctx.utilisateur['nom']}", font=ctk.CTkFont(size=16, weight="bold")
                     ).pack(pady=(22, 6))
        ctk.CTkLabel(self, text="Comptez l'argent présent dans le tiroir-caisse\net saisissez le fond de caisse (DA) :",
                     justify="center").pack(pady=6)
        self.entree = ctk.CTkEntry(self, width=220, height=44, justify="center", font=ctk.CTkFont(size=20))
        self.entree.pack(pady=6)
        self.entree.insert(0, fmt_brut(session_service.fond_suggere(ctx.conn)))
        self.entree.bind("<Return>", lambda _e: self._ouvrir())
        if active is not None:
            ctk.CTkLabel(self, text=(f"La session de {active['utilisateur_nom']} est active : elle passera EN PAUSE "
                                     "(sans être clôturée). Elle gardera ses propres chiffres."),
                         text_color="#b45309", wraplength=420, justify="center").pack(pady=8)
        ligne_boutons(self, [("Ouvrir la session", self._ouvrir, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=20)
        self.after(200, lambda: (self.entree.focus_set(), self.entree.select_range(0, "end")))

    def _ouvrir(self) -> None:
        try:
            session_id = session_service.ouvrir_session(self.ctx.conn, self.ctx.utilisateur, self.entree.get())
            session = session_service.lire(self.ctx.conn, session_id)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        if session["ecart_passation"]:
            afficher_avertissement(
                self, f"Écart de passation : le fond compté diffère de la clôture précédente de "
                      f"{fmt_prix(session['ecart_passation'])}.\nIl est enregistré dans le rapport (il n'est mis sur "
                      "le compte de personne).")
        self.destroy()
        if self.apres:
            self.apres(session_id)


class DialogueCloture(FenetreModale):
    """Clôture « à l'aveugle » : on compte l'argent, puis l'application affiche l'écart."""

    def __init__(self, master, ctx: Contexte, session_id: int, apres: Optional[Callable[[], None]] = None):
        super().__init__(master, "Clôturer la session", 500, 470)
        self.ctx, self.session_id, self.apres = ctx, session_id, apres
        session = session_service.lire(ctx.conn, session_id)
        ctk.CTkLabel(self, text=f"Clôture de la session n°{session_id}", font=ctk.CTkFont(size=16, weight="bold")
                     ).pack(pady=(22, 4))
        ctk.CTkLabel(self, text=f"Employé : {session['utilisateur_nom']}").pack()
        ctk.CTkLabel(self, text="Comptez TOUT l'argent du tiroir (espèces) et saisissez le total (DA).\n"
                                "Le montant attendu s'affichera ensuite avec l'écart.",
                     justify="center", text_color="#6b7280").pack(pady=10)
        self.entree = ctk.CTkEntry(self, width=240, height=46, justify="center", font=ctk.CTkFont(size=22))
        self.entree.pack(pady=6)
        self.entree.bind("<Return>", lambda _e: self._cloturer())
        ctk.CTkLabel(self, text="Note (facultatif) :").pack(pady=(10, 2))
        self.note = ctk.CTkEntry(self, width=360)
        self.note.pack()
        ligne_boutons(self, [("Clôturer", self._cloturer, "#dc2626"), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=22)
        self.after(200, self.entree.focus_set)

    def _cloturer(self) -> None:
        if not confirmer(self, "Clôturer définitivement cette session ?\nLes chiffres seront figés."):
            return
        try:
            resultat = session_service.cloturer_session(self.ctx.conn, self.session_id, self.entree.get(),
                                                        self.ctx.utilisateur, self.note.get())
            rapport = session_service.rapport_session(self.ctx.conn, self.session_id)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        parent = self.master
        self.destroy()
        if self.apres:
            self.apres()
        DialogueRapport(parent, f"Session n°{self.session_id} clôturée", rapport)


class DialogueMouvement(FenetreModale):
    """Entrée ou sortie d'argent du tiroir (retrait pour la banque, dépense, versement...)."""

    TYPES = {"Sortie d'argent (retrait, dépense)": "SORTIE", "Entrée d'argent (versement, monnaie)": "ENTREE"}

    def __init__(self, master, ctx: Contexte, apres: Optional[Callable[[], None]] = None):
        super().__init__(master, "Mouvement de caisse", 460, 400)
        self.ctx, self.apres = ctx, apres
        ctk.CTkLabel(self, text="Mouvement de caisse", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 8))
        self.menu = ctk.CTkOptionMenu(self, values=list(self.TYPES), width=300)
        self.menu.pack(pady=6)
        self.montant = ctk.CTkEntry(self, width=300, placeholder_text="Montant (DA)")
        self.montant.pack(pady=6)
        self.motif = ctk.CTkEntry(self, width=300, placeholder_text="Motif (obligatoire)")
        self.motif.pack(pady=6)
        self.motif.bind("<Return>", lambda _e: self._valider())
        ligne_boutons(self, [("Enregistrer", self._valider, None), ("Annuler", self.destroy, "#6b7280")]
                      ).pack(fill="x", padx=15, pady=22)
        self.after(200, self.montant.focus_set)

    def _valider(self) -> None:
        try:
            session_service.ajouter_mouvement(self.ctx.conn, self.ctx.utilisateur,
                                              self.TYPES.get(self.menu.get(), "SORTIE"),
                                              self.montant.get(), self.motif.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            _erreur_base(self, erreur)
            return
        self.destroy()
        if self.apres:
            self.apres()
