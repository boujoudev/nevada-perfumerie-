"""Statistiques et journal du module cosmétique (caisse)."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from repositories import logs_caisse_repo
from services import stats_service

FILTRES_TYPE: Dict[str, Optional[Tuple[str, ...]]] = {
    "Tous": None,
    "Ventes": ("VENTE",),
    "Retours": ("RETOUR",),
    "Annulations": ("ANNULATION",),
    "Stock (achats, inventaires)": ("ACHAT", "AJUSTEMENT", "IMPORT"),
    "Caisse (sessions, mouvements)": ("OUVERTURE", "PAUSE", "REPRISE", "CLOTURE", "MOUVEMENT_CAISSE"),
    "Produits": ("CREATION", "MODIFICATION", "SUPPRESSION"),
    "Connexions": ("CONNEXION",),
}


def resume_periode(conn: sqlite3.Connection, debut: Optional[str], fin: Optional[str]) -> dict:
    """Chiffres d'une période : ventes, retours, CA net, dépense nette (coût), bénéfice net, tickets."""
    t = conn.execute(
        """SELECT COALESCE(SUM(total), 0) AS ventes, COALESCE(SUM(benefice), 0) AS benefice, COUNT(*) AS nb
           FROM tickets WHERE statut = 'VALIDE' AND (? IS NULL OR date_ticket >= ?) AND (? IS NULL OR date_ticket < ?)""",
        (debut, debut, fin, fin)).fetchone()
    r = conn.execute(
        """SELECT COALESCE(SUM(r.total_rembourse), 0) AS rembourse, COUNT(*) AS nb
           FROM retours r WHERE (? IS NULL OR r.date_retour >= ?) AND (? IS NULL OR r.date_retour < ?)""",
        (debut, debut, fin, fin)).fetchone()
    # coût des articles remis en stock : récupéré (le bénéfice n'est réduit que de la marge perdue)
    recupere = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN lr.remis_en_stock = 1 THEN lr.quantite * lr.cout_unitaire ELSE 0 END), 0)
           FROM lignes_retour lr JOIN retours r ON r.id = lr.retour_id
           WHERE (? IS NULL OR r.date_retour >= ?) AND (? IS NULL OR r.date_retour < ?)""",
        (debut, debut, fin, fin)).fetchone()[0]
    ventes, rembourse = t["ventes"], r["rembourse"]
    ca_net = round(ventes - rembourse, 2)
    benefice = round(t["benefice"] - (rembourse - recupere), 2)
    return {"ventes": round(ventes, 2), "retours": round(rembourse, 2), "ca_net": ca_net,
            "cout": round(ca_net - benefice, 2), "benefice": benefice, "nb_tickets": t["nb"],
            "nb_retours": r["nb"], "panier_moyen": round(ventes / t["nb"], 2) if t["nb"] else 0.0}


def resume_standard(conn: sqlite3.Connection, aujourdhui: Optional[date] = None) -> Dict[str, dict]:
    return {p: resume_periode(conn, *stats_service.bornes(p, aujourdhui=aujourdhui))
            for p in ("Aujourd'hui", "Ce mois", "Cette année")}


def top_produits(conn: sqlite3.Connection, n: int = 5, par: str = "quantite", debut: Optional[str] = None,
                 fin: Optional[str] = None) -> List[sqlite3.Row]:
    """Produits les plus vendus (par='quantite') ou les plus rentables (par='benefice'), hors retours."""
    ordre = "benefice DESC, quantite DESC" if par == "benefice" else "quantite DESC, benefice DESC"
    return conn.execute(
        f"""SELECT MAX(l.designation) AS nom, SUM(l.quantite - l.quantite_retournee) AS quantite,
                   SUM((l.quantite - l.quantite_retournee) * (l.total_ligne * 1.0 / l.quantite - l.cout_unitaire)) AS benefice
            FROM lignes_ticket l JOIN tickets t ON t.id = l.ticket_id AND t.statut = 'VALIDE'
            WHERE (? IS NULL OR t.date_ticket >= ?) AND (? IS NULL OR t.date_ticket < ?)
            GROUP BY l.produit_id HAVING SUM(l.quantite - l.quantite_retournee) > 0
            ORDER BY {ordre} LIMIT ?""", (debut, debut, fin, fin, n)).fetchall()


def valeur_stock(conn: sqlite3.Connection) -> float:
    """Somme prix d'achat × stock (les stocks négatifs comptent pour 0)."""
    return round(conn.execute(
        "SELECT COALESCE(SUM(MAX(quantite_stock, 0) * prix_achat), 0) FROM produits_caisse WHERE actif = 1"
    ).fetchone()[0], 2)


def lister_logs(conn: sqlite3.Connection, debut: Optional[str], fin: Optional[str],
                filtre_type: str = "Tous") -> List[sqlite3.Row]:
    """Logs filtrés ; « Ventes » ne montre que les tickets non annulés."""
    return logs_caisse_repo.lister(conn, debut, fin, FILTRES_TYPE.get(filtre_type),
                                   ventes_valides_seulement=(filtre_type == "Ventes"))


def totaux_logs(logs: Sequence[sqlite3.Row]) -> dict:
    """ca = ventes - annulations - retours ; cout = ca - bénéfice ; achats = réceptions de stock."""
    types_ca = ("VENTE", "ANNULATION", "RETOUR")
    ca = sum(l["prix"] or 0 for l in logs if l["type"] in types_ca)
    benefice = sum(l["benefice"] or 0 for l in logs if l["type"] in types_ca)
    achats = sum(l["prix"] or 0 for l in logs if l["type"] == "ACHAT")
    return {"ca": round(ca, 2), "cout": round(ca - benefice, 2), "benefice": round(benefice, 2),
            "achats": round(achats, 2)}
