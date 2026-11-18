"""Page « Session de caisse » : session en cours, pause / reprise / clôture, historique et rapports."""

from __future__ import annotations

import logging
import sqlite3
from typing import List, Optional

import customtkinter as ctk

from services import session_service, stats_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_prix
from views.dialogues_commun import DialogueRapport
from views.dialogues_session import DialogueCloture, DialogueMouvement
from views.session_ui import etat_session, ouvrir_ma_session
from views.style import ROUGE, VERT
from views.widgets import Tableau, afficher_erreur, afficher_info

journal = logging.getLogger(__name__)

COLONNES_EN_COURS = [("id", "N°", 60, "center"), ("employe", "Employé", 170, "w"), ("statut", "Statut", 150, "w"),
                     ("ouverture", "Ouverture", 150, "center"), ("fond", "Fond", 120, "e"),
                     ("attendu", "Espèces attendues", 150, "e")]
COLONNES_HISTORIQUE = [("id", "N°", 60, "center"), ("employe", "Employé", 150, "w"),
                       ("ouverture", "Ouverture", 140, "center"), ("cloture", "Clôture", 140, "center"),
                       ("fond", "Fond", 100, "e"), ("attendu", "Attendu", 110, "e"),
                       ("compte", "Compté", 110, "e"), ("ecart", "Écart", 130, "e"),
                       ("passation", "Passation", 100, "e")]
PERIODES = ("Aujourd'hui", "Cette semaine", "Ce mois", "Cette année", "Tout")


def _texte_ecart(ecart: Optional[float]) -> str:
    if ecart is None:
        return ""
    if ecart < 0:
        return f"MANQUE {fmt_prix(-ecart)}"
    if ecart > 0:
        return f"+{fmt_prix(ecart)}"
    return "juste"


class SessionsView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection, ctx: Contexte):
        super().__init__(master, fg_color="transparent")
        self.conn, self.ctx = conn, ctx
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Session de caisse", font=ctk.CTkFont(size=24, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))
        self.onglets = ctk.CTkTabview(self)
        self.onglets.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self._construire_en_cours(self.onglets.add("Sessions en cours"))
        self._construire_historique(self.onglets.add("Historique et rapports"))

    # ------------------------------------------------------------- en cours
    def _construire_en_cours(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(3, weight=1)
        self.lbl_etat = ctk.CTkLabel(parent, text="", anchor="w", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_etat.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self.lbl_chiffres = ctk.CTkLabel(parent, text="", anchor="w", justify="left")
        self.lbl_chiffres.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))
        barre = ctk.CTkFrame(parent, fg_color="transparent")
        barre.grid(row=2, column=0, sticky="ew", padx=5, pady=4)
        for texte, commande, largeur in (
                ("Ouvrir / reprendre ma session", self._ouvrir, 220), ("Mettre en pause", self._pause, 140),
                ("Mouvement de caisse", self._mouvement, 170), ("Reprendre la sélection", self._reprendre, 180),
                ("Clôturer", self._cloturer, 110)):
            ctk.CTkButton(barre, text=texte, width=largeur, command=commande).pack(side="left", padx=4)
        self.tableau_en_cours = Tableau(parent, COLONNES_EN_COURS, hauteur=6)
        self.tableau_en_cours.grid(row=3, column=0, sticky="nsew", padx=5, pady=6)
        ctk.CTkLabel(parent, text=("Une seule session est active à la fois : les ventes y sont comptées. "
                                   "Une session « en pause » reste à clôturer plus tard. "
                                   "Sélectionnez une ligne pour la reprendre ou la clôturer."),
                     text_color="#6b7280", wraplength=900, justify="left").grid(row=4, column=0, sticky="w", padx=10)

    def _selection_en_cours(self) -> Optional[int]:
        iid = self.tableau_en_cours.selection()
        return int(iid) if iid else None

    def _session_cible(self) -> Optional[int]:
        """La session sélectionnée, sinon celle de l'utilisateur connecté."""
        choisie = self._selection_en_cours()
        if choisie is not None:
            return choisie
        mienne = session_service.session_de_utilisateur(self.conn, self.ctx.utilisateur_id)
        return mienne["id"] if mienne else None

    def _ouvrir(self) -> None:
        ouvrir_ma_session(self.ctx, self, lambda _id: self.rafraichir())

    def _pause(self) -> None:
        active = session_service.session_active(self.conn)
        if active is None:
            afficher_info(self, "Aucune session active.")
            return
        self._agir(lambda: session_service.mettre_en_pause(self.conn, active["id"], self.ctx.utilisateur))

    def _reprendre(self) -> None:
        cible = self._selection_en_cours()
        if cible is None:
            afficher_info(self, "Sélectionnez d'abord une session dans la liste.")
            return
        self._agir(lambda: session_service.reprendre_session(self.conn, cible, self.ctx.utilisateur))

    def _agir(self, action) -> None:
        try:
            action()
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
        except sqlite3.Error as erreur:
            journal.exception("Action session")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
        self.rafraichir()

    def _mouvement(self) -> None:
        if session_service.session_active(self.conn) is None:
            afficher_info(self, "Aucune session active : ouvrez une session d'abord.")
            return
        DialogueMouvement(self.winfo_toplevel(), self.ctx, self.rafraichir)

    def _cloturer(self) -> None:
        cible = self._session_cible()
        if cible is None:
            afficher_info(self, "Vous n'avez aucune session à clôturer.")
            return
        DialogueCloture(self.winfo_toplevel(), self.ctx, cible, self.rafraichir)

    # ----------------------------------------------------------- historique
    def _construire_historique(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        barre = ctk.CTkFrame(parent, fg_color="transparent")
        barre.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(barre, text="Période").pack(side="left", padx=(0, 4))
        self.menu_periode = ctk.CTkOptionMenu(barre, values=list(PERIODES), width=150,
                                              command=lambda _v: self._charger_historique())
        self.menu_periode.pack(side="left", padx=4)
        ctk.CTkButton(barre, text="Voir le rapport", width=140, command=self._voir_rapport).pack(side="left", padx=12)
        if self.ctx.est_admin:
            self.jour = ctk.CTkEntry(barre, width=120, placeholder_text="JJ/MM/AAAA")
            self.jour.pack(side="left", padx=(20, 4))
            ctk.CTkButton(barre, text="Rapport de la journée", width=190, command=self._rapport_journee
                          ).pack(side="left", padx=4)
        self.tableau_historique = Tableau(parent, COLONNES_HISTORIQUE)
        self.tableau_historique.grid(row=1, column=0, sticky="nsew")
        self.lbl_ecarts = ctk.CTkLabel(parent, text="", anchor="w", justify="left", wraplength=1000)
        self.lbl_ecarts.grid(row=2, column=0, sticky="w", pady=(8, 0))

    def _charger_historique(self) -> None:
        try:
            debut, fin = stats_service.bornes(self.menu_periode.get())
            filtre_utilisateur = None if self.ctx.est_admin else self.ctx.utilisateur_id
            sessions = session_service.lister_sessions(self.conn, utilisateur_id=filtre_utilisateur,
                                                       non_cloturees=False, debut=debut, fin=fin)
            ecarts = session_service.ecarts_par_utilisateur(self.conn, debut, fin) if self.ctx.est_admin else []
        except sqlite3.Error as erreur:
            journal.exception("Historique sessions")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.tableau_historique.vider()
        for s in sessions:
            tags = ("bas",) if (s["ecart"] or 0) < 0 else ()
            self.tableau_historique.ajouter(
                (s["id"], s["utilisateur_nom"], fmt_datetime(s["date_ouverture"]), fmt_datetime(s["date_cloture"]),
                 fmt_prix(s["fond_ouverture"]), fmt_prix(s["especes_attendues"]), fmt_prix(s["especes_comptees"]),
                 _texte_ecart(s["ecart"]), fmt_prix(s["ecart_passation"]) if s["ecart_passation"] else ""),
                iid=str(s["id"]), tags=tags)
        if self.ctx.est_admin:
            if ecarts:
                self.lbl_ecarts.configure(text="Écart cumulé par employé (sessions clôturées de la période) :  " +
                                          "   |   ".join(f"{e['nom']} : {_texte_ecart(round(e['ecart_total'], 2))} "
                                                         f"({e['nb_sessions']} session(s))" for e in ecarts))
            else:
                self.lbl_ecarts.configure(text="Aucune session clôturée sur cette période.")

    def _voir_rapport(self) -> None:
        iid = self.tableau_historique.selection()
        if not iid:
            afficher_info(self, "Sélectionnez une session dans la liste.")
            return
        self._afficher_rapport(lambda: session_service.rapport_session(self.conn, int(iid)), f"Session n°{iid}")

    def _rapport_journee(self) -> None:
        jour = self.jour.get()
        self._afficher_rapport(lambda: session_service.rapport_journee(self.conn, jour), "Rapport de la journée")

    def _afficher_rapport(self, fabrique, titre: str) -> None:
        try:
            texte = fabrique()
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        DialogueRapport(self.winfo_toplevel(), titre, texte)

    # ---------------------------------------------------------- rafraîchir
    def rafraichir(self) -> None:
        try:
            texte, couleur, _ = etat_session(self.ctx)
            self.lbl_etat.configure(text=texte, text_color=couleur if couleur != VERT else VERT)
            self._afficher_chiffres()
            self.tableau_en_cours.vider()
            for s in session_service.lister_sessions(self.conn, non_cloturees=True):
                attendu = fmt_prix(session_service.calculer(self.conn, s["id"])["attendues"]) \
                    if self.ctx.est_admin else "—"
                self.tableau_en_cours.ajouter(
                    (s["id"], s["utilisateur_nom"], session_service.LIBELLES_STATUT[s["statut"]],
                     fmt_datetime(s["date_ouverture"]), fmt_prix(s["fond_ouverture"]), attendu), iid=str(s["id"]),
                    tags=() if s["statut"] == "OUVERTE" else ("annulation",))
            self._charger_historique()
        except sqlite3.Error as erreur:
            journal.exception("Rafraîchissement sessions")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")

    def _afficher_chiffres(self) -> None:
        """Chiffres de la session de l'utilisateur (ou de la session active à défaut)."""
        session = session_service.session_de_utilisateur(self.conn, self.ctx.utilisateur_id) \
            or session_service.session_active(self.conn)
        if session is None:
            self.lbl_chiffres.configure(text="")
            return
        c = session_service.calculer(self.conn, session["id"])
        lignes = [f"Session n°{session['id']} de {session['utilisateur_nom']} — fond {fmt_prix(c['fond'])}",
                  f"Cosmétique : {fmt_prix(c['ventes_cosmetique'])} ({c['nb_tickets']} ticket(s))   |   "
                  f"Parfum : {fmt_prix(c['ventes_parfum'])} ({c['nb_ventes_parfum']} vente(s))   |   "
                  f"Retours : -{fmt_prix(c['retours'])}   |   Entrées : {fmt_prix(c['entrees'])}   |   "
                  f"Sorties : -{fmt_prix(c['sorties'])}"]
        if self.ctx.est_admin:
            lignes.append(f"Espèces attendues dans le tiroir pour cette session : {fmt_prix(c['attendues'])}")
        else:
            lignes.append("(le montant attendu s'affichera à la clôture, après votre comptage)")
        self.lbl_chiffres.configure(text="\n".join(lignes))
