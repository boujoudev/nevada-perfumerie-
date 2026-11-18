"""LOGS & STATISTIQUES du module cosmétique (administrateur)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from tkinter import filedialog
from typing import List

import customtkinter as ctk

from services import caisse_service, session_service, stats_caisse_service as sc, stats_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_nombre, fmt_prix
from views.widgets import Tableau, afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)

COLONNES = [("date", "Date/Heure", 140, "center"), ("type", "Type", 130, "center"), ("employe", "Employé", 100, "w"),
            ("produit", "Produit", 240, "w"), ("qte", "Qté", 60, "e"), ("prix", "Prix", 110, "e"),
            ("benefice", "Bénéfice", 110, "e"), ("details", "Détails", 300, "w")]


class LogsCaisseView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection, ctx: Contexte):
        super().__init__(master, fg_color="transparent")
        self.conn, self.ctx = conn, ctx
        self._logs: List[sqlite3.Row] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Logs & Statistiques — Cosmétique", font=ctk.CTkFont(size=24, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))
        self.onglets = ctk.CTkTabview(self)
        self.onglets.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self._construire_historique(self.onglets.add("Historique"))
        self._construire_stats(self.onglets.add("Statistiques"))

    # ------------------------------------------------------------ historique
    def _construire_historique(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        barre = ctk.CTkFrame(parent, fg_color="transparent")
        barre.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(barre, text="Période").pack(side="left", padx=(0, 4))
        self.menu_periode = ctk.CTkOptionMenu(barre, values=list(stats_service.PERIODES), width=140,
                                              command=lambda _v: self.charger_logs())
        self.menu_periode.pack(side="left", padx=4)
        self.date_debut = ctk.CTkEntry(barre, width=105, placeholder_text="JJ/MM/AAAA")
        self.date_debut.pack(side="left", padx=(8, 2))
        ctk.CTkLabel(barre, text="→").pack(side="left")
        self.date_fin = ctk.CTkEntry(barre, width=105, placeholder_text="JJ/MM/AAAA")
        self.date_fin.pack(side="left", padx=(2, 8))
        for entree in (self.date_debut, self.date_fin):
            entree.bind("<Return>", lambda _e: self.charger_logs())
        ctk.CTkLabel(barre, text="Type").pack(side="left", padx=(8, 4))
        self.menu_type = ctk.CTkOptionMenu(barre, values=list(sc.FILTRES_TYPE), width=210,
                                           command=lambda _v: self.charger_logs())
        self.menu_type.pack(side="left", padx=4)
        ctk.CTkButton(barre, text="Appliquer", width=90, command=self.charger_logs).pack(side="left", padx=8)
        self.tableau = Tableau(parent, COLONNES)
        self.tableau.grid(row=1, column=0, sticky="nsew")
        self.lbl_totaux = ctk.CTkLabel(parent, text="", anchor="w", justify="left", wraplength=1000,
                                       font=ctk.CTkFont(weight="bold"))
        self.lbl_totaux.grid(row=2, column=0, sticky="w", pady=(8, 2))
        bas = ctk.CTkFrame(parent, fg_color="transparent")
        bas.grid(row=3, column=0, sticky="ew")
        ctk.CTkButton(bas, text="Exporter en CSV", width=140, command=self._exporter).pack(side="right", padx=4)
        ctk.CTkButton(bas, text="Annuler le ticket sélectionné", width=220, fg_color="#dc2626", hover_color="#b91c1c",
                      command=self._annuler_ticket).pack(side="right", padx=4)

    def charger_logs(self) -> None:
        try:
            debut, fin = stats_service.bornes(self.menu_periode.get(), self.date_debut.get(), self.date_fin.get())
            self._logs = sc.lister_logs(self.conn, debut, fin, self.menu_type.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Logs caisse")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.tableau.vider()
        for l in self._logs:
            self.tableau.ajouter(
                (fmt_datetime(l["date_log"]), stats_service.LIBELLES_TYPE.get(l["type"], l["type"]),
                 l["utilisateur_nom"] or "", l["produit_nom"] or "", fmt_nombre(l["quantite"]),
                 fmt_prix(l["prix"]) if l["prix"] is not None else "",
                 fmt_prix(l["benefice"]) if l["benefice"] is not None else "", l["details"] or ""),
                iid=str(l["id"]), tags=("annulation",) if l["type"] in ("ANNULATION",) else ())
        t = sc.totaux_logs(self._logs)
        texte = (f"{len(self._logs)} ligne(s)  —  Ventes nettes (retours déduits) : {fmt_prix(t['ca'])}  —  "
                 f"Dépense nette (coût des produits vendus) : {fmt_prix(t['cout'])}  —  "
                 f"Bénéfice net : {fmt_prix(t['benefice'])}")
        if t["achats"]:
            texte += f"  —  Achats de stock : {fmt_prix(t['achats'])}"
        self.lbl_totaux.configure(text=texte)

    def _exporter(self) -> None:
        if not self._logs:
            afficher_info(self, "Il n'y a rien à exporter avec ces filtres.")
            return
        chemin = filedialog.asksaveasfilename(
            parent=self, title="Exporter en CSV", defaultextension=".csv",
            initialfile=f"logs_cosmetique_{datetime.now():%Y%m%d_%H%M}.csv", filetypes=[("Fichier CSV (Excel)", "*.csv")])
        if not chemin:
            return
        try:
            nombre = stats_service.exporter_csv(chemin, self._logs)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        afficher_info(self, f"{nombre} ligne(s) exportée(s) :\n{chemin}", "Export terminé")

    def _annuler_ticket(self) -> None:
        iid = self.tableau.selection()
        log = next((l for l in self._logs if str(l["id"]) == iid), None) if iid else None
        if log is None or log["type"] != "VENTE" or log["ticket_id"] is None:
            afficher_info(self, "Sélectionnez d'abord une ligne « Vente » dans le tableau.")
            return
        if not confirmer(self, f"Annuler le ticket n°{log['ticket_id']} ?\n\nLe stock sera remis et le ticket exclu "
                               "des chiffres. Impossible si la session est clôturée ou s'il y a déjà eu un retour."):
            return
        try:
            caisse_service.annuler_ticket(self.conn, log["ticket_id"], self.ctx.utilisateur)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
        except sqlite3.Error as erreur:
            journal.exception("Annulation ticket")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
        self.rafraichir()

    # ------------------------------------------------------------ statistiques
    def _construire_stats(self, parent) -> None:
        parent.grid_columnconfigure((0, 1), weight=1)
        tableau = ctk.CTkFrame(parent)
        tableau.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(5, 10))
        tableau.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)
        titres = ("", "Ventes nettes", "Dépense (coût)", "Bénéfice net", "Tickets", "Panier moyen")
        for col, titre in enumerate(titres):
            ctk.CTkLabel(tableau, text=titre, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, padx=10, pady=8, sticky="w" if col == 0 else "e")
        self.cellules = {}
        for ligne, periode in enumerate(("Aujourd'hui", "Ce mois", "Cette année"), start=1):
            ctk.CTkLabel(tableau, text=periode, anchor="w").grid(row=ligne, column=0, padx=10, pady=6, sticky="w")
            for col in range(1, 6):
                lbl = ctk.CTkLabel(tableau, text="", anchor="e", font=ctk.CTkFont(size=15))
                lbl.grid(row=ligne, column=col, padx=10, pady=6, sticky="e")
                self.cellules[(periode, col)] = lbl
        self.lbl_valeur_stock = ctk.CTkLabel(parent, text="", font=ctk.CTkFont(size=16, weight="bold"), justify="left")
        self.lbl_valeur_stock.grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=8)
        self.lbl_top_quantite = ctk.CTkLabel(parent, text="", justify="left", anchor="nw")
        self.lbl_top_quantite.grid(row=2, column=0, sticky="nw", padx=10, pady=8)
        self.lbl_top_benefice = ctk.CTkLabel(parent, text="", justify="left", anchor="nw")
        self.lbl_top_benefice.grid(row=2, column=1, sticky="nw", padx=10, pady=8)
        self.lbl_ecarts = ctk.CTkLabel(parent, text="", justify="left", anchor="nw")
        self.lbl_ecarts.grid(row=3, column=0, columnspan=2, sticky="nw", padx=10, pady=8)

    def charger_stats(self) -> None:
        try:
            for periode, v in sc.resume_standard(self.conn).items():
                for col, texte in ((1, fmt_prix(v["ca_net"])), (2, fmt_prix(v["cout"])), (3, fmt_prix(v["benefice"])),
                                   (4, str(v["nb_tickets"])), (5, fmt_prix(v["panier_moyen"]))):
                    self.cellules[(periode, col)].configure(text=texte)
            alertes = len(caisse_service.produits_en_alerte(self.conn))
            self.lbl_valeur_stock.configure(
                text=f"Valeur du stock (prix d'achat) : {fmt_prix(sc.valeur_stock(self.conn))}   —   "
                     f"{alertes} produit(s) en stock bas")
            par_quantite = sc.top_produits(self.conn, 5, "quantite")
            par_benefice = sc.top_produits(self.conn, 5, "benefice")
            debut, fin = stats_service.bornes("Ce mois")
            ecarts = session_service.ecarts_par_utilisateur(self.conn, debut, fin)
        except sqlite3.Error as erreur:
            journal.exception("Statistiques caisse")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.lbl_top_quantite.configure(text="Top 5 produits — les plus vendus\n" + (
            "\n".join(f"{i}. {p['nom']} — {p['quantite']} vendu(s)" for i, p in enumerate(par_quantite, 1))
            or "Aucune vente"))
        self.lbl_top_benefice.configure(text="Top 5 produits — meilleur bénéfice\n" + (
            "\n".join(f"{i}. {p['nom']} — {fmt_prix(p['benefice'])}" for i, p in enumerate(par_benefice, 1))
            or "Aucune vente"))
        self.lbl_ecarts.configure(text="Écarts de caisse par employé (ce mois, sessions clôturées)\n" + (
            "\n".join(f"{e['nom']} : " + ("MANQUE " + fmt_prix(-e["ecart_total"]) if e["ecart_total"] < 0 else
                                          ("+" + fmt_prix(e["ecart_total"]) if e["ecart_total"] > 0 else "juste"))
                      + f" ({e['nb_sessions']} session(s))" for e in ecarts) or "Aucune session clôturée ce mois-ci"))

    def rafraichir(self) -> None:
        self.charger_logs()
        self.charger_stats()
