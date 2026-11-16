"""Section VENTE : composer des combinaisons flacon + parfum (+ alcool), panier, validation."""

from __future__ import annotations

import logging
import sqlite3
from typing import Dict, List, Optional

import customtkinter as ctk

from models.catalogue import CATALOGUE
from repositories import produits_repo
from services import clients_service, vente_service
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_nombre, fmt_prix, parse_nombre
from views.dialogues import DialogueClient
from views.style import ROUGE, VERT
from views.widgets import (Tableau, afficher_avertissement, afficher_erreur, afficher_info,
                           confirmer)

journal = logging.getLogger(__name__)
SANS_ALCOOL = "(sans alcool)"
SANS_CLIENT = "(sans client)"


class ChoixProduit(ctk.CTkFrame):
    """Sélecteur de produit : champ de recherche (nom ou ID) + liste déroulante + infos."""

    def __init__(self, master, conn: sqlite3.Connection, type_code: str, titre: str,
                 quand_change, optionnel: bool = False):
        super().__init__(master)
        self.conn, self.type_code, self.quand_change = conn, type_code, quand_change
        self.optionnel = optionnel
        self._tous: List[tuple] = []           # (libellé, id)
        self._affiches: Dict[str, Optional[int]] = {}
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=titre, font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self.recherche = ctk.CTkEntry(self, placeholder_text="Rechercher (nom ou ID)…")
        self.recherche.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        self.recherche.bind("<KeyRelease>", lambda _e: self._filtrer())
        self.variable = ctk.StringVar(value="")
        self.menu = ctk.CTkOptionMenu(self, variable=self.variable, values=["(aucun)"],
                                      command=self._choisi, dynamic_resizing=False)
        self.menu.grid(row=2, column=0, sticky="ew", padx=10, pady=2)
        self.info = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=360,
                                 text_color="#6b7280")
        self.info.grid(row=3, column=0, sticky="w", padx=10, pady=(2, 8))

    # ----------------------------------------------------------- données
    def recharger(self) -> None:
        t = CATALOGUE[self.type_code]
        self._tous = [(f"{t.code_affiche(r['id'])} · {r['nom']}", r["id"])
                      for r in produits_repo.lister(self.conn, self.type_code)]
        if self.optionnel:
            self._tous.insert(0, (SANS_ALCOOL, None))
        self._appliquer_filtre()

    def _filtrer(self) -> None:
        self._appliquer_filtre()

    def _appliquer_filtre(self) -> None:
        """Met à jour la liste selon la recherche en gardant, si possible, le choix actuel."""
        texte = self.recherche.get().strip().casefold()
        visibles = [(l, i) for l, i in self._tous if not texte or texte in l.casefold()]
        self._affiches = {l: i for l, i in visibles}
        if not visibles:
            self.menu.configure(values=["(aucun résultat)"])
            self.variable.set("(aucun résultat)")
        else:
            libelles = [l for l, _ in visibles]
            self.menu.configure(values=libelles)
            actuel = self.variable.get()
            if actuel in libelles:
                choix = actuel
            elif self.optionnel and len(libelles) > 1 and libelles[0] == SANS_ALCOOL:
                choix = libelles[1]               # alcool par défaut : le premier réel
            else:
                choix = libelles[0]
            self.variable.set(choix)
        self._maj_info()
        self.quand_change()

    def identifiant(self) -> Optional[int]:
        return self._affiches.get(self.variable.get())

    def produit(self):
        identifiant = self.identifiant()
        return produits_repo.obtenir(self.conn, self.type_code, identifiant) if identifiant else None

    def _choisi(self, _valeur: str) -> None:
        self._maj_info()
        self.quand_change()

    def _maj_info(self) -> None:
        p = self.produit()
        if p is None:
            self.info.configure(text="")
        elif self.type_code == "FLACON":
            self.info.configure(text=(
                f"{fmt_nombre(p['capacite_ml'])} ml · stock {fmt_nombre(p['quantite_stock'])} · "
                f"parfum {fmt_nombre(p['qnt_parfum_necessaire'])} ml · "
                f"alcool {fmt_nombre(p['qnt_alcool_necessaire'])} ml (auto)"))
        else:
            self.info.configure(text=f"stock {fmt_nombre(p['quantite_stock_ml'])} ml")


class VenteView(ctk.CTkFrame):
    COLONNES = [("flacon", "Flacon", 170, "w"), ("parfum", "Parfum", 170, "w"),
                ("ml", "Parfum (ml)", 90, "e"), ("alcool", "Alcool (ml)", 90, "e"),
                ("prix", "Prix", 120, "e"), ("benefice", "Bénéfice", 120, "e")]

    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        self.ligne: Optional[dict] = None        # combinaison en cours de composition
        self.panier: List[dict] = []
        self._clients: Dict[str, Optional[int]] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text="Vente", font=ctk.CTkFont(size=24, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        # ---------------------------- colonne gauche : choix des produits
        gauche = ctk.CTkScrollableFrame(self, fg_color="transparent")
        gauche.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(20, 8), pady=5)
        gauche.grid_columnconfigure(0, weight=1)

        cadre_client = ctk.CTkFrame(gauche)
        cadre_client.grid(row=0, column=0, sticky="ew", pady=4)
        ctk.CTkLabel(cadre_client, text="Client", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(side="left", padx=10, pady=8)
        self.var_client = ctk.StringVar(value=SANS_CLIENT)
        self.menu_client = ctk.CTkOptionMenu(cadre_client, variable=self.var_client,
                                             values=[SANS_CLIENT], width=200)
        self.menu_client.pack(side="left", padx=6)
        ctk.CTkButton(cadre_client, text="+ Nouveau", width=90, command=self._nouveau_client
                      ).pack(side="left", padx=6)

        self.choix_flacon = ChoixProduit(gauche, conn, "FLACON", "1. Flacon", self._recalculer)
        self.choix_flacon.grid(row=1, column=0, sticky="ew", pady=4)
        self.var_flacon_client = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(gauche, text="Le client apporte son flacon (coût du flacon non compté, stock inchangé)",
                        variable=self.var_flacon_client, command=self._recalculer
                        ).grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.choix_parfum = ChoixProduit(gauche, conn, "PARFUM", "2. Parfum", self._recalculer)
        self.choix_parfum.grid(row=3, column=0, sticky="ew", pady=4)
        self.choix_alcool = ChoixProduit(gauche, conn, "ALCOOL", "3. Alcool", self._recalculer,
                                         optionnel=True)
        self.choix_alcool.grid(row=4, column=0, sticky="ew", pady=4)

        # ---------------------------- colonne droite : prix et panier
        droite = ctk.CTkFrame(self)
        droite.grid(row=1, column=1, sticky="nsew", padx=(8, 20), pady=5)
        droite.grid_columnconfigure(0, weight=1)
        self.lbl_flacon = ctk.CTkLabel(droite, text="", anchor="w")
        self.lbl_parfum = ctk.CTkLabel(droite, text="", anchor="w")
        self.lbl_alcool = ctk.CTkLabel(droite, text="", anchor="w")
        self.lbl_cout = ctk.CTkLabel(droite, text="", anchor="w", font=ctk.CTkFont(weight="bold"))
        for i, lbl in enumerate((self.lbl_flacon, self.lbl_parfum, self.lbl_alcool, self.lbl_cout)):
            lbl.grid(row=i, column=0, sticky="w", padx=15, pady=(10 if i == 0 else 2, 2))
        ctk.CTkLabel(droite, text="PRIX DE VENTE (DA) — à saisir", font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=5, column=0, sticky="w", padx=15, pady=(14, 2))
        self.entree_total = ctk.CTkEntry(droite, height=46, font=ctk.CTkFont(size=22, weight="bold"),
                                         justify="right", placeholder_text="ex. 1500")
        self.entree_total.grid(row=6, column=0, sticky="ew", padx=15)
        self.entree_total.bind("<KeyRelease>", lambda _e: self._maj_benefice())
        self.entree_total.bind("<Return>", lambda _e: self._ajouter_au_panier())
        self.lbl_benefice = ctk.CTkLabel(droite, text="Bénéfice de cette combinaison : —", anchor="w",
                                         font=ctk.CTkFont(size=13))
        self.lbl_benefice.grid(row=7, column=0, sticky="w", padx=15, pady=8)
        self.lbl_alertes = ctk.CTkLabel(droite, text="", anchor="w", justify="left",
                                        text_color=ROUGE, font=ctk.CTkFont(weight="bold"))
        self.lbl_alertes.grid(row=8, column=0, sticky="w", padx=15, pady=(0, 6))
        ctk.CTkButton(droite, text="Ajouter au panier  (Entrée)", command=self._ajouter_au_panier
                      ).grid(row=9, column=0, sticky="ew", padx=15, pady=(4, 12))

        # ---------------------------- panier (bas)
        bas = ctk.CTkFrame(self, fg_color="transparent")
        bas.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(5, 15))
        bas.grid_columnconfigure(0, weight=1)
        self.tableau = Tableau(bas, self.COLONNES, hauteur=4)
        self.tableau.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 8))
        self.lbl_panier = ctk.CTkLabel(bas, text="Panier vide", anchor="w",
                                       font=ctk.CTkFont(size=15, weight="bold"))
        self.lbl_panier.grid(row=1, column=0, sticky="w")
        self.lbl_benefice_panier = ctk.CTkLabel(bas, text="BÉNÉFICE DU PANIER : —", anchor="w",
                                                font=ctk.CTkFont(size=18, weight="bold"),
                                                text_color="#6b7280")
        self.lbl_benefice_panier.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ctk.CTkButton(bas, text="Retirer la ligne", width=130, fg_color="#6b7280",
                      command=self._retirer_ligne).grid(row=1, column=1, padx=4)
        ctk.CTkButton(bas, text="Tout effacer", width=120, fg_color=ROUGE, hover_color="#b91c1c",
                      command=self._tout_effacer).grid(row=1, column=2, padx=4)
        ctk.CTkButton(bas, text="VALIDER LA VENTE", width=200, height=40, fg_color=VERT,
                      hover_color="#15803d", font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._valider).grid(row=1, column=3, padx=(10, 0))

    # ------------------------------------------------------------ rafraîchir
    def rafraichir(self) -> None:
        self._charger_clients()
        self.choix_flacon.recharger()
        self.choix_parfum.recharger()
        self.choix_alcool.recharger()
        self._recalculer()

    def _charger_clients(self, selection: Optional[int] = None) -> None:
        self._clients = {SANS_CLIENT: None}
        for c in clients_service.lister_clients(self.conn):
            libelle = c["nom"] + (f" ({c['telephone']})" if c["telephone"] else "")
            self._clients[libelle] = c["id"]
        self.menu_client.configure(values=list(self._clients))
        actuel = self.var_client.get()
        cible = next((l for l, i in self._clients.items() if i == selection and i is not None), None)
        self.var_client.set(cible or (actuel if actuel in self._clients else SANS_CLIENT))

    def _nouveau_client(self) -> None:
        DialogueClient(self.winfo_toplevel(), self.conn, lambda ident: self._charger_clients(ident))

    # --------------------------------------------------------------- calculs
    def _recalculer(self) -> None:
        """Calcule les coûts de la combinaison choisie (le prix de vente est saisi, pas calculé)."""
        fid, pid = self.choix_flacon.identifiant(), self.choix_parfum.identifiant()
        self.ligne = None
        if fid is None or pid is None:
            for lbl in (self.lbl_flacon, self.lbl_parfum, self.lbl_alcool, self.lbl_cout, self.lbl_alertes):
                lbl.configure(text="")
            self.lbl_benefice.configure(text="Bénéfice de cette combinaison : —", text_color="#6b7280")
            return
        try:
            ligne = vente_service.calculer_ligne(
                self.conn, fid, pid, self.choix_alcool.identifiant(), self.var_flacon_client.get())
        except ErreurMetier as erreur:
            self.lbl_alertes.configure(text=str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Calcul vente")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        self.ligne = ligne
        self.lbl_flacon.configure(
            text="Coût du flacon (apporté par le client) : " + fmt_prix(0) if ligne["flacon_client"]
            else f"Coût du flacon : {fmt_prix(ligne['cout_flacon'])}")
        self.lbl_parfum.configure(
            text=f"Coût du parfum ({fmt_nombre(ligne['qnt_parfum_ml'])} ml) : {fmt_prix(ligne['cout_parfum'])}")
        self.lbl_alcool.configure(
            text=f"Coût de l'alcool ({fmt_nombre(ligne['qnt_alcool_ml'])} ml) : {fmt_prix(ligne['cout_alcool'])}")
        self.lbl_cout.configure(text=f"COÛT DE REVIENT : {fmt_prix(ligne['cout_total'])}")
        self.lbl_alertes.configure(text="\n".join("⚠ " + a for a in ligne["avertissements"]))
        self._maj_benefice()

    def _total_saisi(self) -> Optional[float]:
        try:
            return parse_nombre(self.entree_total.get(), "Total vente", minimum=0)
        except ErreurMetier:
            return None

    def _maj_benefice(self) -> None:
        total = self._total_saisi()
        if self.ligne is None or total is None:
            self.lbl_benefice.configure(text="Bénéfice de cette combinaison : —", text_color="#6b7280")
            return
        benefice = total - self.ligne["cout_total"]
        self.lbl_benefice.configure(text=f"Bénéfice de cette combinaison : {fmt_prix(benefice)}",
                                    text_color=VERT if benefice >= 0 else ROUGE)

    # ---------------------------------------------------------------- panier
    def _ajouter_au_panier(self) -> bool:
        if self.ligne is None:
            afficher_info(self, "Choisissez un flacon et un parfum.")
            return False
        try:
            total = parse_nombre(self.entree_total.get(), "Prix de vente", minimum=0)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            self.entree_total.focus_set()
            return False
        ligne = dict(self.ligne)
        vente_service.appliquer_prix_final(ligne, total)
        self.panier.append(ligne)
        self._afficher_panier()
        self.entree_total.delete(0, "end")       # prêt pour l'article suivant
        self._maj_benefice()
        return True

    def _afficher_panier(self) -> None:
        self.tableau.vider()
        for i, l in enumerate(self.panier):
            nom_flacon = l["flacon_nom"] + (" (client)" if l["flacon_client"] else "")
            self.tableau.ajouter((nom_flacon, l["parfum_nom"], fmt_nombre(l["qnt_parfum_ml"]),
                                  fmt_nombre(l["qnt_alcool_ml"]), fmt_prix(l["prix_final"]),
                                  fmt_prix(l["benefice"])), iid=str(i))
        if self.panier:
            total = sum(l["prix_final"] for l in self.panier)
            benefice = sum(l["benefice"] for l in self.panier)
            self.lbl_panier.configure(
                text=f"{len(self.panier)} article(s) — TOTAL DU PANIER : {fmt_prix(total)}")
            self.lbl_benefice_panier.configure(
                text=f"BÉNÉFICE DU PANIER : {fmt_prix(benefice)}",
                text_color=VERT if benefice >= 0 else ROUGE)
        else:
            self.lbl_panier.configure(text="Panier vide")
            self.lbl_benefice_panier.configure(text="BÉNÉFICE DU PANIER : —", text_color="#6b7280")

    def _retirer_ligne(self) -> None:
        iid = self.tableau.selection()
        if iid is None:
            afficher_info(self, "Sélectionnez une ligne du panier.")
            return
        self.panier.pop(int(iid))
        self._afficher_panier()

    def _tout_effacer(self) -> None:
        if self.panier and not confirmer(self, "Annuler cette vente et vider le panier ?"):
            return
        self.panier.clear()
        self._afficher_panier()
        self.var_flacon_client.set(False)
        self.entree_total.delete(0, "end")
        self.recherche_vider()
        self.rafraichir()

    def recherche_vider(self) -> None:
        for choix in (self.choix_flacon, self.choix_parfum, self.choix_alcool):
            choix.recherche.delete(0, "end")

    # ------------------------------------------------------------ validation
    def _valider(self) -> None:
        if not self.panier and not self._ajouter_au_panier():
            return
        saisies = [{"flacon_id": l["flacon_id"], "parfum_id": l["parfum_id"],
                    "alcool_id": l["alcool_id"], "flacon_client": l["flacon_client"],
                    "prix_final": l["prix_final"]} for l in self.panier]
        client_id = self._clients.get(self.var_client.get())
        try:
            resultat = vente_service.valider_vente(self.conn, saisies, client_id)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Validation vente")
            afficher_erreur(self, f"La vente n'a pas pu être enregistrée : {erreur}")
            return
        message = (f"Vente n°{resultat['vente_id']} enregistrée.\n\n"
                   f"Total : {fmt_prix(resultat['total'])}\nBénéfice : {fmt_prix(resultat['benefice'])}")
        if resultat["avertissements"]:
            message += "\n\n⚠ " + "\n⚠ ".join(resultat["avertissements"])
            afficher_avertissement(self, message)
        else:
            afficher_info(self, message, "Vente enregistrée")
        self.panier.clear()
        self._afficher_panier()
        self.var_flacon_client.set(False)
        self.rafraichir()
