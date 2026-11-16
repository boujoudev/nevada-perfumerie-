"""Statistiques, filtres du journal et export CSV."""

from __future__ import annotations

import csv
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from repositories import logs_repo
from utils.erreurs import ErreurMetier

LIBELLES_TYPE = {
    "VENTE": "Vente", "ACHAT": "Achat", "ANNULATION": "Annulation",
    "CREATION": "Création", "MODIFICATION": "Modification",
    "SUPPRESSION": "Suppression", "AJUSTEMENT": "Ajustement",
}

FILTRES_TYPE: Dict[str, Optional[Tuple[str, ...]]] = {
    "Tous": None,
    "Ventes": ("VENTE",),
    "Achats": ("ACHAT",),
    "Annulations": ("ANNULATION",),
    "Autres": ("CREATION", "MODIFICATION", "SUPPRESSION", "AJUSTEMENT"),
}

PERIODES = ("Aujourd'hui", "Cette semaine", "Ce mois", "Cette année", "Tout", "Personnalisé")


def _parse_date(texte: str, libelle: str) -> Optional[date]:
    texte = (texte or "").strip()
    if not texte:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            continue
    raise ErreurMetier(f"« {libelle} » : date invalide (format attendu JJ/MM/AAAA).")


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d 00:00:00")


def bornes(periode: str, perso_debut: str = "", perso_fin: str = "",
           aujourdhui: Optional[date] = None) -> Tuple[Optional[str], Optional[str]]:
    """Retourne (debut inclus, fin exclue) sous forme de texte SQL, ou (None, None) pour 'Tout'."""
    jour = aujourdhui or date.today()
    if periode == "Aujourd'hui":
        debut, fin = jour, jour + timedelta(days=1)
    elif periode == "Cette semaine":
        debut = jour - timedelta(days=jour.weekday())
        fin = debut + timedelta(days=7)
    elif periode == "Ce mois":
        debut = jour.replace(day=1)
        fin = (debut + timedelta(days=32)).replace(day=1)
    elif periode == "Cette année":
        debut, fin = date(jour.year, 1, 1), date(jour.year + 1, 1, 1)
    elif periode == "Personnalisé":
        d = _parse_date(perso_debut, "Date de début")
        f = _parse_date(perso_fin, "Date de fin")
        if d and f and d > f:
            raise ErreurMetier("La date de début doit être avant la date de fin.")
        return (_fmt(d) if d else None, _fmt(f + timedelta(days=1)) if f else None)
    else:  # "Tout"
        return None, None
    return _fmt(debut), _fmt(fin)


def resume_periode(conn: sqlite3.Connection, debut: Optional[str], fin: Optional[str]) -> dict:
    """Chiffre d'affaires, bénéfice et nombre de ventes sur une période."""
    row = conn.execute(
        """SELECT COALESCE(SUM(total), 0) AS ca, COALESCE(SUM(cout_total), 0) AS cout,
                  COALESCE(SUM(benefice), 0) AS benefice, COUNT(*) AS nb_ventes
           FROM ventes WHERE (? IS NULL OR date_vente >= ?) AND (? IS NULL OR date_vente < ?)""",
        (debut, debut, fin, fin)).fetchone()
    return {"ca": round(row["ca"], 2), "cout": round(row["cout"], 2),
            "benefice": round(row["benefice"], 2), "nb_ventes": row["nb_ventes"]}


def resume_standard(conn: sqlite3.Connection, aujourdhui: Optional[date] = None) -> Dict[str, dict]:
    """Résumé du jour, du mois et de l'année."""
    return {nom: resume_periode(conn, *bornes(p, aujourdhui=aujourdhui))
            for nom, p in (("Aujourd'hui", "Aujourd'hui"), ("Ce mois", "Ce mois"),
                           ("Cette année", "Cette année"))}


def top_parfums(conn: sqlite3.Connection, n: int = 5) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT parfum_nom AS nom, COUNT(*) AS nb_ventes, SUM(qnt_parfum_ml) AS total_ml
           FROM lignes_vente GROUP BY parfum_nom ORDER BY nb_ventes DESC, total_ml DESC LIMIT ?""",
        (n,)).fetchall()


def top_parfums_benefice(conn: sqlite3.Connection, n: int = 5) -> List[sqlite3.Row]:
    """Parfums classés par bénéfice total généré (et non par quantité vendue)."""
    return conn.execute(
        """SELECT parfum_nom AS nom, COUNT(*) AS nb_ventes, SUM(benefice) AS benefice_total
           FROM lignes_vente GROUP BY parfum_nom
           ORDER BY benefice_total DESC, nb_ventes DESC LIMIT ?""", (n,)).fetchall()


def top_flacons(conn: sqlite3.Connection, n: int = 5) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT flacon_nom AS nom, COUNT(*) AS nb_ventes FROM lignes_vente
           GROUP BY flacon_nom ORDER BY nb_ventes DESC LIMIT ?""", (n,)).fetchall()


def valeur_stock(conn: sqlite3.Connection) -> float:
    """Somme prix_achat × stock (les stocks négatifs comptent pour 0)."""
    total = 0.0
    for table, stock, prix in (("flacons", "quantite_stock", "prix_achat"),
                               ("parfums", "quantite_stock_ml", "prix_achat_100ml / 100.0"),
                               ("alcools", "quantite_stock_ml", "prix_achat_litre / 1000.0")):
        row = conn.execute(
            f"SELECT COALESCE(SUM(MAX({stock}, 0) * {prix}), 0) AS v FROM {table} WHERE actif = 1"
        ).fetchone()
        total += row["v"]
    return round(total, 2)


def lister_logs(conn: sqlite3.Connection, debut: Optional[str], fin: Optional[str],
                filtre_type: str = "Tous") -> List[sqlite3.Row]:
    """Logs filtrés. Le filtre « Ventes » ne montre que les ventes toujours existantes
    (une vente supprimée disparaît de cette vue ; elle reste visible dans « Tous »)."""
    return logs_repo.lister(conn, debut, fin, FILTRES_TYPE.get(filtre_type),
                            ventes_existantes_seulement=(filtre_type == "Ventes"))


def totaux_logs(logs: Sequence[sqlite3.Row]) -> dict:
    """Totaux des logs affichés.

    ca        : ventes nettes (ventes moins ventes supprimées)
    cout      : dépense nette = coût d'achat des produits vendus (ca - bénéfice)
    benefice  : bénéfice net
    achats    : argent dépensé en réapprovisionnement de stock (lignes « Achat »)
    """
    ca = sum(l["prix"] or 0 for l in logs if l["type"] in ("VENTE", "ANNULATION"))
    benefice = sum(l["benefice"] or 0 for l in logs if l["type"] in ("VENTE", "ANNULATION"))
    achats = sum(l["prix"] or 0 for l in logs if l["type"] == "ACHAT")
    return {"ca": round(ca, 2), "cout": round(ca - benefice, 2),
            "benefice": round(benefice, 2), "achats": round(achats, 2)}


def _csv_nombre(valeur) -> str:
    if valeur is None:
        return ""
    texte = f"{float(valeur):.2f}".rstrip("0").rstrip(".")
    return texte.replace(".", ",")


def exporter_csv(chemin: str, logs: Sequence[sqlite3.Row]) -> int:
    """Écrit un CSV lisible par Excel (séparateur ';', UTF-8 avec BOM). Retourne le nombre de lignes."""
    try:
        with open(chemin, "w", newline="", encoding="utf-8-sig") as fichier:
            ecrivain = csv.writer(fichier, delimiter=";")
            ecrivain.writerow(["Date/Heure", "Type", "Produit", "Quantité", "Prix (DA)",
                               "Bénéfice (DA)", "Détails"])
            for l in logs:
                ecrivain.writerow([l["date_log"], LIBELLES_TYPE.get(l["type"], l["type"]),
                                   l["produit_nom"] or "", _csv_nombre(l["quantite"]),
                                   _csv_nombre(l["prix"]), _csv_nombre(l["benefice"]),
                                   l["details"] or ""])
    except OSError as erreur:
        raise ErreurMetier(
            f"Impossible d'écrire le fichier (est-il ouvert dans Excel ?) : {erreur}") from None
    return len(logs)
