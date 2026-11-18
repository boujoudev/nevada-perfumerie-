"""Écran de CAISSE (cosmétique) : scan, panier, quantités, remises, attente, encaissement."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import List, Optional

import customtkinter as ctk

from services import caisse_service, clients_service, session_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_nombre, fmt_prix, parse_nombre
from views.dialogues import DialogueClient
from views.dialogues_caisse import DialogueAttentes
from views.dialogues_commun import DialogueNombre, DialogueRemise
from views.session_ui import assurer_session, etat_session, ouvrir_ma_session
from views.style import ROUGE, VERT
from views.widgets import Tableau, afficher_avertissement, afficher_erreur, afficher_info, confirmer

journal = logging.getLogger(__name__)
SANS_CLIENT = "(sans client)"

COLONNES = [("designation", "Désignation", 330, "w"), ("qte", "Qté", 60, "e"), ("pu", "Prix unit.", 110, "e"),
            ("remise", "Remise", 100, "e"), ("total", "Total", 120, "e")]
COLONNES_SUGGESTIONS = [("code", "ID", 90, "center"), ("nom", "Produit", 330, "w"), ("prix", "Prix", 110, "e"),
                        ("stock", "Stock", 70, "e")]


class CaisseView(ctk.CTkFrame):
    def __init__(self, master, conn: sqlite3.Connection, ctx: Contexte):
        super().__init__(master, fg_color="transparent")
        self.conn, self.ctx = conn, ctx
        self.panier: List[dict] = []
        self.remise_type: Optional[str] = None
        self.remise_valeur: float = 0.0
        self.calcul: Optional[dict] = None
        self._clients: dict = {}
        self._quantite_en_attente = 1
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ----- en-tête : titre + session
        entete = ctk.CTkFrame(self, fg_color="transparent")
        entete.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(15, 5))
        ctk.CTkLabel(entete, text="Caisse", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        self.btn_session = ctk.CTkButton(entete, text="Ouvrir ma session", width=170, command=self._ouvrir_session)
        self.btn_session.pack(side="right")
        self.lbl_session = ctk.CTkLabel(entete, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_session.pack(side="right", padx=12)

        # ----- saisie / scan
        self.saisie = ctk.CTkEntry(self, height=48, font=ctk.CTkFont(size=18), placeholder_text=(
            "Scanner un code-barres — ou taper un nom / ID puis Entrée   (ex. 3*6111… = 3 articles)"))
        self.saisie.grid(row=1, column=0, sticky="ew", padx=(20, 8), pady=4)
        self.saisie.bind("<Return>", lambda _e: self._sur_entree())
        self.saisie.bind("<KeyRelease>", lambda e: self._maj_suggestions(e))
        self.saisie.bind("<Down>", lambda _e: self._aller_aux_suggestions())
        self.saisie.bind("<Escape>", lambda _e: self._vider_saisie())

        self.suggestions = Tableau(self, COLONNES_SUGGESTIONS, hauteur=4)
        self.suggestions.grid(row=2, column=0, sticky="ew", padx=(20, 8), pady=2)
        self.suggestions.grid_remove()
        self.suggestions.lier_double_clic(self._ajouter_suggestion)
        self.suggestions.arbre.bind("<Return>", lambda _e: self._ajouter_suggestion())

        # ----- panier
        self.tableau = Tableau(self, COLONNES, hauteur=12)
        self.tableau.grid(row=3, column=0, sticky="nsew", padx=(20, 8), pady=4)
        barre = ctk.CTkFrame(self, fg_color="transparent")
        barre.grid(row=4, column=0, sticky="ew", padx=(20, 8), pady=(2, 12))
        for texte, commande, largeur in (
                ("＋1", lambda: self._delta(1), 50), ("－1", lambda: self._delta(-1), 50),
                ("Quantité (F2)", self._modifier_quantite, 120), ("Remise (F3)", self._remise_ligne, 110),
                ("Prix (F4)", self._modifier_prix, 90), ("Retirer (Suppr)", self._retirer, 120)):
            ctk.CTkButton(barre, text=texte, width=largeur, fg_color="#475569", hover_color="#334155",
                          command=commande).pack(side="left", padx=3)
        ctk.CTkButton(barre, text="Vider le panier", width=130, fg_color=ROUGE, hover_color="#b91c1c",
                      command=self._vider_panier).pack(side="right", padx=3)

        # ----- panneau de droite : total et paiement
        droite = ctk.CTkFrame(self, width=370)
        droite.grid(row=1, column=1, rowspan=4, sticky="ns", padx=(8, 20), pady=4)
        ctk.CTkLabel(droite, text="Client (facultatif)").pack(anchor="w", padx=15, pady=(12, 0))
        ligne_client = ctk.CTkFrame(droite, fg_color="transparent")
        ligne_client.pack(fill="x", padx=12)
        self.var_client = ctk.StringVar(value=SANS_CLIENT)
        self.menu_client = ctk.CTkOptionMenu(ligne_client, variable=self.var_client, values=[SANS_CLIENT], width=220)
        self.menu_client.pack(side="left", padx=3)
        ctk.CTkButton(ligne_client, text="+", width=36, command=self._nouveau_client).pack(side="left")
        self.lbl_sous_total = ctk.CTkLabel(droite, text="", anchor="w")
        self.lbl_sous_total.pack(fill="x", padx=15, pady=(14, 0))
        self.lbl_remises = ctk.CTkLabel(droite, text="", anchor="w", text_color="#b45309")
        self.lbl_remises.pack(fill="x", padx=15)
        ctk.CTkButton(droite, text="Remise sur le ticket…", width=200, fg_color="#475569", hover_color="#334155",
                      command=self._remise_globale).pack(pady=8)
        ctk.CTkLabel(droite, text="TOTAL À PAYER", font=ctk.CTkFont(size=13, weight="bold")).pack()
        self.lbl_total = ctk.CTkLabel(droite, text=fmt_prix(0), font=ctk.CTkFont(size=34, weight="bold"))
        self.lbl_total.pack(pady=(0, 6))
        ctk.CTkLabel(droite, text="Montant donné (DA)").pack(anchor="w", padx=15)
        self.entree_donne = ctk.CTkEntry(droite, height=42, font=ctk.CTkFont(size=20), justify="right")
        self.entree_donne.pack(fill="x", padx=15, pady=(2, 4))
        self.entree_donne.bind("<KeyRelease>", lambda _e: self._maj_monnaie())
        self.entree_donne.bind("<Return>", lambda _e: self._encaisser())
        self.lbl_monnaie = ctk.CTkLabel(droite, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self.lbl_monnaie.pack(pady=4)
        self.lbl_benefice = ctk.CTkLabel(droite, text="", text_color="#6b7280")
        self.lbl_benefice.pack()
        self.lbl_alertes = ctk.CTkLabel(droite, text="", text_color=ROUGE, wraplength=330, justify="left")
        self.lbl_alertes.pack(padx=12, pady=4)
        ctk.CTkButton(droite, text="ENCAISSER  (F12)", height=56, fg_color=VERT, hover_color="#15803d",
                      font=ctk.CTkFont(size=18, weight="bold"), command=self._encaisser).pack(fill="x", padx=15, pady=(8, 6))
        ligne_attente = ctk.CTkFrame(droite, fg_color="transparent")
        ligne_attente.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(ligne_attente, text="Mettre en attente (F8)", width=170, fg_color="#475569",
                      hover_color="#334155", command=self._mettre_en_attente).pack(side="left", padx=3)
        self.btn_attentes = ctk.CTkButton(ligne_attente, text="En attente (F9)", width=150, fg_color="#475569",
                                          hover_color="#334155", command=self._voir_attentes)
        self.btn_attentes.pack(side="left", padx=3)
        self.lbl_dernier = ctk.CTkLabel(droite, text="", text_color=VERT, wraplength=330, justify="left",
                                        font=ctk.CTkFont(weight="bold"))
        self.lbl_dernier.pack(padx=12, pady=(10, 12))

        for widget in (self.saisie, self.tableau.arbre, self.entree_donne):
            self._lier_raccourcis(widget)
        self._afficher_panier()

    # ------------------------------------------------------------ raccourcis
    def _lier_raccourcis(self, widget) -> None:
        for touche, action in (("<F2>", self._modifier_quantite), ("<F3>", self._remise_ligne),
                               ("<F4>", self._modifier_prix), ("<F8>", self._mettre_en_attente),
                               ("<F9>", self._voir_attentes), ("<F12>", self._encaisser),
                               ("<Delete>", self._retirer)):
            if touche == "<Delete>" and widget is self.saisie:
                continue                               # Suppr sert à effacer du texte dans le champ de scan
            widget.bind(touche, lambda _e, a=action: a())

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
        self._charger_clients()
        self.btn_attentes.configure(text=f"En attente ({len(caisse_service.lister_attentes(self.conn))}) F9")
        self.after(150, self.saisie.focus_set)
        if session_service.session_active(self.conn) is None:
            self.after(350, self._proposer_session)

    def _proposer_session(self) -> None:
        if session_service.session_active(self.conn) is None:
            ouvrir_ma_session(self.ctx, self, lambda _id: self._maj_bandeau())

    def _charger_clients(self) -> None:
        self._clients = {SANS_CLIENT: None}
        for c in clients_service.lister_clients(self.conn):
            self._clients[c["nom"] + (f" ({c['telephone']})" if c["telephone"] else "")] = c["id"]
        self.menu_client.configure(values=list(self._clients))
        if self.var_client.get() not in self._clients:
            self.var_client.set(SANS_CLIENT)

    def _nouveau_client(self) -> None:
        DialogueClient(self.winfo_toplevel(), self.conn, lambda _id: self._charger_clients())

    # --------------------------------------------------------------- saisie
    def _vider_saisie(self) -> None:
        self.saisie.delete(0, "end")
        self.suggestions.grid_remove()

    def _sur_entree(self) -> None:
        self._traiter_saisie(self.saisie.get())

    def _traiter_saisie(self, texte: str) -> None:
        """Scan (code-barres ou ID exact) -> ajout direct ; sinon recherche par nom."""
        texte = (texte or "").strip()
        if not texte:
            return
        quantite = 1
        multiplicateur = re.match(r"^(\d+)\s*[*xX]\s*(.+)$", texte)
        if multiplicateur:
            quantite, texte = int(multiplicateur.group(1)), multiplicateur.group(2).strip()
        try:
            exact = caisse_service.trouver_exact(self.conn, texte)
            if exact is not None:
                self._ajouter_produit(caisse_service.produit_dict(exact), quantite)
                self._vider_saisie()
                return
            resultats = caisse_service.rechercher(self.conn, texte, limite=8)
        except sqlite3.Error as erreur:
            journal.exception("Recherche caisse")
            afficher_erreur(self, f"Erreur de base de données : {erreur}")
            return
        if len(resultats) == 1:
            self._ajouter_produit(resultats[0], quantite)
            self._vider_saisie()
        elif resultats:
            self._quantite_en_attente = quantite
            self._remplir_suggestions(resultats)
            self.suggestions.selectionner(str(resultats[0]["id"]))
            self._aller_aux_suggestions()
        else:
            afficher_info(self, f"Aucun produit trouvé pour « {texte} ».\nVérifiez le code, ou ajoutez le produit "
                                "dans le stock.")

    def _maj_suggestions(self, evenement=None) -> None:
        if evenement is not None and getattr(evenement, "keysym", "") in ("Return", "Down", "Up", "Escape", "Tab"):
            return
        texte = self.saisie.get().strip()
        if len(texte) < 2 or (texte.isdigit() and len(texte) >= 6):        # un scan de code-barres : pas de liste
            self.suggestions.grid_remove()
            return
        self._quantite_en_attente = 1
        try:
            resultats = caisse_service.rechercher(self.conn, texte, limite=8)
        except sqlite3.Error:
            return
        if resultats:
            self._remplir_suggestions(resultats)
        else:
            self.suggestions.grid_remove()

    def _remplir_suggestions(self, resultats: List[dict]) -> None:
        self.suggestions.vider()
        for p in resultats:
            self.suggestions.ajouter((p["code_affiche"], p["nom"], fmt_prix(p["prix_vente"]), p["stock"]),
                                     iid=str(p["id"]), tags=("bas",) if p["stock"] <= 0 else ())
        self.suggestions.grid()

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
            self._ajouter_produit(caisse_service.produit_dict(produit), self._quantite_en_attente)
        self._quantite_en_attente = 1
        self._vider_saisie()
        self.saisie.focus_set()

    # --------------------------------------------------------------- panier
    def _ajouter_produit(self, produit: dict, quantite: int = 1) -> None:
        for i, ligne in enumerate(self.panier):                  # même produit, même prix, sans remise : on cumule
            if (ligne["produit_id"] == produit["id"] and ligne["prix_unitaire"] == produit["prix_vente"]
                    and not ligne.get("remise_type")):
                ligne["quantite"] += quantite
                self._afficher_panier(selection=i)
                return
        self.panier.append({
            "produit_id": produit["id"], "designation": produit["nom"],
            "code_barre": (produit["codes_barres"] or "").split(" ")[0], "quantite": quantite,
            "prix_catalogue": produit["prix_vente"], "prix_unitaire": produit["prix_vente"],
            "remise_type": None, "remise_valeur": 0, "stock": produit["quantite_stock"],
            "cout_unitaire": produit["prix_achat"]})
        self._afficher_panier(selection=len(self.panier) - 1)

    def _afficher_panier(self, selection: Optional[int] = None) -> None:
        try:
            self.calcul = caisse_service.calculer_panier(self.panier, self.remise_type, self.remise_valeur)
        except ErreurMetier as erreur:
            self.calcul = None
            afficher_erreur(self, str(erreur))
            return
        self.tableau.vider()
        for i, (ligne, c) in enumerate(zip(self.panier, self.calcul["lignes"])):
            prix = fmt_prix(ligne["prix_unitaire"])
            if abs(ligne["prix_unitaire"] - ligne["prix_catalogue"]) > 0.004:
                prix += " *"
            self.tableau.ajouter((ligne["designation"], ligne["quantite"], prix,
                                  fmt_prix(c["remise_ligne"]) if c["remise_ligne"] else "", fmt_prix(c["total_ligne"])),
                                 iid=str(i))
        if selection is not None:
            self.tableau.selectionner(str(selection))
        c = self.calcul
        self.lbl_total.configure(text=fmt_prix(c["total"]))
        self.lbl_sous_total.configure(text=f"Sous-total : {fmt_prix(c['sous_total'])}" if self.panier else "")
        self.lbl_remises.configure(text=f"Remises : -{fmt_prix(c['remise_totale'])}" if c["remise_totale"] else "")
        if self.ctx.peut("voir_prix_achat") and self.panier:
            cout = sum(l["quantite"] * l["cout_unitaire"] for l in self.panier)
            self.lbl_benefice.configure(text=f"Bénéfice du ticket : {fmt_prix(c['total'] - cout)}")
        else:
            self.lbl_benefice.configure(text="")
        manque = {}
        for l in self.panier:
            manque[l["produit_id"]] = manque.get(l["produit_id"], 0) + l["quantite"]
        alertes = [f"⚠ Stock insuffisant : {l['designation']} (stock {l['stock']})"
                   for l in {l["produit_id"]: l for l in self.panier}.values() if manque[l["produit_id"]] > l["stock"]]
        self.lbl_alertes.configure(text="\n".join(alertes))
        self._maj_monnaie()

    def _maj_monnaie(self) -> None:
        if self.calcul is None or not self.entree_donne.get().strip():
            self.lbl_monnaie.configure(text="")
            return
        try:
            donne = parse_nombre(self.entree_donne.get(), "Montant donné", minimum=0)
        except ErreurMetier:
            self.lbl_monnaie.configure(text="")
            return
        reste = round(donne - self.calcul["total"], 2)
        if reste < 0:
            self.lbl_monnaie.configure(text=f"Il manque {fmt_prix(-reste)}", text_color=ROUGE)
        else:
            self.lbl_monnaie.configure(text=f"Monnaie à rendre : {fmt_prix(reste)}", text_color=VERT)

    def _index(self) -> Optional[int]:
        """Ligne sélectionnée (ou la dernière ligne ajoutée à défaut)."""
        if not self.panier:
            return None
        iid = self.tableau.selection()
        return int(iid) if iid is not None and int(iid) < len(self.panier) else len(self.panier) - 1

    def _delta(self, delta: int) -> None:
        i = self._index()
        if i is None:
            return
        self.panier[i]["quantite"] = max(1, self.panier[i]["quantite"] + delta)
        self._afficher_panier(selection=i)

    def _modifier_quantite(self) -> None:
        i = self._index()
        if i is None:
            return
        DialogueNombre(self.winfo_toplevel(), "Quantité", f"Quantité pour « {self.panier[i]['designation']} »",
                       self.panier[i]["quantite"], lambda v, i=i: self._fixer(i, "quantite", int(v)),
                       entier=True, minimum=1, strict=True)

    def _modifier_prix(self) -> None:
        i = self._index()
        if i is None:
            return
        DialogueNombre(self.winfo_toplevel(), "Prix unitaire", f"Prix de « {self.panier[i]['designation']} » (DA)",
                       self.panier[i]["prix_unitaire"], lambda v, i=i: self._fixer(i, "prix_unitaire", float(v)))

    def _remise_ligne(self) -> None:
        i = self._index()
        if i is None:
            return
        ligne = self.panier[i]

        def appliquer(type_remise, valeur, i=i):
            self.panier[i]["remise_type"], self.panier[i]["remise_valeur"] = type_remise, valeur
            self._afficher_panier(selection=i)
        DialogueRemise(self.winfo_toplevel(), f"Remise sur « {ligne['designation']} »", appliquer,
                       (ligne.get("remise_type"), ligne.get("remise_valeur") or 0))

    def _fixer(self, i: int, cle: str, valeur) -> None:
        if i < len(self.panier):
            self.panier[i][cle] = valeur
            self._afficher_panier(selection=i)
            self.saisie.focus_set()

    def _retirer(self) -> None:
        i = self._index()
        if i is None:
            return
        self.panier.pop(i)
        self._afficher_panier(selection=min(i, len(self.panier) - 1) if self.panier else None)

    def _remise_globale(self) -> None:
        if not self.panier:
            afficher_info(self, "Le panier est vide.")
            return

        def appliquer(type_remise, valeur):
            self.remise_type, self.remise_valeur = type_remise, valeur
            self._afficher_panier()
        DialogueRemise(self.winfo_toplevel(), "Remise sur tout le ticket", appliquer,
                       (self.remise_type, self.remise_valeur))

    def _vider_panier(self) -> None:
        if self.panier and not confirmer(self, "Vider le panier ?"):
            return
        self._reinitialiser()

    def _reinitialiser(self) -> None:
        self.panier.clear()
        self.remise_type, self.remise_valeur = None, 0.0
        self.entree_donne.delete(0, "end")
        self._afficher_panier()
        self.saisie.focus_set()

    def panier_en_cours(self) -> bool:
        return bool(self.panier)

    # ------------------------------------------------------------ attente
    def _mettre_en_attente(self) -> None:
        if not self.panier:
            afficher_info(self, "Le panier est vide : rien à mettre en attente.")
            return
        try:
            caisse_service.mettre_en_attente(self.conn, self.ctx.utilisateur, self.panier, self.remise_type,
                                             self.remise_valeur)
        except (ErreurMetier, sqlite3.Error) as erreur:
            afficher_erreur(self, str(erreur))
            return
        self._reinitialiser()
        self.rafraichir()
        self.lbl_dernier.configure(text="Ticket mis en attente. Vous pouvez servir le client suivant.")

    def _voir_attentes(self) -> None:
        DialogueAttentes(self.winfo_toplevel(), self.ctx, self._reprendre_panier)

    def _reprendre_panier(self, donnees: dict) -> None:
        if self.panier:
            if not confirmer(self, "Le panier actuel sera REMPLACÉ par le ticket repris. Continuer ?\n"
                                   "(Sinon : annulez puis mettez le panier actuel en attente.)"):
                try:                                              # on remet le ticket repris de côté
                    caisse_service.mettre_en_attente(self.conn, self.ctx.utilisateur, donnees["lignes"],
                                                     donnees["remise_type"], donnees["remise_valeur"])
                except ErreurMetier:
                    pass
                self.rafraichir()
                return
        self.panier = donnees["lignes"]
        self.remise_type, self.remise_valeur = donnees["remise_type"], float(donnees["remise_valeur"] or 0)
        self._afficher_panier(selection=0 if self.panier else None)
        self.rafraichir()

    # --------------------------------------------------------- encaissement
    def _encaisser(self) -> None:
        if not self.panier:
            afficher_info(self, "Le panier est vide : scannez ou ajoutez un produit.")
            return
        if not assurer_session(self.ctx, self, lambda _id: self._maj_bandeau()):
            return
        try:
            resultat = caisse_service.valider_ticket(
                self.conn, self.panier, self.ctx.utilisateur, self._clients.get(self.var_client.get()),
                self.remise_type, self.remise_valeur, self.entree_donne.get())
        except ErreurMetier as erreur:
            afficher_erreur(self, str(erreur))
            return
        except sqlite3.Error as erreur:
            journal.exception("Encaissement")
            afficher_erreur(self, f"Le ticket n'a pas pu être enregistré : {erreur}")
            return
        self._reinitialiser()
        self.var_client.set(SANS_CLIENT)
        self._maj_bandeau()
        self.lbl_dernier.configure(
            text=f"✔ Ticket n°{resultat['ticket_id']} encaissé : {fmt_prix(resultat['total'])}\n"
                 f"Monnaie rendue : {fmt_prix(resultat['monnaie'])}")
        for message in resultat["avertissements"]:
            afficher_avertissement(self, message)
