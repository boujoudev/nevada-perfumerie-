"""Accès aux fichiers fournis avec l'application (logo, icônes), y compris dans l'.exe PyInstaller."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

journal = logging.getLogger(__name__)


def chemin_ressource(relatif: str) -> Path:
    """Chemin d'un fichier du projet (ex. 'assets/logo.png'), en développement comme dans l'.exe."""
    racine = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return racine / relatif


def charger_logo(largeur: int):
    """Retourne le logo (CTkImage) à la largeur voulue, ou None s'il est introuvable.

    L'application fonctionne sans logo : l'appelant affiche alors un simple texte.
    """
    try:
        import customtkinter as ctk
        from PIL import Image

        image = Image.open(chemin_ressource("assets/logo.png")).convert("RGBA")
        hauteur = round(image.height * largeur / image.width)
        return ctk.CTkImage(light_image=image, dark_image=image, size=(largeur, hauteur))
    except Exception:  # noqa: BLE001 - un logo manquant ne doit jamais bloquer le démarrage
        journal.warning("Logo introuvable ou illisible", exc_info=True)
        return None
