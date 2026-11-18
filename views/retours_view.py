"""Écran des RETOURS (cosmétique) : retour sur ticket ou retour libre, remboursement en espèces."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import List, Optional

import customtkinter as ctk

from services import caisse_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_prix, parse_nombre
from views.dialogues_commun import DialogueNombre
from views.session_ui import assurer_session, etat_session, ouvrir_ma_session
from views.style import ROUGE, VERT
from views.widgets import Tableau, afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)

MODE_TICKET = "Retour sur un ticket"
MODE_LIBRE = "Retour libre (sans ticket)"

COL_TICKETS = [("id", "N°", 60, "center"), ("date", "Date", 140, "center"), ("employe", "Employé", 120, "w"),
               ("articles", "Lignes", 60, "e"), ("total", "Total", 110, "e"), ("statut", "Statut", 90, "center")]
COL_LIGNES = [("designation", "Désignation", 300, "w"), ("vendu", "Vendu", 70, "e"),
              ("retourne", "Déjà rendu", 90, "e"), ("prix", "Prix payé / unité", 130, "e")]
COL_SUGGESTIONS = [("code", "ID", 90, "center"), ("nom", "Produit", 330, "w"), ("prix", "Prix", 110, "e"),
                   ("stock", "Stock", 70, "e")]
COL_RETOUR = [("designation", "Désignation", 300, "w"), ("qte", "Qté", 60, "e"), ("pu", "Remboursé / unité", 140, "e"),
              ("total", "Total", 110, "e"), ("stock", "Produit", 130, "center")]


class RetoursView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection, ctx: Contexte):
        super().__init__(master, fg_color="transparent")
        self.conn, self.ctx = conn, ctx
        self.ticket_id: Optional[int] = None          # ticket des lignes en cours de retour (None = retour libre)
        self.lignes_retour: List[dict] = []
        self._ticket_affiche: Optional[int] = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        entete = ctk.CTkFrame(self, fg_color="transparent")
        entete.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 5))
        ctk.CTkLabel(entete, text="Retours clients", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        self.btn_session = ctk.CTkButton(entete, text="Ouvrir ma session", width=170, command=self._ouvrir_session)
        self.btn_session.pack(side="right")
        self.lbl_session = ctk.CTkLabel(entete, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_session.pack(side="right", padx=12)

        self.menu_mode = ctk.CTkOptionMenu(self, values=[MODE_TICKET, MODE_LIBRE], width=260, command=self._changer_mode)
        self.menu_mode.grid(row=1, column=0, sticky="w", padx=20, pady=4)

        cadre = ctk.CTkFrame(self, fg_color="transparent")
        cadre.grid(row=2, column=0, sticky="ew", padx=20)
        cadre.grid_columnconfigure(0, weight=1)
        self._construire_panneau_ticket(cadre)
        self._construire_panneau_libre(cadre)
        self.panneau_libre.grid_remove()

        self.tableau_retour = Tableau(self, COL_RETOUR, hauteur=6)
        self.tableau_retour.grid(row=3, column=0, sticky="nsew", padx=20, pady=6)
        bas = ctk.CTkFrame(self, fg_color="transparent")
        bas.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 14))
        self.lbl_total = ctk.CTkLabel(bas, text="À REMBOURSER : " + fmt_prix(0), font=ctk.CTkFont(size=20, weight="bold"))
        self.lbl_total.pack(side="left")
        ctk.CTkButton(bas, text="VALIDER LE RETOUR", width=210, height=42, fg_color=VERT, hover_color="#15803d",
                      font=ctk.CTkFont(weight="bold"), command=self._valider).pack(side="right", padx=3)
        ctk.CTkButton(bas, text="Vider", width=80, fg_color=ROUGE, hover_color="#b91c1c",
                      command=self._vider).pack(side="right", padx=3)
        ctk.CTkButton(bas, text="Retirer", width=90, fg_color="#475569", command=self._retirer).pack(side="right", padx=3)
        ctk.CTkButton(bas, text="Remis en stock ⇄ Perte", width=190, fg_color="#475569",
                      command=self._basculer_stock).pack(side="right", padx=3)
        self.btn_prix = ctk.CTkButton(bas, text="Prix remboursé…", width=150, fg_color="#475569", command=self._modifier_prix)
        self.btn_prix.pack(side="right", padx=3)

    # ------------------------------------------------------------- panneaux
    def _construire_panneau_ticket(self, parent) -> None:
        self.panneau_ticket = ctk.CTkFrame(parent)
        self.panneau_ticket.grid(row=0, column=0, sticky="ew")
        self.panneau_ticket.grid_columnconfigure(0, weight=1)
        barre = ctk.CTkFrame(self.panneau_ticket, fg_color="transparent")
        barre.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self.entree_numero = ctk.CTkEntry(barre, width=200, placeholder_text="N° de ticket (vide = les derniers)")
        self.entree_numero.pack(side="left", padx=4)
        self.entree_numero.bind("<Return>", lambda _e: self._charger_tickets())
        ctk.CTkButton(barre, text="Rechercher", width=110, command=self._charger_tickets).pack(side="left", padx=4)
        ctk.CTkButton(barre, text="Voir les articles du ticket", width=200, command=self._voir_lignes).pack(side="left", padx=4)
        self.tableau_tickets = Tableau(self.panneau_ticket, COL_TICKETS, hauteur=4)
        self.tableau_tickets.grid(row=1, column=0, sticky="ew", padx=8, pady=2)
        self.tableau_tickets.lier_double_clic(self._voir_lignes)
        self.tableau_lignes = Tableau(self.panneau_ticket, COL_LIGNES, hauteur=3)
        self.tableau_lignes.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        barre2 = ctk.CTkFrame(self.panneau_ticket, fg_color="transparent")
        barre2.grid(row=3, column=0, sticky="ew", padx=8, pady=(2, 8))
        ctk.CTkLabel(barre2, text="Quantité rendue").pack(side="left", padx=4)
        self.entree_qte = ctk.CTkEntry(barre2, width=70, justify="center")
        self.entree_qte.pack(side="left", padx=4)
        self.entree_qte.insert(0, "1")
        self.var_remis = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(barre2, text="Produit intact : remettre en stock", variable=self.var_remis
                        ).pack(side="left", padx=14)
        ctk.CTkButton(barre2, text="Ajouter au retour", width=160, command=self._ajouter_ligne_ticket).pack(side="left", padx=4)

    def _construire_panneau_libre(self, parent) -> None:
        self.panneau_libre = ctk.CTkFrame(parent)
        self.panneau_libre.grid(row=0, column=0, sticky="ew")
        self._quantite_en_attente = 1
        ctk.CTkLabel(self.panneau_libre, text=("Retour sans ticket : scannez le produit, ou tapez son nom / ID "
                                               "(la liste s'affiche pendant la frappe). Remboursement au prix de "
                                               "vente actuel (modifiable)."),
                     text_color="#6b7280", wraplength=900, justify="left").pack(anchor="w", padx=12, pady=(10, 2))
        ligne = ctk.CTkFrame(self.panneau_libre, fg_color="transparent")
        ligne.pack(fill="x", padx=8, pady=8)
        self.entree_libre = ctk.CTkEntry(ligne, height=42, width=420, font=ctk.CTkFont(size=16),
                                         placeholder_text="Code-barres, nom ou ID — Entrée")
        self.entree_libre.pack(side="left", padx=4)
        self.entree_libre.bind("<Return>", lambda _e: self._sur_entree_libre())
        self.entree_libre.bind("<KeyRelease>", lambda e: self._maj_suggestions(e))
        self.entree_libre.bind("<Down>", lambda _e: self._aller_aux_suggestions())
        self.entree_libre.bind("<Escape>", lambda _e: self._vider_saisie_libre())
        ctk.CTkButton(ligne, text="Ajouter au retour", width=160, command=self._sur_entree_libre).pack(side="left", padx=4)
        self.var_remis_libre = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(ligne, text="Produit intact : remettre en stock", variable=self.var_remis_libre
                        ).pack(side="left", padx=14)
        # liste des produits trouvés (comme dans la caisse)
        self.suggestions = Tableau(self.panneau_libre, COL_SUGGESTIONS, hauteur=4)
        self.suggestions.pack(fill="x", padx=12, pady=(0, 10))
        self.suggestions.pack_forget()
        self.suggestions.lier_double_clic(self._ajouter_suggestion)
        self.suggestions.arbre.bind("<Return>", lambda _e: self._ajouter_suggestion())

    # ---------------------------------------------------------------- session
    def _maj_bandeau(self) -> None:
        texte, couleur, besoin = etat_session(self.ctx)
        self.lbl_session.configure(text=texte, text_color=couleur)
        if besoin:
            self.btn_session.pack(side="right")
        else:
            self.btn_session.pack_forget()

    def _ouvrir_session(self) -> None:
        ouvrir_ma_session(self.ctx, self, lambda _id: self._maj_bandeau())

    def rafraichir(self) -> None:
        self._maj_bandeau()
        self._charger_tickets()

    # ------------------------------------------------------------------- mode
    def _changer_mode(self, mode: str) -> None:
        if self.lignes_retour and not confirmer(self, "La liste de retour en cours sera vidée. Continuer ?"):
            self.menu_mode.set(MODE_LIBRE if mode == MODE_TICKET else MODE_TICKET)
            return
        self._vider()
        if mode == MODE_TICKET:
            self.panneau_libre.grid_remove()
            self.panneau_ticket.grid()
        else:
            self.panneau_ticket.grid_remove()
            self.panneau_libre.grid()
        self.btn_prix.configure(state="normal" if mode == MODE_LIBRE else "disabled")

    # ---------------------------------------------------------- retour ticket
    def _charger_tickets(self) -> None:
        texte = self.entree_numero.get().strip()
        numero = int(texte) if texte.isdigit() else None
        self.tableau_tickets.vider()
        for t in caisse_service.lister_tickets(self.conn, numero=numero):
            self.tableau_tickets.ajouter(
                (t["id"], fmt_datetime(t["date_ticket"]), t["utilisateur_nom"], t["nb_lignes"], fmt_prix(t["total"]),
                 "Annulé" if t["statut"] == "ANNULE" else "Valide"), iid=str(t["id"]),
                tags=("annulation",) if t["statut"] == "ANNULE" else ())

    def _voir_lignes(self) -> None:
        iid = self.tableau_tickets.selection()
        if not iid:
            afficher_info(self, "Sélectionnez un ticket dans la liste.")
            return
        self._afficher_lignes(int(iid))

    def _afficher_lignes(self, ticket_id: int) -> None:
        self.tableau_lignes.vider()
        self._ticket_affiche = ticket_id
        for l in caisse_service.lignes_du_ticket(self.conn, ticket_id):
            self.tableau_lignes.ajouter((l["designation"], l["quantite"], l["quantite_retournee"],
                                         fmt_prix(l["total_ligne"] / l["quantite"])), iid=str(l["id"]))

    def _ajouter_ligne_ticket(self) -> None:
        ligne_id = self.tableau_lignes.selection()
        if not ligne_id:
            afficher_info(self, "Sélectionnez d'abord l'article rendu dans la liste du ticket.")
            return
        try:
            quantite = parse_nombre(self.entree_qte.get(), "Quantité rendue", minimum=1, entier=True,
                                    strictement_positif=True)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        source = next((l for l in caisse_service.lignes_du_ticket(self.conn, self._ticket_affiche)
                       if l["id"] == int(ligne_id)), None)
        if source is None:
            return
        deja = sum(l["quantite"] for l in self.lignes_retour if l.get("ligne_ticket_id") == source["id"])
        reste = source["quantite"] - source["quantite_retournee"] - deja
        if quantite > reste:
            afficher_erreur(self, f"« {source['designation']} » : il ne reste que {reste} article(s) à rendre.")
            return
        if self.lignes_retour and self.ticket_id != self._ticket_affiche:
            afficher_erreur(self, "Un retour ne peut concerner qu'un seul ticket : validez ou videz la liste d'abord.")
            return
        self.ticket_id = self._ticket_affiche
        self.lignes_retour.append({
            "ligne_ticket_id": source["id"], "produit_id": source["produit_id"], "designation": source["designation"],
            "quantite": quantite, "unitaire": round(source["total_ligne"] / source["quantite"], 2),
            "remis_en_stock": bool(self.var_remis.get())})
        self._afficher_retour()

    # ------------------------------------------------------------ retour libre
    def _vider_saisie_libre(self) -> None:
        self.entree_libre.delete(0, "end")
        self.suggestions.pack_forget()

    def _maj_suggestions(self, evenement=None) -> None:
        """Liste des produits pendant la frappe (pas pour un scan de code-barres)."""
        if evenement is not None and getattr(evenement, "keysym", "") in ("Return", "Down", "Up", "Escape", "Tab"):
            return
        texte = self.entree_libre.get().strip()
        if len(texte) < 2 or (texte.isdigit() and len(texte) >= 6):
            self.suggestions.pack_forget()
            return
        self._quantite_en_attente = 1
        try:
            resultats = caisse_service.rechercher(self.conn, texte, limite=8)
        except sqlite3.Error:
            return
        if resultats:
            self._remplir_suggestions(resultats)
        else:
            self.suggestions.pack_forget()

    def _remplir_suggestions(self, resultats: List[dict]) -> None:
        self.suggestions.vider()
        for p in resultats:
            self.suggestions.ajouter((p["code_affiche"], p["nom"], fmt_prix(p["prix_vente"]), p["stock"]),
                                     iid=str(p["id"]))
        self.suggestions.pack(fill="x", padx=12, pady=(0, 10))

    def _aller_aux_suggestions(self) -> None:
        if not self.suggestions.arbre.get_children():
            return
        if self.suggestions.selection() is None:
            self.suggestions.selectionner(self.suggestions.arbre.get_children()[0])
        self.suggestions.arbre.focus_set()

    def _ajouter_suggestion(self) -> None:
        iid = self.suggestions.selection()
        if not iid:
            return
        produit = caisse_service.obtenir(self.conn, int(iid))
        if produit is not None:
            self._ajouter_produit_libre(caisse_service.produit_dict(produit), self._quantite_en_attente)
        self._quantite_en_attente = 1
        self._vider_saisie_libre()
        self.entree_libre.focus_set()

    def _sur_entree_libre(self) -> None:
        """Entrée : scan / ID exact -> ajout direct ; un seul résultat -> ajout ; plusieurs -> la liste."""
        texte = self.entree_libre.get().strip()
        if not texte:
            return
        quantite = 1
        m = re.match(r"^(\d+)\s*[*xX]\s*(.+)$", texte)
        if m:
            quantite, texte = int(m.group(1)), m.group(2).strip()
        exact = caisse_service.trouver_exact(self.conn, texte)
        if exact is not None:
            self._ajouter_produit_libre(caisse_service.produit_dict(exact), quantite)
            self._vider_saisie_libre()
            return
        resultats = caisse_service.rechercher(self.conn, texte, limite=8)
        if len(resultats) == 1:
            self._ajouter_produit_libre(resultats[0], quantite)
            self._vider_saisie_libre()
        elif resultats:
            self._quantite_en_attente = quantite
            self._remplir_suggestions(resultats)
            self.suggestions.selectionner(str(resultats[0]["id"]))
            self._aller_aux_suggestions()
        else:
            afficher_info(self, f"Aucun produit trouvé pour « {texte} ».")

    def _ajouter_produit_libre(self, produit: dict, quantite: int = 1) -> None:
        self.ticket_id = None
        self.lignes_retour.append({
            "produit_id": produit["id"], "designation": produit["nom"], "quantite": quantite,
            "unitaire": produit["prix_vente"], "remis_en_stock": bool(self.var_remis_libre.get())})
        self._afficher_retour(selection=len(self.lignes_retour) - 1)

    # ------------------------------------------------------------ liste retour
    def _afficher_retour(self, selection: Optional[int] = None) -> None:
        self.tableau_retour.vider()
        total = 0.0
        for i, l in enumerate(self.lignes_retour):
            ligne_total = round(l["unitaire"] * l["quantite"], 2)
            total += ligne_total
            self.tableau_retour.ajouter((l["designation"], l["quantite"], fmt_prix(l["unitaire"]), fmt_prix(ligne_total),
                                         "Remis en stock" if l["remis_en_stock"] else "PERTE (abîmé)"), iid=str(i),
                                        tags=() if l["remis_en_stock"] else ("bas",))
        if selection is not None:
            self.tableau_retour.selectionner(str(selection))
        suffixe = f"   (ticket n°{self.ticket_id})" if self.ticket_id else ""
        self.lbl_total.configure(text=f"À REMBOURSER : {fmt_prix(round(total, 2))}{suffixe}")

    def _index(self) -> Optional[int]:
        iid = self.tableau_retour.selection()
        if iid is None or int(iid) >= len(self.lignes_retour):
            afficher_info(self, "Sélectionnez une ligne de la liste de retour.")
            return None
        return int(iid)

    def _retirer(self) -> None:
        i = self._index()
        if i is not None:
            self.lignes_retour.pop(i)
            if not self.lignes_retour:
                self.ticket_id = None
            self._afficher_retour()

    def _basculer_stock(self) -> None:
        i = self._index()
        if i is not None:
            self.lignes_retour[i]["remis_en_stock"] = not self.lignes_retour[i]["remis_en_stock"]
            self._afficher_retour(selection=i)

    def _modifier_prix(self) -> None:
        i = self._index()
        if i is None:
            return
        if self.ticket_id is not None:
            afficher_info(self, "Sur un ticket, le remboursement est toujours au prix réellement payé.")
            return

        def appliquer(valeur, i=i):
            self.lignes_retour[i]["unitaire"] = float(valeur)
            self._afficher_retour(selection=i)
        DialogueNombre(self.winfo_toplevel(), "Prix remboursé", "Prix remboursé par unité (DA)",
                       self.lignes_retour[i]["unitaire"], appliquer)

    def _vider(self) -> None:
        self.lignes_retour.clear()
        self.ticket_id = None
        self._afficher_retour()

    # -------------------------------------------------------------- validation
    def _valider(self) -> None:
        if not self.lignes_retour:
            afficher_info(self, "Ajoutez d'abord les articles rendus.")
            return
        if not assurer_session(self.ctx, self, lambda _id: self._maj_bandeau()):
            return
        total = round(sum(l["unitaire"] * l["quantite"] for l in self.lignes_retour), 2)
        if not confirmer(self, f"Rembourser {fmt_prix(total)} au client ?"):
            return
        lignes = [{"ligne_ticket_id": l.get("ligne_ticket_id"), "produit_id": l["produit_id"],
                   "quantite": l["quantite"], "remis_en_stock": l["remis_en_stock"],
                   **({} if l.get("ligne_ticket_id") else {"prix_rembourse_unitaire": l["unitaire"]})}
                  for l in self.lignes_retour]
        try:
            resultat = caisse_service.valider_retour(self.conn, lignes, self.ctx.utilisateur, self.ticket_id)
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Validation retour")
            afficher_erreur(self, f"Le retour n'a pas pu être enregistré : {erreur}")
            return
        afficher_info(self, f"Retour n°{resultat['retour_id']} enregistré.\n\nRendez au client : "
                            f"{fmt_prix(resultat['total_rembourse'])}", "Retour enregistré")
        self._vider()
        self.tableau_lignes.vider()
        self._charger_tickets()

    def panier_en_cours(self) -> bool:
        return bool(self.lignes_retour)
