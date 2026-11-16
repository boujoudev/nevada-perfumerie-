"""Section LOGS & STATISTIQUES : historique filtrable, export CSV, chiffres clés."""

from __future__ import annotations

import logging
import sqlite3
from tkinter import filedialog
from datetime import datetime
from typing import List

import customtkinter as ctk

from services import stats_service, vente_service
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_nombre, fmt_prix
from views.widgets import Tableau, afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)

COLONNES = [("date", "Date/Heure", 140, "center"), ("type", "Type", 100, "center"),
            ("produit", "Produit", 300, "w"), ("qte", "Quantité", 90, "e"),
            ("prix", "Prix", 120, "e"), ("benefice", "Bénéfice", 120, "e"),
            ("details", "Détails", 330, "w")]


class LogsView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        self._logs: List[sqlite3.Row] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Logs & Statistiques", font=ctk.CTkFont(size=24, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))
        self.onglets = ctk.CTkTabview(self)
        self.onglets.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self._construire_historique(self.onglets.add("Historique"))
        self._construire_stats(self.onglets.add("Statistiques"))

    # ------------------------------------------------------------- historique
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
        self.menu_type = ctk.CTkOptionMenu(barre, values=list(stats_service.FILTRES_TYPE), width=120,
                                           command=lambda _v: self.charger_logs())
        self.menu_type.pack(side="left", padx=4)
        ctk.CTkButton(barre, text="Appliquer", width=90, command=self.charger_logs).pack(side="left", padx=8)

        self.tableau = Tableau(parent, COLONNES)
        self.tableau.grid(row=1, column=0, sticky="nsew")

        self.lbl_totaux = ctk.CTkLabel(parent, text="", anchor="w", justify="left", wraplength=1000,
                                       font=ctk.CTkFont(weight="bold"))
        self.lbl_totaux.grid(row=2, column=0, sticky="w", pady=(8, 2))
        bas = ctk.CTkFrame(parent, fg_color="transparent")
        bas.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        ctk.CTkButton(bas, text="Exporter en CSV", width=140, command=self._exporter).pack(side="right", padx=4)
        ctk.CTkButton(bas, text="Supprimer la vente sélectionnée", width=220, fg_color="#dc2626",
                      hover_color="#b91c1c", command=self._supprimer_vente).pack(side="right", padx=4)

    def charger_logs(self) -> None:
        try:
            debut, fin = stats_service.bornes(self.menu_periode.get(), self.date_debut.get(),
                                              self.date_fin.get())
            self._logs = stats_service.lister_logs(self.conn, debut, fin, self.menu_type.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Chargement logs")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.tableau.vider()
        for l in self._logs:
            libelle = stats_service.LIBELLES_TYPE.get(l["type"], l["type"])
            self.tableau.ajouter(
                (fmt_datetime(l["date_log"]), libelle, l["produit_nom"] or "",
                 fmt_nombre(l["quantite"]), fmt_prix(l["prix"]) if l["prix"] is not None else "",
                 fmt_prix(l["benefice"]) if l["benefice"] is not None else "", l["details"] or ""),
                iid=str(l["id"]), tags=("annulation",) if l["type"] == "ANNULATION" else ())
        t = stats_service.totaux_logs(self._logs)
        texte = (f"{len(self._logs)} ligne(s)  —  Ventes nettes : {fmt_prix(t['ca'])}  —  "
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
            initialfile=f"logs_{datetime.now():%Y%m%d_%H%M}.csv",
            filetypes=[("Fichier CSV (Excel)", "*.csv")])
        if not chemin:
            return
        try:
            nombre = stats_service.exporter_csv(chemin, self._logs)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        afficher_info(self, f"{nombre} ligne(s) exportée(s) :\n{chemin}", "Export terminé")

    def _supprimer_vente(self) -> None:
        iid = self.tableau.selection()
        if iid is None:
            afficher_info(self, "Sélectionnez d'abord une ligne « Vente » dans le tableau.")
            return
        log = next((l for l in self._logs if str(l["id"]) == iid), None)
        if log is None or log["type"] != "VENTE" or log["vente_id"] is None:
            afficher_info(self, "Seules les lignes de type « Vente » peuvent être supprimées.")
            return
        if not confirmer(self, f"Supprimer la vente n°{log['vente_id']} ?\n\n"
                               "Les stocks seront remis (sauf le flacon apporté par le client) "
                               "et la suppression sera enregistrée dans les logs."):
            return
        try:
            vente_service.supprimer_vente(self.conn, log["vente_id"])
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
        except sqlite3.Error as erreur:
            journal.exception("Suppression vente")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
        self.rafraichir()

    # ------------------------------------------------------------ statistiques
    def _construire_stats(self, parent) -> None:
        parent.grid_columnconfigure((0, 1, 2), weight=1)
        tableau = ctk.CTkFrame(parent)
        tableau.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(5, 10))
        tableau.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        titres = ("", "Chiffre d'affaires", "Dépense (coût des produits vendus)", "Bénéfice", "Nombre de ventes")
        for col, titre in enumerate(titres):
            ctk.CTkLabel(tableau, text=titre, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, padx=10, pady=8, sticky="w" if col == 0 else "e")
        self.cellules = {}
        for ligne, periode in enumerate(("Aujourd'hui", "Ce mois", "Cette année"), start=1):
            ctk.CTkLabel(tableau, text=periode, anchor="w").grid(row=ligne, column=0, padx=10, pady=6, sticky="w")
            for col in (1, 2, 3, 4):
                lbl = ctk.CTkLabel(tableau, text="", anchor="e", font=ctk.CTkFont(size=15))
                lbl.grid(row=ligne, column=col, padx=10, pady=6, sticky="e")
                self.cellules[(periode, col)] = lbl
        self.lbl_valeur_stock = ctk.CTkLabel(parent, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_valeur_stock.grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=8)
        self.lbl_top_parfums = ctk.CTkLabel(parent, text="", justify="left", anchor="nw")
        self.lbl_top_parfums.grid(row=2, column=0, sticky="nw", padx=10, pady=8)
        self.lbl_top_benefice = ctk.CTkLabel(parent, text="", justify="left", anchor="nw")
        self.lbl_top_benefice.grid(row=2, column=1, sticky="nw", padx=10, pady=8)
        self.lbl_top_flacons = ctk.CTkLabel(parent, text="", justify="left", anchor="nw")
        self.lbl_top_flacons.grid(row=2, column=2, sticky="nw", padx=10, pady=8)

    def charger_stats(self) -> None:
        try:
            for periode, valeurs in stats_service.resume_standard(self.conn).items():
                self.cellules[(periode, 1)].configure(text=fmt_prix(valeurs["ca"]))
                self.cellules[(periode, 2)].configure(text=fmt_prix(valeurs["cout"]))
                self.cellules[(periode, 3)].configure(text=fmt_prix(valeurs["benefice"]))
                self.cellules[(periode, 4)].configure(text=str(valeurs["nb_ventes"]))
            self.lbl_valeur_stock.configure(
                text=f"Valeur du stock actuel (prix d'achat) : {fmt_prix(stats_service.valeur_stock(self.conn))}")
            parfums = stats_service.top_parfums(self.conn)
            parfums_benefice = stats_service.top_parfums_benefice(self.conn)
            flacons = stats_service.top_flacons(self.conn)
        except sqlite3.Error as erreur:
            journal.exception("Statistiques")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.lbl_top_parfums.configure(text="Top 5 parfums — les plus vendus\n" + (
            "\n".join(f"{i}. {p['nom']} — {p['nb_ventes']} vente(s), {fmt_nombre(p['total_ml'])} ml"
                      for i, p in enumerate(parfums, 1)) or "Aucune vente"))
        self.lbl_top_benefice.configure(text="Top 5 parfums — meilleur bénéfice\n" + (
            "\n".join(f"{i}. {p['nom']} — {fmt_prix(p['benefice_total'])} ({p['nb_ventes']} vente(s))"
                      for i, p in enumerate(parfums_benefice, 1)) or "Aucune vente"))
        self.lbl_top_flacons.configure(text="Top 5 flacons — les plus vendus\n" + (
            "\n".join(f"{i}. {f['nom']} — {f['nb_ventes']} vente(s)"
                      for i, f in enumerate(flacons, 1)) or "Aucune vente"))

    def rafraichir(self) -> None:
        self.charger_logs()
        self.charger_stats()
