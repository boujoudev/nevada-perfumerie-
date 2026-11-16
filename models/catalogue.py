"""Description des 3 types de produits et de leurs champs.

Ce fichier est la source unique de vérité : les formulaires, la validation,
le stock et les dialogues sont tous générés à partir de ce catalogue.

Il n'y a PAS de prix de vente par produit : le prix de chaque vente est saisi
au moment de la vente et le bénéfice = prix saisi - coût d'achat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Champ:
    cle: str                      # nom de la colonne SQL
    libelle: str                  # texte affiché à l'utilisateur
    genre: str                    # "texte" | "nombre" | "entier"
    minimum: Optional[float] = 0  # None = pas de minimum (stock négatif permis)
    strict: bool = False          # True = doit être > 0
    defaut: Optional[str] = None  # valeur proposée / utilisée si champ vide


@dataclass(frozen=True)
class TypeProduit:
    code: str
    libelle: str
    table: str
    prefixe: str
    colonne_stock: str
    colonne_prix_achat: str
    unite_stock: str
    champs: Tuple[Champ, ...]
    colonnes_calculees: Tuple[str, ...] = ()   # remplies par le service, pas saisies

    @property
    def cles(self) -> Tuple[str, ...]:
        return tuple(c.cle for c in self.champs) + self.colonnes_calculees

    def code_affiche(self, identifiant: int) -> str:
        """Ex. 'F-3' : évite la confusion entre le flacon n°3 et le parfum n°3."""
        return f"{self.prefixe}-{identifiant}"


CATALOGUE: Dict[str, TypeProduit] = {
    "FLACON": TypeProduit(
        code="FLACON", libelle="Flacon", table="flacons", prefixe="F",
        colonne_stock="quantite_stock", colonne_prix_achat="prix_achat", unite_stock="unités",
        champs=(
            Champ("nom", "Nom du flacon", "texte"),
            Champ("capacite_ml", "Capacité (ml)", "nombre", strict=True),
            Champ("prix_achat", "Prix d'achat du flacon vide (DA)", "nombre"),
            Champ("quantite_stock", "Quantité en stock (unités)", "entier", minimum=None, defaut="0"),
            Champ("qnt_parfum_necessaire", "Concentré de parfum par flacon (ml)", "nombre"),
            Champ("seuil_alerte", "Seuil d'alerte stock bas (unités)", "nombre", defaut="5"),
        ),
        # alcool = capacité - parfum (automatique)
        colonnes_calculees=("qnt_alcool_necessaire",),
    ),
    "PARFUM": TypeProduit(
        code="PARFUM", libelle="Parfum", table="parfums", prefixe="P",
        colonne_stock="quantite_stock_ml", colonne_prix_achat="prix_achat_100ml", unite_stock="ml",
        champs=(
            Champ("nom", "Nom du parfum", "texte"),
            Champ("prix_achat_100ml", "Prix d'achat pour 100 ml (DA)", "nombre"),
            Champ("quantite_stock_ml", "Quantité en stock (ml)", "nombre", minimum=None, defaut="0"),
            Champ("seuil_alerte", "Seuil d'alerte stock bas (ml)", "nombre", defaut="100"),
        ),
    ),
    "ALCOOL": TypeProduit(
        code="ALCOOL", libelle="Alcool", table="alcools", prefixe="A",
        colonne_stock="quantite_stock_ml", colonne_prix_achat="prix_achat_litre", unite_stock="ml",
        champs=(
            Champ("nom", "Nom de l'alcool", "texte"),
            Champ("prix_achat_litre", "Prix d'achat par litre (DA)", "nombre"),
            Champ("quantite_stock_ml", "Quantité en stock (ml)", "nombre", minimum=None, defaut="0"),
            Champ("seuil_alerte", "Seuil d'alerte stock bas (ml)", "nombre", defaut="1000"),
        ),
    ),
}

ORDRE_TYPES = ("FLACON", "PARFUM", "ALCOOL")
