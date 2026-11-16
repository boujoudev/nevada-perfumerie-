"""Conversion et affichage des nombres, prix et dates (format français)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from utils.erreurs import ErreurMetier

DEVISE = "DA"


def fmt_nombre(valeur: Optional[float]) -> str:
    """1234.5 -> '1 234,5' ; 50.0 -> '50'."""
    if valeur is None:
        return ""
    valeur = float(valeur)
    if valeur.is_integer():
        return f"{int(valeur):,}".replace(",", " ")
    texte = f"{valeur:,.2f}".replace(",", " ").replace(".", ",")
    return texte.rstrip("0").rstrip(",")


def fmt_prix(valeur: Optional[float]) -> str:
    """1234.5 -> '1 234,50 DA'."""
    if valeur is None:
        return ""
    texte = f"{float(valeur):,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} {DEVISE}"


def fmt_ml(valeur: Optional[float]) -> str:
    """500 -> '500 ml'."""
    return f"{fmt_nombre(valeur)} ml" if valeur is not None else ""


def fmt_brut(valeur) -> str:
    """Valeur pour un champ de saisie (sans séparateur de milliers)."""
    if valeur is None:
        return ""
    if isinstance(valeur, (int, float)):
        return "%.10g" % valeur
    return str(valeur)


def fmt_datetime(texte: Optional[str]) -> str:
    """'2026-11-15 14:30:00' -> '15/11/2026 14:30'."""
    if not texte:
        return ""
    try:
        return datetime.strptime(texte[:19], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return texte


def parse_nombre(
    texte: Optional[str],
    libelle: str,
    minimum: Optional[float] = None,
    entier: bool = False,
    strictement_positif: bool = False,
):
    """Convertit une saisie en nombre (accepte la virgule et les espaces).

    Lève ErreurMetier avec un message clair si la saisie est invalide.
    """
    brut = (texte or "").strip().replace(" ", "").replace(",", ".")
    if brut == "":
        raise ErreurMetier(f"Le champ « {libelle} » est obligatoire.")
    try:
        valeur = float(brut)
    except ValueError:
        raise ErreurMetier(f"« {libelle} » doit être un nombre (saisi : « {texte} »).") from None
    if not math.isfinite(valeur):
        raise ErreurMetier(f"« {libelle} » n'est pas un nombre valide.")
    if entier:
        if valeur != int(valeur):
            raise ErreurMetier(f"« {libelle} » doit être un nombre entier.")
        valeur = int(valeur)
    if strictement_positif and valeur <= 0:
        raise ErreurMetier(f"« {libelle} » doit être supérieur à 0.")
    if minimum is not None and valeur < minimum:
        raise ErreurMetier(f"« {libelle} » ne peut pas être inférieur à {fmt_nombre(minimum)}.")
    return valeur
