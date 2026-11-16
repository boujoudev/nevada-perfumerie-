"""Logique métier des produits : création, modification, stock, recherche."""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Tuple

from database.connection import transaction
from models.catalogue import CATALOGUE, ORDRE_TYPES, TypeProduit
from repositories import logs_repo, produits_repo
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_ml, fmt_nombre, fmt_prix, parse_nombre


# Prix d'achat saisis pour 100 ml (parfum) ou au litre (alcool) ; quantités en ml.
DIVISEUR_PRIX = {"FLACON": 1, "PARFUM": 100, "ALCOOL": 1000}


def _type(type_code: str) -> TypeProduit:
    if type_code not in CATALOGUE:
        raise ErreurMetier(f"Type de produit inconnu : {type_code}")
    return CATALOGUE[type_code]


# ------------------------------------------------------------------ validation
def valider_saisies(type_code: str, saisies: Dict[str, str]) -> Tuple[dict, List[str]]:
    """Convertit les saisies texte en valeurs typées.

    Retourne (valeurs, avertissements). Lève ErreurMetier si invalide.
    """
    t = _type(type_code)
    valeurs: dict = {}
    for champ in t.champs:
        brut = saisies.get(champ.cle, "")
        if champ.genre == "texte":
            texte = (brut or "").strip()
            if not texte:
                raise ErreurMetier(f"Le champ « {champ.libelle} » est obligatoire.")
            valeurs[champ.cle] = texte
        else:
            if (brut or "").strip() == "" and champ.defaut is not None:
                brut = champ.defaut
            valeurs[champ.cle] = parse_nombre(
                brut, champ.libelle, minimum=champ.minimum,
                entier=(champ.genre == "entier"), strictement_positif=champ.strict)

    avertissements: List[str] = []
    if type_code == "FLACON":
        capacite, parfum = valeurs["capacite_ml"], valeurs["qnt_parfum_necessaire"]
        if parfum > capacite:
            raise ErreurMetier(
                f"Le parfum ({fmt_nombre(parfum)} ml) ne peut pas dépasser la capacité du "
                f"flacon ({fmt_nombre(capacite)} ml).")
        # Quantité d'alcool automatique : le reste du flacon
        valeurs["qnt_alcool_necessaire"] = round(capacite - parfum, 3)
    return valeurs, avertissements


# ------------------------------------------------------------------ écriture
def creer_produit(conn: sqlite3.Connection, type_code: str, saisies: Dict[str, str]) -> dict:
    """Crée un produit ; il entre automatiquement en stock avec la quantité saisie."""
    t = _type(type_code)
    valeurs, avertissements = valider_saisies(type_code, saisies)
    with transaction(conn):
        identifiant = produits_repo.inserer(conn, type_code, valeurs)
        logs_repo.ajouter(conn, "CREATION", type_code, identifiant, valeurs["nom"],
                          quantite=valeurs[t.colonne_stock],
                          details=f"Création {t.libelle.lower()} {t.code_affiche(identifiant)}")
    return {"id": identifiant, "code": t.code_affiche(identifiant),
            "nom": valeurs["nom"], "avertissements": avertissements}


def modifier_produit(conn: sqlite3.Connection, type_code: str, identifiant: int,
                     saisies: Dict[str, str]) -> dict:
    t = _type(type_code)
    if produits_repo.obtenir(conn, type_code, identifiant) is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    valeurs, avertissements = valider_saisies(type_code, saisies)
    with transaction(conn):
        produits_repo.modifier(conn, type_code, identifiant, valeurs)
        logs_repo.ajouter(conn, "MODIFICATION", type_code, identifiant, valeurs["nom"],
                          details=f"Modification {t.libelle.lower()} {t.code_affiche(identifiant)}")
    return {"avertissements": avertissements}


def supprimer_produit(conn: sqlite3.Connection, type_code: str, identifiant: int) -> None:
    """Suppression douce : le produit disparaît du stock, l'historique reste intact."""
    t = _type(type_code)
    produit = produits_repo.obtenir(conn, type_code, identifiant)
    if produit is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    with transaction(conn):
        produits_repo.desactiver(conn, type_code, identifiant)
        logs_repo.ajouter(conn, "SUPPRESSION", type_code, identifiant, produit["nom"],
                          details=f"Suppression {t.libelle.lower()} {t.code_affiche(identifiant)}")


def reapprovisionner(conn: sqlite3.Connection, type_code: str, identifiant: int,
                     quantite_txt: str) -> float:
    """Ajoute du stock et enregistre un 'Achat' (quantité × prix d'achat). Retourne le nouveau stock."""
    t = _type(type_code)
    produit = produits_repo.obtenir(conn, type_code, identifiant)
    if produit is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    quantite = parse_nombre(quantite_txt, f"Quantité à ajouter ({t.unite_stock})",
                            strictement_positif=True, entier=(type_code == "FLACON"))
    diviseur = DIVISEUR_PRIX[type_code]
    cout = round(quantite * produit[t.colonne_prix_achat] / diviseur, 2)
    with transaction(conn):
        produits_repo.ajuster_stock(conn, type_code, identifiant, quantite)
        logs_repo.ajouter(conn, "ACHAT", type_code, identifiant, produit["nom"],
                          quantite=quantite, prix=cout,
                          details=f"Réapprovisionnement {t.code_affiche(identifiant)}")
    return produits_repo.obtenir(conn, type_code, identifiant)[t.colonne_stock]


# ------------------------------------------------------------------ lecture
def _details(type_code: str, row: sqlite3.Row) -> str:
    if type_code == "FLACON":
        return (f"{fmt_nombre(row['capacite_ml'])} ml | parfum {fmt_nombre(row['qnt_parfum_necessaire'])} ml"
                f" | alcool {fmt_nombre(row['qnt_alcool_necessaire'])} ml (auto)")
    if type_code == "PARFUM":
        return "Concentré pur"
    return "Composant de base"


def _ligne_unifiee(type_code: str, row: sqlite3.Row) -> dict:
    t = CATALOGUE[type_code]
    stock = row[t.colonne_stock]
    suffixe_achat = {"FLACON": "", "PARFUM": "/100 ml", "ALCOOL": "/L"}[type_code]
    return {
        "type": type_code,
        "id": row["id"],
        "code": t.code_affiche(row["id"]),
        "nom": row["nom"],
        "type_libelle": t.libelle,
        "prix_achat_txt": fmt_prix(row[t.colonne_prix_achat]) + suffixe_achat,
        "stock": stock,
        "stock_txt": fmt_nombre(stock) if type_code == "FLACON" else fmt_ml(stock),
        "details": _details(type_code, row),
        "bas": stock < row["seuil_alerte"],
    }


def rechercher(conn: sqlite3.Connection, texte: str = "", par: str = "Nom",
               type_code: Optional[str] = None) -> List[dict]:
    """Recherche dans le stock.

    par = "Nom"  : recherche partielle, insensible à la casse.
    par = "ID"   : recherche exacte ('3' ou 'F-3').
    type_code    : None = tous les types.
    """
    texte = (texte or "").strip()
    types = [type_code] if type_code else list(ORDRE_TYPES)
    resultats: List[dict] = []
    for code in types:
        for row in produits_repo.lister(conn, code):
            ligne = _ligne_unifiee(code, row)
            if texte:
                if par == "ID":
                    if not (texte.isdigit() and int(texte) == row["id"]
                            or texte.upper() == ligne["code"]):
                        continue
                elif texte.casefold() not in row["nom"].casefold():
                    continue
            resultats.append(ligne)
    return resultats


def produits_en_alerte(conn: sqlite3.Connection) -> List[dict]:
    """Produits dont le stock est sous le seuil d'alerte."""
    return [l for l in rechercher(conn) if l["bas"]]
