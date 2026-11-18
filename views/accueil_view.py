"""Page d'accueil : le choix entre PARFUM et COSMÉTIQUE."""

from __future__ import annotations

import customtkinter as ctk

from services import utilisateurs_service
from utils.contexte import Contexte
from utils.ressources import charger_logo
from views.dialogues_commun import DialogueMotDePasse
from views.dialogues_utilisateurs import DialogueUtilisateurs
from views.session_ui import etat_session
from views.style import BLEU


class AccueilView(ctk.CTkFrame):
    def __init__(self, master, app, ctx: Contexte):
        super().__init__(master, fg_color="transparent")
        self.app, self.ctx = app, ctx
        centre = ctk.CTkFrame(self, fg_color="transparent")
        centre.place(relx=0.5, rely=0.47, anchor="center")
        self.logo = charger_logo(250)
        if self.logo is not None:
            ctk.CTkLabel(centre, text="", image=self.logo).pack(pady=(0, 10))
        else:
            ctk.CTkLabel(centre, text="NEVADA", font=ctk.CTkFont(size=34, weight="bold")).pack(pady=(0, 10))
        u = ctx.utilisateur
        ctk.CTkLabel(centre, text=f"Bonjour {u['nom']}",
                     font=ctk.CTkFont(size=20, weight="bold")).pack()
        ctk.CTkLabel(centre, text=utilisateurs_service.LIBELLES_ROLE[u["role"]], text_color="#6b7280").pack()
        self.lbl_session = ctk.CTkLabel(centre, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_session.pack(pady=(6, 14))

        gros = ctk.CTkFrame(centre, fg_color="transparent")
        gros.pack(pady=6)
        ctk.CTkButton(gros, text="🌸\nPARFUM", width=300, height=170, font=ctk.CTkFont(size=26, weight="bold"),
                      command=lambda: app.ouvrir_module("PARFUM")).pack(side="left", padx=14)
        ctk.CTkButton(gros, text="🧴\nCOSMÉTIQUE", width=300, height=170, font=ctk.CTkFont(size=26, weight="bold"),
                      command=lambda: app.ouvrir_module("COSMETIQUE")).pack(side="left", padx=14)

        petits = ctk.CTkFrame(centre, fg_color="transparent")
        petits.pack(pady=(24, 0))
        boutons = [("💰  Sessions de caisse", lambda: app.ouvrir_module("COSMETIQUE", "Session"), 200)]
        if ctx.peut("utilisateurs"):
            boutons.append(("👤  Utilisateurs", self._utilisateurs, 150))
        boutons += [("🔑  Mon mot de passe", self._mot_de_passe, 180),
                    ("↪  Changer d'utilisateur", app.deconnecter, 200)]
        for texte, commande, largeur in boutons:
            ctk.CTkButton(petits, text=texte, width=largeur, fg_color="#475569", hover_color="#334155",
                          command=commande).pack(side="left", padx=5)
        ctk.CTkButton(petits, text="Quitter", width=100, fg_color="#dc2626", hover_color="#b91c1c",
                      command=app.quitter).pack(side="left", padx=5)

    def rafraichir(self) -> None:
        texte, couleur, _ = etat_session(self.ctx)
        self.lbl_session.configure(text=texte, text_color=couleur)

    def _utilisateurs(self) -> None:
        DialogueUtilisateurs(self.winfo_toplevel(), self.ctx.conn)

    def _mot_de_passe(self) -> None:
        DialogueMotDePasse(self.winfo_toplevel(), self.ctx.conn, self.ctx.utilisateur_id, self.ctx.utilisateur["nom"])
