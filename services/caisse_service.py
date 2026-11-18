"""Module COSMÉTIQUE (caisse) : produits, codes-barres, panier, tickets, retours, import.

Règles :
  * le prix de vente est fixé par produit (modifiable à la vente) ; le coût = dernier prix d'achat saisi ;
  * vente en rupture autorisée (stock négatif + avertissement) ;
  * toute vente / retour exige une SESSION de caisse ouverte ;
  * le bénéfice = prix réellement encaissé - coût d'achat ; les retours le diminuent.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from typing import Dict, List, Optional, Tuple

from database.connection import transaction
from models.catalogue_caisse import CHAMPS_PRODUIT
from repositories import logs_caisse_repo
from services import session_service, utilisateurs_service
from services.produits_service import _nettoyer_id
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_nombre, fmt_prix, parse_nombre

_SQL_PRODUITS = (
    "SELECT p.*, (SELECT group_concat(code_barre, ' ') FROM codes_barres WHERE produit_id = p.id) "
    "AS codes_barres FROM produits_caisse p WHERE p.actif = 1")


def _r(valeur: float) -> float:
    return round(float(valeur), 2)


# =================================================================== PRODUITS
def code_affiche(ligne) -> str:
    """ID affiché : celui choisi par l'utilisateur, sinon C-<n>."""
    try:
        code = ligne["code"]
    except (KeyError, IndexError):
        code = None
    return code or f"C-{ligne['id']}"


def produit_dict(ligne: sqlite3.Row) -> dict:
    d = dict(ligne)
    d["code_affiche"] = code_affiche(ligne)
    d["codes_barres"] = d.get("codes_barres") or ""
    d["stock"] = ligne["quantite_stock"]
    d["bas"] = ligne["quantite_stock"] < ligne["seuil_alerte"]
    return d


def obtenir(conn: sqlite3.Connection, produit_id: int, actif_seulement: bool = True) -> Optional[sqlite3.Row]:
    sql = ("SELECT p.*, (SELECT group_concat(code_barre, ' ') FROM codes_barres WHERE produit_id = p.id) "
           "AS codes_barres FROM produits_caisse p WHERE p.id = ?")
    if actif_seulement:
        sql += " AND p.actif = 1"
    return conn.execute(sql, (produit_id,)).fetchone()


def _parser_codes_barres(brut: Optional[str]) -> List[str]:
    codes: List[str] = []
    for morceau in re.split(r"[\s,;]+", (brut or "").strip()):
        if not morceau:
            continue
        if len(morceau) > 64:
            raise ErreurMetier("Un code-barres est trop long (64 caractères maximum).")
        if morceau not in codes:
            codes.append(morceau)
    return codes


def valider_produit(saisies: Dict[str, str]) -> Tuple[dict, List[str], List[str]]:
    """Retourne (valeurs, codes_barres, avertissements) ou lève ErreurMetier."""
    valeurs: dict = {}
    codes_barres: List[str] = []
    for champ in CHAMPS_PRODUIT:
        brut = saisies.get(champ.cle, "")
        if champ.cle == "code":
            valeurs["code"] = _nettoyer_id(brut)
        elif champ.cle == "codes_barres":
            codes_barres = _parser_codes_barres(brut)
        elif champ.genre == "texte":
            texte = (brut or "").strip()
            if not texte and champ.obligatoire:
                raise ErreurMetier(f"Le champ « {champ.libelle} » est obligatoire.")
            valeurs[champ.cle] = texte or None
        else:
            if (brut or "").strip() == "" and champ.defaut is not None:
                brut = champ.defaut
            valeurs[champ.cle] = parse_nombre(brut, champ.libelle, minimum=champ.minimum,
                                              entier=(champ.genre == "entier"),
                                              strictement_positif=champ.strict)
    avertissements = []
    if valeurs["prix_achat"] > valeurs["prix_vente"]:
        avertissements.append(
            f"Attention : le prix d'achat ({fmt_nombre(valeurs['prix_achat'])} DA) est supérieur au prix de "
            f"vente ({fmt_nombre(valeurs['prix_vente'])} DA). Vérifiez les prix.")
    return valeurs, codes_barres, avertissements


def _verifier_codes_barres_libres(conn: sqlite3.Connection, codes: List[str],
                                  exclure: Optional[int] = None) -> None:
    for code in codes:
        ligne = conn.execute(
            "SELECT cb.produit_id, p.nom FROM codes_barres cb JOIN produits_caisse p ON p.id = cb.produit_id "
            "WHERE cb.code_barre = ?", (code,)).fetchone()
        if ligne and ligne["produit_id"] != exclure:
            raise ErreurMetier(f"Le code-barres « {code} » est déjà utilisé par le produit « {ligne['nom']} ».")


def _verifier_id_libre(conn: sqlite3.Connection, code: str, exclure: Optional[int] = None) -> None:
    ligne = conn.execute("SELECT id, nom FROM produits_caisse WHERE code = ? COLLATE NOCASE", (code,)).fetchone()
    if ligne and ligne["id"] != exclure:
        raise ErreurMetier(f"L'ID « {code} » est déjà utilisé par le produit « {ligne['nom']} ». "
                           "Choisissez-en un autre.")


def _id_automatique(conn: sqlite3.Connection, identifiant: int) -> str:
    base, candidat, n = f"C-{identifiant}", f"C-{identifiant}", 1
    while conn.execute("SELECT 1 FROM produits_caisse WHERE code = ? COLLATE NOCASE", (candidat,)).fetchone():
        candidat, n = f"{base}.{n}", n + 1
    return candidat


def _creer(conn: sqlite3.Connection, valeurs: dict, codes_barres: List[str], utilisateur_id: Optional[int]) -> dict:
    """Création SANS transaction propre (appelée dans une transaction par creer_produit et l'import)."""
    if valeurs.get("code"):
        _verifier_id_libre(conn, valeurs["code"])
    _verifier_codes_barres_libres(conn, codes_barres)
    colonnes = list(valeurs)
    identifiant = conn.execute(
        f"INSERT INTO produits_caisse ({', '.join(colonnes)}) VALUES ({', '.join('?' for _ in colonnes)})",
        [valeurs[c] for c in colonnes]).lastrowid
    code = valeurs.get("code")
    if not code:
        code = _id_automatique(conn, identifiant)
        conn.execute("UPDATE produits_caisse SET code = ? WHERE id = ?", (code, identifiant))
    for code_barre in codes_barres:
        conn.execute("INSERT INTO codes_barres (code_barre, produit_id) VALUES (?, ?)", (code_barre, identifiant))
    logs_caisse_repo.ajouter(conn, "CREATION", utilisateur_id, produit_id=identifiant,
                             produit_nom=valeurs["nom"], quantite=valeurs["quantite_stock"],
                             details=f"Création produit {code}")
    return {"id": identifiant, "code": code, "nom": valeurs["nom"]}


def creer_produit(conn: sqlite3.Connection, saisies: Dict[str, str], utilisateur=None) -> dict:
    valeurs, codes_barres, avertissements = valider_produit(saisies)
    with transaction(conn):
        resultat = _creer(conn, valeurs, codes_barres, utilisateur["id"] if utilisateur else None)
    return {**resultat, "avertissements": avertissements}


def modifier_produit(conn: sqlite3.Connection, produit_id: int, saisies: Dict[str, str], utilisateur=None) -> dict:
    """Modifie un produit. ID/code-barres libres uniquement ; ID vidé = ancien conservé."""
    produit = obtenir(conn, produit_id)
    if produit is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    valeurs, codes_barres, avertissements = valider_produit(saisies)
    with transaction(conn):
        if valeurs["code"]:
            _verifier_id_libre(conn, valeurs["code"], exclure=produit_id)
        else:
            valeurs.pop("code")
        _verifier_codes_barres_libres(conn, codes_barres, exclure=produit_id)
        affectations = ", ".join(f"{c} = ?" for c in valeurs)
        conn.execute(f"UPDATE produits_caisse SET {affectations} WHERE id = ?", [*valeurs.values(), produit_id])
        conn.execute("DELETE FROM codes_barres WHERE produit_id = ?", (produit_id,))
        for code_barre in codes_barres:
            conn.execute("INSERT INTO codes_barres (code_barre, produit_id) VALUES (?, ?)", (code_barre, produit_id))
        logs_caisse_repo.ajouter(conn, "MODIFICATION", utilisateur["id"] if utilisateur else None,
                                 produit_id=produit_id, produit_nom=valeurs["nom"],
                                 details=f"Modification produit {valeurs.get('code') or code_affiche(produit)}")
    return {"avertissements": avertissements}


def supprimer_produit(conn: sqlite3.Connection, produit_id: int, utilisateur=None) -> None:
    """Suppression douce : le produit disparaît ; son ID et ses codes-barres sont libérés."""
    produit = obtenir(conn, produit_id)
    if produit is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    with transaction(conn):
        conn.execute("UPDATE produits_caisse SET actif = 0, code = NULL WHERE id = ?", (produit_id,))
        conn.execute("DELETE FROM codes_barres WHERE produit_id = ?", (produit_id,))
        logs_caisse_repo.ajouter(conn, "SUPPRESSION", utilisateur["id"] if utilisateur else None,
                                 produit_id=produit_id, produit_nom=produit["nom"],
                                 details=f"Suppression produit {code_affiche(produit)}")


def trouver_exact(conn: sqlite3.Connection, texte: str) -> Optional[sqlite3.Row]:
    """Produit dont le code-barres (ou l'ID) est exactement `texte` — c'est ce que fait un scan."""
    texte = (texte or "").strip()
    if not texte:
        return None
    ligne = conn.execute(_SQL_PRODUITS + " AND p.id = (SELECT produit_id FROM codes_barres WHERE code_barre = ?)",
                         (texte,)).fetchone()
    return ligne or conn.execute(_SQL_PRODUITS + " AND p.code = ? COLLATE NOCASE", (texte,)).fetchone()


def rechercher(conn: sqlite3.Connection, texte: str = "", limite: Optional[int] = None) -> List[dict]:
    """Recherche par nom (tous les mots), catégorie, ID ou code-barres (partiel). Vide = tout le catalogue."""
    mots = (texte or "").casefold().split()
    resultats: List[dict] = []
    for ligne in conn.execute(_SQL_PRODUITS + " ORDER BY p.nom COLLATE NOCASE").fetchall():
        if mots:
            texte_nom = f"{ligne['nom']} {ligne['categorie'] or ''}".casefold()
            autres = f"{code_affiche(ligne)} {ligne['codes_barres'] or ''}".casefold()
            if not all(m in texte_nom or m in autres for m in mots):
                continue
        resultats.append(produit_dict(ligne))
        if limite and len(resultats) >= limite:
            break
    return resultats


def produits_en_alerte(conn: sqlite3.Connection) -> List[dict]:
    return [p for p in rechercher(conn) if p["bas"]]


def reapprovisionner(conn: sqlite3.Connection, produit_id: int, quantite_txt: str, prix_achat_txt: str = "",
                     utilisateur=None) -> int:
    """Réception de marchandise : stock + quantité ; le prix d'achat devient le dernier prix saisi."""
    produit = obtenir(conn, produit_id)
    if produit is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    quantite = parse_nombre(quantite_txt, "Quantité reçue", strictement_positif=True, entier=True)
    if (prix_achat_txt or "").strip():
        prix_achat = parse_nombre(prix_achat_txt, "Prix d'achat", minimum=0)
    else:
        prix_achat = produit["prix_achat"]
    with transaction(conn):
        conn.execute("UPDATE produits_caisse SET quantite_stock = quantite_stock + ?, prix_achat = ? WHERE id = ?",
                     (quantite, prix_achat, produit_id))
        logs_caisse_repo.ajouter(conn, "ACHAT", utilisateur["id"] if utilisateur else None,
                                 produit_id=produit_id, produit_nom=produit["nom"], quantite=quantite,
                                 prix=_r(quantite * prix_achat),
                                 details=f"Réception {code_affiche(produit)} au prix d'achat {fmt_prix(prix_achat)}")
    return obtenir(conn, produit_id)["quantite_stock"]


def ajuster_stock(conn: sqlite3.Connection, produit_id: int, quantite_comptee_txt: str, utilisateur=None,
                  motif: str = "") -> int:
    """Inventaire : remplace le stock par la quantité comptée. Retourne l'écart (compté - ancien)."""
    produit = obtenir(conn, produit_id)
    if produit is None:
        raise ErreurMetier("Ce produit n'existe plus.")
    comptee = parse_nombre(quantite_comptee_txt, "Quantité comptée", entier=True)
    ancien = produit["quantite_stock"]
    ecart = comptee - ancien
    with transaction(conn):
        conn.execute("UPDATE produits_caisse SET quantite_stock = ? WHERE id = ?", (comptee, produit_id))
        details = f"Inventaire {code_affiche(produit)} : {ancien} → {comptee} (écart {ecart:+d})"
        if (motif or "").strip():
            details += f" — {motif.strip()}"
        logs_caisse_repo.ajouter(conn, "AJUSTEMENT", utilisateur["id"] if utilisateur else None,
                                 produit_id=produit_id, produit_nom=produit["nom"], quantite=ecart,
                                 details=details)
    return ecart


# ================================================================= IMPORT
_ALIAS = {
    "code_barre": {"codebarre", "codebarres", "codesbarres", "barcode", "ean", "code", "gencod", "upc"},
    "code": {"id", "reference", "ref", "idproduit"},
    "nom": {"nom", "designation", "produit", "libelle", "article", "name", "description"},
    "categorie": {"categorie", "famille", "category", "rayon", "type"},
    "prix_achat": {"prixachat", "achat", "prixdachat", "cout", "coutachat", "pa", "purchaseprice"},
    "prix_vente": {"prixvente", "vente", "prix", "prixdevente", "pv", "prixttc", "price"},
    "quantite_stock": {"stock", "quantite", "qte", "qty", "quantitestock", "qtestock"},
    "seuil_alerte": {"seuil", "seuilalerte", "stockminimum", "stockmin"},
}


def _normaliser(texte: str) -> str:
    sans_accent = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sans_accent.lower())


def _texte_cellule(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))                  # Excel : 6.1234e12 -> « 6123400000000 »
    return str(valeur).strip()


def _lire_tableau(chemin: str) -> List[List[str]]:
    """Lit un .csv (séparateur , ou ;) ou un .xlsx et retourne la liste des lignes (texte)."""
    if chemin.lower().endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ErreurMetier("La lecture des fichiers Excel demande le module openpyxl "
                               "(ou enregistrez le fichier en CSV depuis Excel).") from None
        try:
            classeur = load_workbook(chemin, read_only=True, data_only=True)
            feuille = classeur.active
            lignes = [[_texte_cellule(c) for c in ligne] for ligne in feuille.iter_rows(values_only=True)]
            classeur.close()
            return lignes
        except Exception as erreur:  # noqa: BLE001
            raise ErreurMetier(f"Impossible de lire le fichier Excel : {erreur}") from None
    contenu = None
    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(chemin, encoding=encodage, newline="") as fichier:
                contenu = fichier.read()
            break
        except UnicodeDecodeError:
            continue
        except OSError as erreur:
            raise ErreurMetier(f"Impossible d'ouvrir le fichier : {erreur}") from None
    if contenu is None:
        raise ErreurMetier("Encodage du fichier non reconnu (enregistrez-le en CSV UTF-8).")
    premiere = contenu.splitlines()[0] if contenu.strip() else ""
    separateur = ";" if premiere.count(";") >= premiere.count(",") and ";" in premiere else \
        ("\t" if "\t" in premiere and "," not in premiere else ",")
    return [[c.strip() for c in ligne] for ligne in csv.reader(contenu.splitlines(), delimiter=separateur)]


def importer(conn: sqlite3.Connection, chemin: str, utilisateur=None) -> dict:
    """Importe un catalogue (CSV / Excel).

    Colonnes reconnues (peu importe l'ordre, les accents, les majuscules) : code-barres, nom (obligatoire),
    prix de vente (obligatoire), prix d'achat, catégorie, stock, seuil, ID.
    Produit dont le code-barres existe déjà : nom, catégorie et prix mis à jour, stock NON modifié.
    Retourne {"crees": n, "mis_a_jour": n, "erreurs": [texte, ...]}.
    """
    lignes = _lire_tableau(chemin)
    if not lignes:
        raise ErreurMetier("Le fichier est vide.")
    colonnes: Dict[str, int] = {}
    for position, entete in enumerate(lignes[0]):
        cle = _normaliser(entete)
        for champ, alias in _ALIAS.items():
            if cle in alias and champ not in colonnes:
                colonnes[champ] = position
    if "nom" not in colonnes or "prix_vente" not in colonnes:
        raise ErreurMetier("Colonnes obligatoires introuvables : le fichier doit avoir au minimum une colonne "
                           "« nom » (ou désignation) et une colonne « prix de vente ». "
                           "La première ligne doit contenir les titres des colonnes.")

    def cellule(ligne: List[str], champ: str) -> str:
        position = colonnes.get(champ)
        return ligne[position].strip() if position is not None and position < len(ligne) else ""

    crees = mis_a_jour = 0
    erreurs: List[str] = []
    with transaction(conn):
        for numero, ligne in enumerate(lignes[1:], start=2):
            if not any(c.strip() for c in ligne):
                continue
            try:
                code_barre = cellule(ligne, "code_barre")
                saisies = {
                    "nom": cellule(ligne, "nom"), "categorie": cellule(ligne, "categorie"),
                    "prix_achat": cellule(ligne, "prix_achat") or "0", "prix_vente": cellule(ligne, "prix_vente"),
                    "quantite_stock": cellule(ligne, "quantite_stock") or "0",
                    "seuil_alerte": cellule(ligne, "seuil_alerte") or "5",
                    "code": cellule(ligne, "code"), "codes_barres": code_barre,
                }
                valeurs, codes, _ = valider_produit(saisies)
                existant = None
                if codes:
                    existant = conn.execute("SELECT produit_id FROM codes_barres WHERE code_barre = ?",
                                            (codes[0],)).fetchone()
                if existant:
                    maj = {"nom": valeurs["nom"], "categorie": valeurs["categorie"], "prix_vente": valeurs["prix_vente"]}
                    if "prix_achat" in colonnes:
                        maj["prix_achat"] = valeurs["prix_achat"]
                    conn.execute(f"UPDATE produits_caisse SET {', '.join(f'{c} = ?' for c in maj)} WHERE id = ?",
                                 [*maj.values(), existant["produit_id"]])
                    mis_a_jour += 1
                else:
                    conn.execute("SAVEPOINT ligne")
                    try:
                        _creer(conn, valeurs, codes, utilisateur["id"] if utilisateur else None)
                        conn.execute("RELEASE ligne")
                    except ErreurMetier:
                        conn.execute("ROLLBACK TO ligne")
                        conn.execute("RELEASE ligne")
                        raise
                    crees += 1
            except ErreurMetier as erreur:
                erreurs.append(f"Ligne {numero} : {erreur}")
        logs_caisse_repo.ajouter(conn, "IMPORT", utilisateur["id"] if utilisateur else None, quantite=crees,
                                 details=f"Import {chemin.replace(chr(92), '/').split('/')[-1]} : {crees} créé(s), "
                                         f"{mis_a_jour} mis à jour, {len(erreurs)} erreur(s)")
    return {"crees": crees, "mis_a_jour": mis_a_jour, "erreurs": erreurs}


# ===================================================================== PANIER
def _remise(base: float, type_remise: Optional[str], valeur) -> float:
    """Montant de la remise (jamais supérieur à la base, jamais négatif)."""
    if not type_remise or not valeur:
        return 0.0
    valeur = float(valeur)
    if valeur < 0:
        raise ErreurMetier("Une remise ne peut pas être négative.")
    if type_remise == "POURCENT":
        if valeur > 100:
            raise ErreurMetier("Une remise ne peut pas dépasser 100 %.")
        return _r(base * valeur / 100)
    if type_remise == "MONTANT":
        return _r(min(valeur, base))
    raise ErreurMetier("Type de remise inconnu.")


def calculer_panier(lignes: List[dict], remise_type: Optional[str] = None, remise_valeur=0) -> dict:
    """Calcule les totaux d'un panier (sans accès à la base).

    Chaque ligne : quantite, prix_unitaire, remise_type, remise_valeur (remise de la ligne, facultative).
    La remise globale est répartie sur les lignes au prorata (le retour d'une ligne reste ainsi exact).
    """
    calculees: List[dict] = []
    for ligne in lignes:
        quantite = int(ligne["quantite"])
        prix = float(ligne["prix_unitaire"])
        if quantite <= 0:
            raise ErreurMetier("La quantité doit être d'au moins 1.")
        if prix < 0:
            raise ErreurMetier("Un prix ne peut pas être négatif.")
        base = _r(quantite * prix)
        propre = _remise(base, ligne.get("remise_type"), ligne.get("remise_valeur"))
        calculees.append({"base": base, "remise_propre": propre, "net": _r(base - propre)})
    net_avant_globale = _r(sum(c["net"] for c in calculees))
    globale = _remise(net_avant_globale, remise_type, remise_valeur)
    reste = globale
    for i, c in enumerate(calculees):
        if globale and net_avant_globale > 0:
            part = reste if i == len(calculees) - 1 else min(reste, _r(globale * c["net"] / net_avant_globale))
        else:
            part = 0.0
        reste = _r(reste - part)
        c["remise_globale"] = _r(part)
        c["remise_ligne"] = _r(c["remise_propre"] + part)
        c["total_ligne"] = _r(c["base"] - c["remise_ligne"])
    return {
        "lignes": calculees,
        "sous_total": _r(sum(c["base"] for c in calculees)),
        "remise_globale": globale,
        "remise_totale": _r(sum(c["remise_ligne"] for c in calculees)),
        "total": _r(sum(c["total_ligne"] for c in calculees)),
    }


# ===================================================================== TICKETS
def valider_ticket(conn: sqlite3.Connection, lignes: List[dict], utilisateur, client_id: Optional[int] = None,
                   remise_type: Optional[str] = None, remise_valeur=0, montant_donne_txt: str = "",
                   note: Optional[str] = None) -> dict:
    """Encaisse un ticket : enregistre, décrémente le stock, calcule la monnaie et le bénéfice."""
    if utilisateur is None:
        raise ErreurMetier("Aucun utilisateur connecté.")
    if not lignes:
        raise ErreurMetier("Le panier est vide : scannez ou ajoutez un produit.")
    session = session_service.exiger_session_active(conn)

    with transaction(conn):
        produits: List[sqlite3.Row] = []
        a_calculer: List[dict] = []
        modifs: List[str] = []
        for ligne in lignes:
            produit = obtenir(conn, int(ligne["produit_id"]))
            if produit is None:
                raise ErreurMetier("Un produit du panier n'existe plus (supprimé ?). Retirez-le du panier.")
            prix = ligne.get("prix_unitaire")
            prix = produit["prix_vente"] if prix is None else float(prix)
            if abs(prix - produit["prix_vente"]) > 0.004:
                modifs.append(f"{produit['nom']} : prix {fmt_prix(produit['prix_vente'])} → {fmt_prix(prix)}")
            if ligne.get("remise_type") and ligne.get("remise_valeur"):
                modifs.append(f"remise sur {produit['nom']}")
            produits.append(produit)
            a_calculer.append({"quantite": ligne["quantite"], "prix_unitaire": prix,
                               "remise_type": ligne.get("remise_type"), "remise_valeur": ligne.get("remise_valeur")})
        calcul = calculer_panier(a_calculer, remise_type, remise_valeur)
        if calcul["remise_globale"]:
            modifs.append(f"remise globale {fmt_prix(calcul['remise_globale'])}")
        total = calcul["total"]

        if (montant_donne_txt or "").strip():
            donne = parse_nombre(montant_donne_txt, "Montant donné", minimum=0)
            if donne + 0.004 < total:
                raise ErreurMetier(f"Montant insuffisant : il manque {fmt_prix(total - donne)}.")
        else:
            donne = total
        monnaie = _r(donne - total)

        cout_total = _r(sum(int(l["quantite"]) * p["prix_achat"] for l, p in zip(lignes, produits)))
        benefice = _r(total - cout_total)
        if client_id and conn.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone() is None:
            client_id = None
        ticket_id = conn.execute(
            """INSERT INTO tickets (session_id, utilisateur_id, client_id, sous_total, remise_totale, total,
                                    cout_total, benefice, montant_donne, monnaie_rendue, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session["id"], utilisateur["id"], client_id, calcul["sous_total"], calcul["remise_totale"],
             total, cout_total, benefice, donne, monnaie, note)).lastrowid

        quantite_totale = 0
        for ligne, produit, calcule, brut in zip(lignes, produits, calcul["lignes"], a_calculer):
            quantite = int(ligne["quantite"])
            quantite_totale += quantite
            code_barre = (produit["codes_barres"] or "").split(" ")[0] or None
            conn.execute(
                """INSERT INTO lignes_ticket (ticket_id, produit_id, code_barre, designation, quantite,
                       prix_unitaire, remise_ligne, total_ligne, cout_unitaire)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticket_id, produit["id"], code_barre, produit["nom"], quantite, brut["prix_unitaire"],
                 calcule["remise_ligne"], calcule["total_ligne"], produit["prix_achat"]))
            conn.execute("UPDATE produits_caisse SET quantite_stock = quantite_stock - ? WHERE id = ?",
                         (quantite, produit["id"]))

        avertissements: List[str] = []
        for produit_id in sorted({p["id"] for p in produits}):
            apres = obtenir(conn, produit_id)
            if apres["quantite_stock"] < 0:
                avertissements.append(f"Stock négatif : {apres['nom']} ({apres['quantite_stock']})")
        details = f"Ticket #{ticket_id} — {utilisateur['nom']}"
        if modifs:
            details += " — " + " ; ".join(modifs)[:400]
        logs_caisse_repo.ajouter(conn, "VENTE", utilisateur["id"], session["id"],
                                 produit_nom=f"Ticket #{ticket_id} ({len(lignes)} article(s))",
                                 quantite=quantite_totale, prix=total, benefice=benefice,
                                 ticket_id=ticket_id, details=details)
    return {"ticket_id": ticket_id, "total": total, "monnaie": monnaie, "benefice": benefice,
            "session_id": session["id"], "avertissements": avertissements}


def annuler_ticket(conn: sqlite3.Connection, ticket_id: int, utilisateur) -> None:
    """Annule un ticket (ADMIN, session non clôturée, sans retour) : stock remis, ticket exclu des chiffres."""
    utilisateurs_service.exiger_admin(utilisateur, "L'annulation d'un ticket est réservée à l'administrateur.")
    ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        raise ErreurMetier("Ticket introuvable.")
    if ticket["statut"] == "ANNULE":
        raise ErreurMetier("Ce ticket est déjà annulé.")
    session = session_service.lire(conn, ticket["session_id"])
    if session["statut"] == "CLOTUREE":
        raise ErreurMetier("La session de ce ticket est clôturée : faites un retour (ou un mouvement de caisse) "
                           "au lieu d'annuler.")
    lignes = conn.execute("SELECT * FROM lignes_ticket WHERE ticket_id = ?", (ticket_id,)).fetchall()
    if any(l["quantite_retournee"] for l in lignes):
        raise ErreurMetier("Ce ticket a déjà des articles retournés : il ne peut plus être annulé.")
    with transaction(conn):
        for l in lignes:
            conn.execute("UPDATE produits_caisse SET quantite_stock = quantite_stock + ? WHERE id = ?",
                         (l["quantite"], l["produit_id"]))
        conn.execute("UPDATE tickets SET statut = 'ANNULE' WHERE id = ?", (ticket_id,))
        logs_caisse_repo.ajouter(
            conn, "ANNULATION", utilisateur["id"], ticket["session_id"], produit_nom=f"Ticket #{ticket_id} annulé",
            quantite=sum(l["quantite"] for l in lignes), prix=-ticket["total"], benefice=-ticket["benefice"],
            ticket_id=ticket_id, details=f"Ticket #{ticket_id} annulé par {utilisateur['nom']} ; stock remis")


def lister_tickets(conn: sqlite3.Connection, numero: Optional[int] = None, limite: int = 40) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT t.*, u.nom AS utilisateur_nom, (SELECT COUNT(*) FROM lignes_ticket WHERE ticket_id = t.id) AS nb_lignes "
        "FROM tickets t JOIN utilisateurs u ON u.id = t.utilisateur_id WHERE (? IS NULL OR t.id = ?) "
        "ORDER BY t.id DESC LIMIT ?", (numero, numero, limite)).fetchall()


def lignes_du_ticket(conn: sqlite3.Connection, ticket_id: int) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM lignes_ticket WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()


# ============================================================ MISE EN ATTENTE
def mettre_en_attente(conn: sqlite3.Connection, utilisateur, panier: List[dict], remise_type: Optional[str] = None,
                      remise_valeur=0, libelle: Optional[str] = None) -> int:
    if not panier:
        raise ErreurMetier("Le panier est vide.")
    contenu = json.dumps({"lignes": panier, "remise_type": remise_type, "remise_valeur": remise_valeur})
    return conn.execute("INSERT INTO tickets_en_attente (utilisateur_id, libelle, contenu) VALUES (?, ?, ?)",
                        (utilisateur["id"], (libelle or "").strip() or None, contenu)).lastrowid


def lister_attentes(conn: sqlite3.Connection) -> List[dict]:
    resultats = []
    for ligne in conn.execute(
            "SELECT a.*, u.nom AS utilisateur_nom FROM tickets_en_attente a "
            "JOIN utilisateurs u ON u.id = a.utilisateur_id ORDER BY a.id").fetchall():
        contenu = json.loads(ligne["contenu"])
        try:
            total = calculer_panier(contenu["lignes"], contenu.get("remise_type"), contenu.get("remise_valeur"))["total"]
        except (ErreurMetier, KeyError, ValueError):
            total = 0.0
        resultats.append({"id": ligne["id"], "date": ligne["date_creation"], "libelle": ligne["libelle"],
                          "utilisateur_nom": ligne["utilisateur_nom"],
                          "nb_articles": sum(int(l["quantite"]) for l in contenu["lignes"]), "total": total})
    return resultats


def reprendre_attente(conn: sqlite3.Connection, attente_id: int) -> dict:
    """Retourne le panier mis de côté (données produit rafraîchies) et supprime l'attente."""
    ligne = conn.execute("SELECT * FROM tickets_en_attente WHERE id = ?", (attente_id,)).fetchone()
    if ligne is None:
        raise ErreurMetier("Ce ticket en attente n'existe plus.")
    contenu = json.loads(ligne["contenu"])
    lignes, avertissements = [], []
    for l in contenu["lignes"]:
        produit = obtenir(conn, int(l["produit_id"]))
        if produit is None:
            avertissements.append(f"« {l.get('designation', '?')} » n'existe plus : ligne retirée.")
            continue
        l["designation"], l["stock"], l["prix_catalogue"] = produit["nom"], produit["quantite_stock"], produit["prix_vente"]
        lignes.append(l)
    with transaction(conn):
        conn.execute("DELETE FROM tickets_en_attente WHERE id = ?", (attente_id,))
    return {"lignes": lignes, "remise_type": contenu.get("remise_type"),
            "remise_valeur": contenu.get("remise_valeur") or 0, "avertissements": avertissements}


def supprimer_attente(conn: sqlite3.Connection, attente_id: int) -> None:
    conn.execute("DELETE FROM tickets_en_attente WHERE id = ?", (attente_id,))


# ===================================================================== RETOURS
def valider_retour(conn: sqlite3.Connection, lignes: List[dict], utilisateur, ticket_id: Optional[int] = None,
                   motif: Optional[str] = None) -> dict:
    """Enregistre un retour client et rembourse en espèces (pris dans la session de caisse active).

    Retour sur ticket : chaque ligne = {ligne_ticket_id, quantite, remis_en_stock} ; remboursement au
    prix réellement payé (remises comprises). Retour libre : {produit_id, quantite, remis_en_stock,
    prix_rembourse_unitaire (facultatif : prix de vente actuel par défaut)}.
    remis_en_stock = False : produit abîmé, perdu (il ne retourne pas en stock).
    """
    if utilisateur is None:
        raise ErreurMetier("Aucun utilisateur connecté.")
    if not lignes:
        raise ErreurMetier("Ajoutez au moins un article à retourner.")
    session = session_service.exiger_session_active(conn)
    with transaction(conn):
        preparees: List[dict] = []
        if ticket_id is not None:
            ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if ticket is None:
                raise ErreurMetier("Ticket introuvable.")
            if ticket["statut"] == "ANNULE":
                raise ErreurMetier("Ce ticket a été annulé : rien à rembourser.")
            demandees: Dict[int, int] = {}
            for l in lignes:
                if not l.get("ligne_ticket_id"):
                    raise ErreurMetier("Retour sur ticket : chaque ligne doit venir du ticket.")
                demandees[l["ligne_ticket_id"]] = demandees.get(l["ligne_ticket_id"], 0) + int(l["quantite"])
            for l in lignes:
                source = conn.execute("SELECT * FROM lignes_ticket WHERE id = ? AND ticket_id = ?",
                                      (l["ligne_ticket_id"], ticket_id)).fetchone()
                if source is None:
                    raise ErreurMetier("Une ligne ne fait pas partie de ce ticket.")
                quantite = int(l["quantite"])
                if quantite <= 0:
                    raise ErreurMetier("La quantité retournée doit être d'au moins 1.")
                if demandees[source["id"]] > source["quantite"] - source["quantite_retournee"]:
                    raise ErreurMetier(
                        f"« {source['designation']} » : vous ne pouvez rendre que "
                        f"{source['quantite'] - source['quantite_retournee']} article(s) (déjà retourné : "
                        f"{source['quantite_retournee']}).")
                remboursement = _r(source["total_ligne"] * quantite / source["quantite"])
                preparees.append({"source": source, "produit_id": source["produit_id"], "designation": source["designation"],
                                  "quantite": quantite, "remboursement": remboursement,
                                  "cout_unitaire": source["cout_unitaire"], "remis": bool(l.get("remis_en_stock", True))})
        else:
            for l in lignes:
                if l.get("ligne_ticket_id"):
                    raise ErreurMetier("Retour libre : les lignes ne doivent pas venir d'un ticket.")
                produit = obtenir(conn, int(l["produit_id"]))
                if produit is None:
                    raise ErreurMetier("Un produit du retour n'existe plus.")
                quantite = int(l["quantite"])
                if quantite <= 0:
                    raise ErreurMetier("La quantité retournée doit être d'au moins 1.")
                prix = l.get("prix_rembourse_unitaire")
                prix = produit["prix_vente"] if prix is None else float(prix)
                if prix < 0:
                    raise ErreurMetier("Un prix remboursé ne peut pas être négatif.")
                preparees.append({"source": None, "produit_id": produit["id"], "designation": produit["nom"],
                                  "quantite": quantite, "remboursement": _r(quantite * prix),
                                  "cout_unitaire": produit["prix_achat"], "remis": bool(l.get("remis_en_stock", True))})

        total = _r(sum(p["remboursement"] for p in preparees))
        retour_id = conn.execute(
            "INSERT INTO retours (session_id, utilisateur_id, ticket_id, total_rembourse, motif) VALUES (?, ?, ?, ?, ?)",
            (session["id"], utilisateur["id"], ticket_id, total, (motif or "").strip() or None)).lastrowid
        cout_recupere = 0.0
        pertes = 0
        for p in preparees:
            conn.execute(
                """INSERT INTO lignes_retour (retour_id, produit_id, ligne_ticket_id, designation, quantite,
                       prix_rembourse_unitaire, cout_unitaire, remis_en_stock) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (retour_id, p["produit_id"], p["source"]["id"] if p["source"] else None, p["designation"],
                 p["quantite"], p["remboursement"] / p["quantite"], p["cout_unitaire"], 1 if p["remis"] else 0))
            if p["source"] is not None:
                conn.execute("UPDATE lignes_ticket SET quantite_retournee = quantite_retournee + ? WHERE id = ?",
                             (p["quantite"], p["source"]["id"]))
            if p["remis"]:
                conn.execute("UPDATE produits_caisse SET quantite_stock = quantite_stock + ? WHERE id = ?",
                             (p["quantite"], p["produit_id"]))
                cout_recupere += p["quantite"] * p["cout_unitaire"]
            else:
                pertes += p["quantite"]
        benefice = _r(-(total - cout_recupere))
        details = f"Retour #{retour_id} — " + (f"ticket #{ticket_id}" if ticket_id else "retour libre")
        if pertes:
            details += f" — {pertes} article(s) perdu(s) (non remis en stock)"
        if (motif or "").strip():
            details += f" — {motif.strip()}"
        logs_caisse_repo.ajouter(conn, "RETOUR", utilisateur["id"], session["id"],
                                 produit_nom=f"Retour #{retour_id} ({len(preparees)} article(s))",
                                 quantite=sum(p["quantite"] for p in preparees), prix=-total, benefice=benefice,
                                 ticket_id=ticket_id, details=details)
    return {"retour_id": retour_id, "total_rembourse": total, "session_id": session["id"]}
