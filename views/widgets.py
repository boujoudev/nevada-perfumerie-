"""Composants réutilisables : tableau, formulaire produit, boîtes de message, fenêtre modale."""

from __future__ import annotations

from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import customtkinter as ctk

from models.catalogue import CATALOGUE
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_brut, fmt_nombre, parse_nombre
from views.style import GRIS, ROUGE, VERT


# ----------------------------------------------------------------- messages
def afficher_erreur(parent, message: str) -> None:
    messagebox.showerror("Erreur", message, parent=parent)


def afficher_info(parent, message: str, titre: str = "Information") -> None:
    messagebox.showinfo(titre, message, parent=parent)


def afficher_avertissement(parent, message: str) -> None:
    messagebox.showwarning("Attention", message, parent=parent)


def confirmer(parent, message: str, titre: str = "Confirmation") -> bool:
    return messagebox.askyesno(titre, message, parent=parent)


# ------------------------------------------------------------------ tableau
class Tableau(ctk.CTkFrame):
    """Tableau avec barre de défilement. colonnes = [(cle, titre, largeur, ancrage), ...]."""

    def __init__(self, master, colonnes: Sequence[Tuple[str, str, int, str]], hauteur: int = 12):
        super().__init__(master)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.arbre = ttk.Treeview(self, columns=[c[0] for c in colonnes], show="headings",
                                  height=hauteur, selectmode="browse")
        for cle, titre, largeur, ancrage in colonnes:
            self.arbre.heading(cle, text=titre)
            self.arbre.column(cle, width=largeur, anchor=ancrage, stretch=True)
        barre = ttk.Scrollbar(self, orient="vertical", command=self.arbre.yview)
        self.arbre.configure(yscrollcommand=barre.set)
        self.arbre.grid(row=0, column=0, sticky="nsew")
        barre.grid(row=0, column=1, sticky="ns")
        self.arbre.tag_configure("bas", foreground=ROUGE)
        self.arbre.tag_configure("annulation", foreground="#9ca3af")

    def vider(self) -> None:
        self.arbre.delete(*self.arbre.get_children())

    def ajouter(self, valeurs: Sequence, iid: Optional[str] = None, tags: Sequence[str] = ()) -> None:
        self.arbre.insert("", "end", iid=iid, values=list(valeurs), tags=tuple(tags))

    def selectionner(self, iid: str) -> None:
        """Sélectionne (et rend visible) la ligne portant cet identifiant."""
        if iid in self.arbre.get_children():
            self.arbre.selection_set(iid)
            self.arbre.see(iid)

    def selection(self) -> Optional[str]:
        choix = self.arbre.selection()
        return choix[0] if choix else None

    def lier_double_clic(self, rappel: Callable[[], None]) -> None:
        def _sur_double_clic(evenement):
            ligne = self.arbre.identify_row(evenement.y)
            if ligne:
                self.arbre.selection_set(ligne)
                rappel()
        self.arbre.bind("<Double-1>", _sur_double_clic)


# ------------------------------------------------------------- formulaire produit
class FormulaireProduit(ctk.CTkFrame):
    """Formulaire généré automatiquement à partir du catalogue (un champ par colonne).

    Pour un flacon, la quantité d'alcool est affichée en direct : capacité − parfum.
    """

    def __init__(self, master, type_code: str):
        super().__init__(master, fg_color="transparent")
        self.type = CATALOGUE[type_code]
        self.entrees: Dict[str, ctk.CTkEntry] = {}
        self.lbl_alcool: Optional[ctk.CTkLabel] = None
        self.grid_columnconfigure(1, weight=1)
        ligne = 0
        for champ in self.type.champs:
            ctk.CTkLabel(self, text=champ.libelle, anchor="w").grid(
                row=ligne, column=0, padx=(10, 12), pady=6, sticky="w")
            entree = ctk.CTkEntry(self, width=300)
            entree.grid(row=ligne, column=1, padx=10, pady=6, sticky="ew")
            self.entrees[champ.cle] = entree
            ligne += 1
            if type_code == "FLACON" and champ.cle == "qnt_parfum_necessaire":
                ctk.CTkLabel(self, text="Alcool par flacon (ml)", anchor="w").grid(
                    row=ligne, column=0, padx=(10, 12), pady=6, sticky="w")
                self.lbl_alcool = ctk.CTkLabel(self, text="", anchor="w",
                                               font=ctk.CTkFont(weight="bold"))
                self.lbl_alcool.grid(row=ligne, column=1, padx=10, pady=6, sticky="w")
                ligne += 1
        if self.lbl_alcool is not None:
            for cle in ("capacite_ml", "qnt_parfum_necessaire"):
                self.entrees[cle].bind("<KeyRelease>", lambda _e: self._maj_alcool())
        self.vider()

    def _maj_alcool(self) -> None:
        """Affiche l'alcool automatique = capacité − parfum."""
        if self.lbl_alcool is None:
            return
        try:
            capacite = parse_nombre(self.entrees["capacite_ml"].get(), "Capacité", strictement_positif=True)
            parfum = parse_nombre(self.entrees["qnt_parfum_necessaire"].get(), "Parfum", minimum=0)
        except ErreurMetier:
            self.lbl_alcool.configure(text="automatique (capacité − parfum)", text_color=GRIS)
            return
        if parfum > capacite:
            self.lbl_alcool.configure(text="⚠ le parfum dépasse la capacité du flacon", text_color=ROUGE)
        else:
            self.lbl_alcool.configure(text=f"{fmt_nombre(capacite - parfum)} ml  (automatique)",
                                      text_color=VERT)

    def vider(self) -> None:
        for champ in self.type.champs:
            entree = self.entrees[champ.cle]
            entree.delete(0, "end")
            if champ.defaut is not None:
                entree.insert(0, champ.defaut)
        self.entrees["nom"].focus_set()
        self._maj_alcool()

    def remplir(self, ligne) -> None:
        for champ in self.type.champs:
            entree = self.entrees[champ.cle]
            entree.delete(0, "end")
            entree.insert(0, self.type.code_de(ligne) if champ.cle == "code" else fmt_brut(ligne[champ.cle]))
        self._maj_alcool()

    def valeurs(self) -> Dict[str, str]:
        return {cle: entree.get() for cle, entree in self.entrees.items()}


class FormulaireChamps(ctk.CTkFrame):
    """Formulaire générique : un champ de saisie par `Champ` (cosmétiques, utilisateurs...)."""

    def __init__(self, master, champs, largeur: int = 300):
        super().__init__(master, fg_color="transparent")
        self.champs = champs
        self.entrees: Dict[str, ctk.CTkEntry] = {}
        self.grid_columnconfigure(1, weight=1)
        for ligne, champ in enumerate(champs):
            ctk.CTkLabel(self, text=champ.libelle, anchor="w").grid(
                row=ligne, column=0, padx=(10, 12), pady=6, sticky="w")
            entree = ctk.CTkEntry(self, width=largeur)
            entree.grid(row=ligne, column=1, padx=10, pady=6, sticky="ew")
            self.entrees[champ.cle] = entree
        self.vider()

    def vider(self) -> None:
        for champ in self.champs:
            entree = self.entrees[champ.cle]
            entree.delete(0, "end")
            if champ.defaut is not None:
                entree.insert(0, champ.defaut)

    def remplir(self, valeurs: dict) -> None:
        for champ in self.champs:
            entree = self.entrees[champ.cle]
            entree.delete(0, "end")
            entree.insert(0, fmt_brut(valeurs.get(champ.cle)))

    def valeurs(self) -> Dict[str, str]:
        return {cle: entree.get() for cle, entree in self.entrees.items()}


# -------------------------------------------------------------- fenêtre modale
class FenetreModale(ctk.CTkToplevel):
    """Fenêtre de dialogue centrée, au premier plan, qui bloque la fenêtre principale."""

    def __init__(self, master, titre: str, largeur: int, hauteur: int, lier_au_parent: bool = True):
        super().__init__(master)
        self.title(titre)
        self.resizable(False, False)
        if lier_au_parent:
            x = master.winfo_rootx() + max((master.winfo_width() - largeur) // 2, 0)
            y = master.winfo_rooty() + max((master.winfo_height() - hauteur) // 3, 0)
        else:  # parent caché (connexion) : centrage sur l'écran
            x = max((self.winfo_screenwidth() - largeur) // 2, 0)
            y = max((self.winfo_screenheight() - hauteur) // 3, 0)
        self.geometry(f"{largeur}x{hauteur}+{max(x, 0)}+{max(y, 0)}")
        if lier_au_parent:
            self.transient(master)
        self.after(150, self._activer)

    def _activer(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:  # la fenêtre a pu être fermée entre-temps
            pass


def ligne_boutons(parent, boutons: List[Tuple[str, Callable, Optional[str]]]) -> ctk.CTkFrame:
    """Barre de boutons alignés à droite : [(texte, commande, couleur ou None), ...]."""
    cadre = ctk.CTkFrame(parent, fg_color="transparent")
    for texte, commande, couleur in boutons:
        options = {"fg_color": couleur} if couleur else {}
        ctk.CTkButton(cadre, text=texte, command=commande, width=130, **options).pack(
            side="right", padx=6)
    return cadre
