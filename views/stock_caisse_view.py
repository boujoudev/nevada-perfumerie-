"""STOCK des produits cosmétiques : recherche, fiche produit, réception, inventaire, import."""

from __future__ import annotations

import logging
import sqlite3
from tkinter import filedialog
from typing import Optional

import customtkinter as ctk

from services import caisse_service, stats_caisse_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_prix
from views.dialogues_caisse import DialogueAjustement, DialogueProduitCaisse, DialogueReapproCaisse
from views.dialogues_commun import DialogueRapport
from views.widgets import Tableau, afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)
LIMITE_AFFICHAGE = 300      # au-delà, on invite à affiner la recherche (un gros tableau ralentit l'écran)


class StockCaisseView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection, ctx: Contexte):
        super().__init__(master, fg_color="transparent")
        self.conn, self.ctx = conn, ctx
        self.modifiable = ctx.peut("caisse_stock_modifier")          # administrateur : peut tout modifier
        self.voir_achat = ctx.peut("voir_prix_achat")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text="Stock cosmétique", font=ctk.CTkFont(size=24, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        barre = ctk.CTkFrame(self, fg_color="transparent")
        barre.grid(row=1, column=0, sticky="ew", padx=20, pady=5)
        self.recherche = ctk.CTkEntry(barre, width=380, placeholder_text="Rechercher : nom, catégorie, ID ou code-barres…")
        self.recherche.pack(side="left", padx=(0, 8))
        self.recherche.bind("<KeyRelease>", lambda _e: self.rafraichir())
        self.lbl_resume = ctk.CTkLabel(barre, text="", text_color="#6b7280")
        self.lbl_resume.pack(side="right")

        colonnes = [("id", "ID", 90, "center"), ("codes", "Codes-barres", 160, "w"), ("nom", "Produit", 280, "w"),
                    ("categorie", "Catégorie", 120, "w")]
        if self.voir_achat:
            colonnes.append(("achat", "Prix d'achat", 110, "e"))
        colonnes += [("vente", "Prix de vente", 110, "e"), ("stock", "Stock", 80, "e")]
        self.tableau = Tableau(self, colonnes)
        self.tableau.grid(row=2, column=0, sticky="nsew", padx=20, pady=8)

        if self.modifiable:
            self.tableau.lier_double_clic(self._modifier)
            actions = ctk.CTkFrame(self, fg_color="transparent")
            actions.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 10))
            for texte, commande, largeur, couleur in (
                    ("+ Nouveau produit", self._nouveau, 150, None), ("Modifier", self._modifier, 90, None),
                    ("Réception de stock", self._reception, 160, None), ("Inventaire", self._inventaire, 100, None),
                    ("Importer (CSV / Excel)", self._importer, 180, "#475569"),
                    ("Supprimer", self._supprimer, 100, "#dc2626")):
                options = {"fg_color": couleur} if couleur else {}
                ctk.CTkButton(actions, text=texte, width=largeur, command=commande, **options).pack(side="left", padx=3)
        else:
            ctk.CTkLabel(self, text="Consultation seulement : la modification du stock est réservée à l'administrateur.",
                         text_color="#6b7280").grid(row=3, column=0, sticky="w", padx=20, pady=(0, 10))

    def rafraichir(self) -> None:
        try:
            produits = caisse_service.rechercher(self.conn, self.recherche.get())
            valeur = stats_caisse_service.valeur_stock(self.conn) if self.voir_achat else None
        except sqlite3.Error as erreur:
            journal.exception("Stock caisse")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.tableau.vider()
        total = len(produits)
        bas = sum(1 for p in produits if p["bas"])
        for p in produits[:LIMITE_AFFICHAGE]:
            ligne = [p["code_affiche"], p["codes_barres"], p["nom"], p["categorie"] or ""]
            if self.voir_achat:
                ligne.append(fmt_prix(p["prix_achat"]))
            ligne += [fmt_prix(p["prix_vente"]), p["stock"]]
            self.tableau.ajouter(ligne, iid=str(p["id"]), tags=("bas",) if p["bas"] else ())
        texte = f"{total} produit(s)" + (f" — {bas} en stock bas (rouge)" if bas else "")
        if total > LIMITE_AFFICHAGE:
            texte += f" — {LIMITE_AFFICHAGE} affichés : tapez dans la recherche pour affiner"
        if valeur is not None:
            texte += f" — valeur du stock : {fmt_prix(valeur)}"
        self.lbl_resume.configure(text=texte)

    # --------------------------------------------------------------- actions
    def _selection(self) -> Optional[int]:
        iid = self.tableau.selection()
        if not iid:
            afficher_info(self, "Sélectionnez d'abord un produit dans le tableau.")
            return None
        return int(iid)

    def _nouveau(self) -> None:
        DialogueProduitCaisse(self.winfo_toplevel(), self.ctx, None, self.rafraichir)

    def _modifier(self) -> None:
        produit_id = self._selection()
        if produit_id is not None:
            DialogueProduitCaisse(self.winfo_toplevel(), self.ctx, produit_id, self.rafraichir)

    def _reception(self) -> None:
        produit_id = self._selection()
        if produit_id is not None:
            DialogueReapproCaisse(self.winfo_toplevel(), self.ctx, produit_id, self.rafraichir)

    def _inventaire(self) -> None:
        produit_id = self._selection()
        if produit_id is not None:
            DialogueAjustement(self.winfo_toplevel(), self.ctx, produit_id, self.rafraichir)

    def _supprimer(self) -> None:
        produit_id = self._selection()
        if produit_id is None:
            return
        produit = caisse_service.obtenir(self.conn, produit_id)
        if produit is None or not confirmer(self, f"Supprimer « {produit['nom']} » ?\n\nIl disparaîtra de la caisse "
                                                  "(l'historique des ventes est conservé ; son ID et ses codes-barres "
                                                  "seront libérés)."):
            return
        try:
            caisse_service.supprimer_produit(self.conn, produit_id, self.ctx.utilisateur)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
        except sqlite3.Error as erreur:
            journal.exception("Suppression produit caisse")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
        self.rafraichir()

    def _importer(self) -> None:
        chemin = filedialog.askopenfilename(
            parent=self, title="Importer un catalogue",
            filetypes=[("Catalogue (CSV ou Excel)", "*.csv *.xlsx"), ("Tous les fichiers", "*.*")])
        if not chemin:
            return
        try:
            resultat = caisse_service.importer(self.conn, chemin, self.ctx.utilisateur)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Import catalogue")
            afficher_erreur(self, f"Import impossible : {erreur}")
            return
        texte = (f"Import terminé.\n\n{resultat['crees']} produit(s) créé(s)\n{resultat['mis_a_jour']} produit(s) "
                 f"mis à jour (le stock n'est pas modifié)\n{len(resultat['erreurs'])} ligne(s) en erreur")
        self.rafraichir()
        if resultat["erreurs"]:
            DialogueRapport(self.winfo_toplevel(), "Résultat de l'import",
                            texte + "\n\nLignes ignorées :\n" + "\n".join(resultat["erreurs"][:200]))
        else:
            afficher_info(self, texte, "Import terminé")
