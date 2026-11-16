"""Couleurs et style commun de l'interface."""

from tkinter import ttk

ROUGE = "#dc2626"
VERT = "#16a34a"
BLEU = "#1d464a"          # vert Nevada (couleur du logo), utilisé comme couleur d'accent
VERT_CLAIR = "#dcebe8"
GRIS = "#6b7280"
POLICE = "Segoe UI"


def appliquer_theme_nevada() -> None:
    """Remplace le bleu par défaut de CustomTkinter par le vert du logo (boutons, listes, cases).

    Sans risque : si la structure du thème change dans une future version, on garde simplement le bleu.
    """
    try:
        import customtkinter as ctk

        reglages = {
            "CTkButton": {"fg_color": BLEU, "hover_color": "#2c5f65"},
            "CTkOptionMenu": {"fg_color": BLEU, "button_color": "#2c5f65", "button_hover_color": "#24505a"},
            "CTkCheckBox": {"fg_color": BLEU, "hover_color": "#2c5f65"},
            "CTkSegmentedButton": {"selected_color": BLEU, "selected_hover_color": "#2c5f65"},
            "CTkTabview": {"segmented_button_selected_color": BLEU,
                           "segmented_button_selected_hover_color": "#2c5f65"},
        }
        for widget, cles in reglages.items():
            for cle, valeur in cles.items():
                if widget in ctk.ThemeManager.theme and cle in ctk.ThemeManager.theme[widget]:
                    ctk.ThemeManager.theme[widget][cle] = [valeur, valeur]
    except Exception:  # noqa: BLE001
        pass


def appliquer_style_tableaux() -> None:
    """Style des tableaux (ttk.Treeview) cohérent avec le thème clair."""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:  # thème indisponible : on garde celui par défaut
        pass
    style.configure("Treeview", rowheight=28, font=(POLICE, 11), background="white",
                    fieldbackground="white", borderwidth=0)
    style.configure("Treeview.Heading", font=(POLICE, 11, "bold"), background="#e5e7eb",
                    relief="flat")
    style.map("Treeview", background=[("selected", BLEU)], foreground=[("selected", "white")])
