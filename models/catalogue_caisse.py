"""Champs d'un produit cosmétique (caisse) : source unique pour le formulaire et la validation."""

from models.catalogue import Champ

CHAMPS_PRODUIT = (
    Champ("code", "ID (laisser vide = automatique)", "texte", obligatoire=False),
    Champ("codes_barres", "Codes-barres (séparés par un espace ou une virgule)", "texte", obligatoire=False),
    Champ("nom", "Nom du produit", "texte"),
    Champ("categorie", "Catégorie (facultatif)", "texte", obligatoire=False),
    Champ("prix_achat", "Prix d'achat (DA)", "nombre"),
    Champ("prix_vente", "Prix de vente (DA)", "nombre"),
    Champ("quantite_stock", "Quantité en stock", "entier", minimum=None, defaut="0"),
    Champ("seuil_alerte", "Seuil d'alerte stock bas", "entier", defaut="5"),
)
