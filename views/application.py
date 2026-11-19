"""Fenêtre principale : connexion -> accueil (Parfum / Cosmétique) -> modules."""

from __future__ import annotations

import logging
import sqlite3
import sys
from typing import Dict, Optional

import customtkinter as ctk

from database import connection as base
from repositories import logs_caisse_repo
from services import caisse_service, produits_service, utilisateurs_service
from utils import perf
from utils.contexte import Contexte
from utils.ressources import chemin_ressource
from views.accueil_view import AccueilView
from views.login_view import LoginView, PremierDemarrageView
from views.module_cosmetique import ModuleCosmetique
from views.module_parfum import ModuleParfum
from views.style import appliquer_style_tableaux
from views.widgets import afficher_avertissement, afficher_erreur, confirmer

journal = logging.getLogger(__name__)
INTERVALLE_SAUVEGARDE_MS = 30 * 60 * 1000


class Application(ctk.CTk):
    def __init__(self, conn: sqlite3.Connection, message_demarrage: Optional[str] = None):
        super().__init__()
        self.conn = conn
        self.message_demarrage = message_demarrage
        self.ctx = Contexte(conn, self)
        self.modules: Dict[str, ctk.CTkFrame] = {}
        self._vue = None
        self._vue_ephemere = False
        self.accueil: Optional[AccueilView] = None        # construit une fois par connexion
        self._alertes_faites: set = set()
        self.title("Nevada Parfumerie — Gestion")
        # La fenêtre s'adapte à l'écran (petits portables) au lieu de dépasser
        largeur = min(1320, max(self.winfo_screenwidth() - 60, 960))
        hauteur = min(800, max(self.winfo_screenheight() - 140, 600))
        self.geometry(f"{largeur}x{hauteur}+30+30")
        self.minsize(960, 600)
        self.withdraw()                                    # cachée jusqu'au démarrage
        self.report_callback_exception = self._erreur_inattendue
        self.protocol("WM_DELETE_WINDOW", self.quitter)
        appliquer_style_tableaux()
        self._appliquer_icone()
        self.conteneur = ctk.CTkFrame(self, fg_color="transparent")
        self.conteneur.pack(fill="both", expand=True)
        self.conteneur.grid_columnconfigure(0, weight=1)
        self.conteneur.grid_rowconfigure(0, weight=1)
        self.after(100, self._demarrer)

    def _appliquer_icone(self) -> None:
        """Icône de la fenêtre / barre des tâches (sans importance si elle échoue)."""
        try:
            if sys.platform.startswith("win"):
                ico = str(chemin_ressource("assets/icone.ico"))
                # CustomTkinter remet son icône par défaut ~200 ms après l'ouverture : on la remplace après
                self.after(300, lambda: self.iconbitmap(ico))
            else:
                import tkinter
                self._icone = tkinter.PhotoImage(file=str(chemin_ressource("assets/icone.png")))
                self.iconphoto(True, self._icone)
        except Exception:  # noqa: BLE001
            journal.warning("Icône de fenêtre non appliquée", exc_info=True)

    # --------------------------------------------------------------- démarrage
    def _demarrer(self) -> None:
        self.deiconify()
        if self.message_demarrage:
            afficher_avertissement(self, self.message_demarrage)
        if utilisateurs_service.a_des_utilisateurs(self.conn):
            self.afficher_login()
        else:
            self._montrer(PremierDemarrageView(self.conteneur, self, self.conn), ephemere=True)
        self.after(INTERVALLE_SAUVEGARDE_MS, self._sauvegarde_periodique)

    # -------------------------------------------------------------- navigation
    def _montrer(self, vue, ephemere: bool = False) -> None:
        """Affiche une vue ; la précédente est détruite (éphémère) ou simplement cachée (module)."""
        if self._vue is not None and self._vue is not vue:
            if self._vue_ephemere:
                self._vue.destroy()
            elif not perf.EMPILER:
                self._vue.grid_remove()
        self._vue, self._vue_ephemere = vue, ephemere
        vue.grid(row=0, column=0, sticky="nsew")
        if perf.EMPILER:
            vue.tkraise()
        if hasattr(vue, "rafraichir") and not isinstance(vue, (ModuleParfum, ModuleCosmetique)):
            vue.rafraichir()

    def afficher_login(self) -> None:
        self._montrer(LoginView(self.conteneur, self, self.conn), ephemere=True)

    def connecter(self, utilisateur) -> None:
        self.ctx.utilisateur = utilisateur
        try:
            logs_caisse_repo.ajouter(self.conn, "CONNEXION", utilisateur["id"], details=f"Connexion de {utilisateur['nom']}")
        except sqlite3.Error:
            journal.exception("Journal de connexion")
        self.afficher_accueil()

    def afficher_accueil(self) -> None:
        chrono = perf.Chrono("Accueil")
        if self.accueil is None:
            self.accueil = AccueilView(self.conteneur, self, self.ctx)
        chrono.etape("construction")
        self._montrer(self.accueil)
        chrono.etape("affichage")
        self.update_idletasks()
        chrono.etape("mise en page")
        chrono.fin()

    def ouvrir_module(self, nom: str, section: Optional[str] = None) -> None:
        """Ouvre le module PARFUM ou COSMETIQUE (créé à la première ouverture, puis conservé)."""
        chrono = perf.Chrono(f"Ouverture du module {nom}")
        if nom not in self.modules:
            fabrique = ModuleParfum if nom == "PARFUM" else ModuleCosmetique
            self.modules[nom] = fabrique(self.conteneur, self, self.ctx)
        chrono.etape("construction du module")
        module = self.modules[nom]
        self._montrer(module)
        chrono.etape("affichage")
        module.rafraichir_courant(section)
        chrono.etape("section")
        chrono.fin()
        if nom not in self._alertes_faites:
            self._alertes_faites.add(nom)
            self.after(500, lambda: self._notifier_stock_bas(nom))

    def _notifier_stock_bas(self, nom: str) -> None:
        """À la première ouverture d'un module, l'administrateur est prévenu des stocks bas."""
        if not self.ctx.est_admin:
            return
        try:
            if nom == "PARFUM":
                alertes = [f"• {a['code']} {a['nom']} : {a['stock_txt']}" for a in produits_service.produits_en_alerte(self.conn)]
            else:
                alertes = [f"• {a['code_affiche']} {a['nom']} : {a['stock']}" for a in caisse_service.produits_en_alerte(self.conn)]
        except sqlite3.Error:
            journal.exception("Alertes stock")
            return
        if alertes:
            if len(alertes) > 12:
                alertes = alertes[:12] + [f"… et {len(alertes) - 12} autre(s)"]
            afficher_avertissement(self, "Stock bas :\n\n" + "\n".join(alertes))

    # ------------------------------------------------------------ déconnexion
    def _paniers_en_cours(self) -> bool:
        return any(m.panier_en_cours() for m in self.modules.values())

    def deconnecter(self) -> None:
        if self._paniers_en_cours() and not confirmer(
                self, "Un panier ou un retour est en cours : il sera PERDU si vous changez d'utilisateur.\nContinuer ?"):
            return
        for module in self.modules.values():
            module.destroy()
        self.modules.clear()
        if self.accueil is not None:
            self.accueil.destroy()
            self.accueil = None
        self._alertes_faites.clear()
        if not self._vue_ephemere:
            self._vue = None                               # c'était un module (détruit ci-dessus)
        self.ctx.utilisateur = None
        self.afficher_login()

    # ----------------------------------------------------------------- vie
    def _sauvegarde_periodique(self) -> None:
        try:
            base.sauvegarder(self.conn, "auto")
        except (sqlite3.Error, OSError):
            journal.exception("Sauvegarde périodique")
        self.after(INTERVALLE_SAUVEGARDE_MS, self._sauvegarde_periodique)

    def quitter(self) -> None:
        if self._paniers_en_cours() and not confirmer(
                self, "Un panier ou un retour est en cours : il sera PERDU si vous quittez.\nQuitter quand même ?"):
            return
        try:
            base.sauvegarder(self.conn, "fermeture")
        except (sqlite3.Error, OSError):
            journal.exception("Sauvegarde à la fermeture")
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
        self.destroy()

    def _erreur_inattendue(self, type_erreur, valeur, trace) -> None:
        """Évite le crash : l'erreur est journalisée et l'utilisateur prévenu."""
        journal.error("Erreur inattendue", exc_info=(type_erreur, valeur, trace))
        try:
            afficher_erreur(self, "Une erreur inattendue s'est produite.\nVos données ne sont pas "
                                  f"affectées.\n\nDétail : {valeur}")
        except Exception:  # noqa: BLE001
            pass
