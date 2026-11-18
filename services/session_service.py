"""Sessions de caisse : une session = un employé + le tiroir-caisse.

Règles :
  * UNE seule session OUVERTE à la fois : les ventes (cosmétique ET parfum) vont dans celle-là.
  * On peut changer d'employé sans clôturer : l'ancienne session passe EN_PAUSE (elle reste à clôturer).
  * Clôture : on compte l'argent ; écart = espèces comptées - espèces attendues (négatif = manque).
  * Une session CLOTUREE est figée : ses chiffres ne changent plus.

  espèces attendues = fond d'ouverture + ventes cosmétique + ventes parfum + entrées de caisse
                      - remboursements de retours - sorties de caisse
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from database.connection import transaction
from repositories import logs_caisse_repo
from services import stats_service, utilisateurs_service
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime, fmt_prix, parse_nombre

LIBELLES_STATUT = {"OUVERTE": "Ouverte (active)", "EN_PAUSE": "En pause", "CLOTUREE": "Clôturée"}


# ---------------------------------------------------------------------- lecture
def lire(conn: sqlite3.Connection, session_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT s.*, u.nom AS utilisateur_nom FROM sessions_caisse s "
        "JOIN utilisateurs u ON u.id = s.utilisateur_id WHERE s.id = ?", (session_id,)).fetchone()


def session_active(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """La session OUVERTE (celle où vont les ventes), ou None."""
    ligne = conn.execute("SELECT id FROM sessions_caisse WHERE statut = 'OUVERTE'").fetchone()
    return lire(conn, ligne["id"]) if ligne else None


def session_de_utilisateur(conn: sqlite3.Connection, utilisateur_id: int) -> Optional[sqlite3.Row]:
    """La session non clôturée (ouverte ou en pause) de cet utilisateur, ou None."""
    ligne = conn.execute(
        "SELECT id FROM sessions_caisse WHERE utilisateur_id = ? AND statut != 'CLOTUREE' "
        "ORDER BY id DESC", (utilisateur_id,)).fetchone()
    return lire(conn, ligne["id"]) if ligne else None


def exiger_session_active(conn: sqlite3.Connection) -> sqlite3.Row:
    session = session_active(conn)
    if session is None:
        raise ErreurMetier("Aucune session de caisse n'est ouverte. Ouvrez une session pour vendre.")
    return session


def derniere_cloturee(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions_caisse WHERE statut = 'CLOTUREE' ORDER BY date_cloture DESC, id DESC"
    ).fetchone()


def fond_suggere(conn: sqlite3.Connection) -> float:
    """Fond proposé à l'ouverture : l'argent compté à la dernière clôture (si plus personne n'est en cours)."""
    if conn.execute("SELECT COUNT(*) FROM sessions_caisse WHERE statut != 'CLOTUREE'").fetchone()[0]:
        return 0.0
    derniere = derniere_cloturee(conn)
    return float(derniere["especes_comptees"] or 0) if derniere else 0.0


def calculer(conn: sqlite3.Connection, session_id: int) -> dict:
    """Chiffres de la session (en direct si elle n'est pas clôturée)."""
    session = lire(conn, session_id)
    if session is None:
        raise ErreurMetier("Session introuvable.")
    if session["statut"] == "CLOTUREE":
        return {
            "fond": session["fond_ouverture"], "ventes_cosmetique": session["total_ventes_cosmetique"] or 0,
            "ventes_parfum": session["total_ventes_parfum"] or 0, "retours": session["total_retours"] or 0,
            "entrees": session["entrees_caisse"] or 0, "sorties": session["sorties_caisse"] or 0,
            "attendues": session["especes_attendues"] or 0,
            "nb_tickets": _un(conn, "SELECT COUNT(*) FROM tickets WHERE session_id = ? AND statut = 'VALIDE'", session_id),
            "nb_ventes_parfum": _un(conn, "SELECT COUNT(*) FROM ventes WHERE session_id = ?", session_id),
        }
    vc = _un(conn, "SELECT COALESCE(SUM(total), 0) FROM tickets WHERE session_id = ? AND statut = 'VALIDE'", session_id)
    vp = _un(conn, "SELECT COALESCE(SUM(total), 0) FROM ventes WHERE session_id = ?", session_id)
    retours = _un(conn, "SELECT COALESCE(SUM(total_rembourse), 0) FROM retours WHERE session_id = ?", session_id)
    entrees = _un(conn, "SELECT COALESCE(SUM(montant), 0) FROM mouvements_caisse WHERE session_id = ? AND type = 'ENTREE'", session_id)
    sorties = _un(conn, "SELECT COALESCE(SUM(montant), 0) FROM mouvements_caisse WHERE session_id = ? AND type = 'SORTIE'", session_id)
    attendues = round(session["fond_ouverture"] + vc + vp + entrees - retours - sorties, 2)
    return {
        "fond": session["fond_ouverture"], "ventes_cosmetique": round(vc, 2), "ventes_parfum": round(vp, 2),
        "retours": round(retours, 2), "entrees": round(entrees, 2), "sorties": round(sorties, 2),
        "attendues": attendues,
        "nb_tickets": _un(conn, "SELECT COUNT(*) FROM tickets WHERE session_id = ? AND statut = 'VALIDE'", session_id),
        "nb_ventes_parfum": _un(conn, "SELECT COUNT(*) FROM ventes WHERE session_id = ?", session_id),
    }


def _un(conn: sqlite3.Connection, sql: str, *params):
    return conn.execute(sql, params).fetchone()[0]


def lister_sessions(conn: sqlite3.Connection, utilisateur_id: Optional[int] = None,
                    non_cloturees: Optional[bool] = None, debut: Optional[str] = None,
                    fin: Optional[str] = None, limite: int = 300) -> List[sqlite3.Row]:
    """Sessions (la plus récente d'abord). non_cloturees : True = en cours, False = clôturées, None = toutes."""
    sql = ("SELECT s.*, u.nom AS utilisateur_nom FROM sessions_caisse s "
           "JOIN utilisateurs u ON u.id = s.utilisateur_id WHERE 1 = 1")
    params: list = []
    if utilisateur_id is not None:
        sql += " AND s.utilisateur_id = ?"
        params.append(utilisateur_id)
    if non_cloturees is True:
        sql += " AND s.statut != 'CLOTUREE'"
    elif non_cloturees is False:
        sql += " AND s.statut = 'CLOTUREE'"
    if debut:
        sql += " AND s.date_ouverture >= ?"
        params.append(debut)
    if fin:
        sql += " AND s.date_ouverture < ?"
        params.append(fin)
    sql += " ORDER BY s.id DESC LIMIT ?"
    params.append(limite)
    return conn.execute(sql, params).fetchall()


# --------------------------------------------------------------------- écriture
def ouvrir_session(conn: sqlite3.Connection, utilisateur, fond_txt: str = "0") -> int:
    """Ouvre la session de cet utilisateur. L'éventuelle session active passe EN_PAUSE (non clôturée)."""
    if utilisateur is None or not utilisateur["actif"]:
        raise ErreurMetier("Utilisateur invalide.")
    fond = parse_nombre(fond_txt if (fond_txt or "").strip() else "0", "Fond de caisse", minimum=0)
    if session_de_utilisateur(conn, utilisateur["id"]) is not None:
        raise ErreurMetier("Vous avez déjà une session non clôturée : reprenez-la ou clôturez-la.")
    with transaction(conn):
        autres = _un(conn, "SELECT COUNT(*) FROM sessions_caisse WHERE statut != 'CLOTUREE'")
        ecart_passation = 0.0
        if autres == 0:
            derniere = derniere_cloturee(conn)
            if derniere is not None and derniere["especes_comptees"] is not None:
                ecart_passation = round(fond - derniere["especes_comptees"], 2)
        ancienne = conn.execute("SELECT id FROM sessions_caisse WHERE statut = 'OUVERTE'").fetchone()
        if ancienne:
            conn.execute("UPDATE sessions_caisse SET statut = 'EN_PAUSE' WHERE id = ?", (ancienne["id"],))
            logs_caisse_repo.ajouter(conn, "PAUSE", utilisateur["id"], ancienne["id"],
                                     details=f"Session #{ancienne['id']} mise en pause (changement de caisse)")
        session_id = conn.execute(
            "INSERT INTO sessions_caisse (utilisateur_id, fond_ouverture, ecart_passation) VALUES (?, ?, ?)",
            (utilisateur["id"], fond, ecart_passation)).lastrowid
        details = f"Session #{session_id} ouverte par {utilisateur['nom']} — fond {fmt_prix(fond)}"
        if ecart_passation:
            details += f" — écart de passation {fmt_prix(ecart_passation)}"
        logs_caisse_repo.ajouter(conn, "OUVERTURE", utilisateur["id"], session_id, prix=fond, details=details)
    return session_id


def mettre_en_pause(conn: sqlite3.Connection, session_id: int, utilisateur) -> None:
    session = lire(conn, session_id)
    if session is None or session["statut"] != "OUVERTE":
        raise ErreurMetier("Seule la session active peut être mise en pause.")
    _verifier_droit(session, utilisateur)
    with transaction(conn):
        conn.execute("UPDATE sessions_caisse SET statut = 'EN_PAUSE' WHERE id = ?", (session_id,))
        logs_caisse_repo.ajouter(conn, "PAUSE", utilisateur["id"], session_id,
                                 details=f"Session #{session_id} mise en pause")


def reprendre_session(conn: sqlite3.Connection, session_id: int, utilisateur) -> None:
    """Rend active une session en pause ; la session active actuelle passe EN_PAUSE."""
    session = lire(conn, session_id)
    if session is None or session["statut"] == "CLOTUREE":
        raise ErreurMetier("Cette session n'existe plus ou est déjà clôturée.")
    if session["statut"] == "OUVERTE":
        return
    _verifier_droit(session, utilisateur)
    with transaction(conn):
        ancienne = conn.execute("SELECT id FROM sessions_caisse WHERE statut = 'OUVERTE'").fetchone()
        if ancienne:
            conn.execute("UPDATE sessions_caisse SET statut = 'EN_PAUSE' WHERE id = ?", (ancienne["id"],))
            logs_caisse_repo.ajouter(conn, "PAUSE", utilisateur["id"], ancienne["id"],
                                     details=f"Session #{ancienne['id']} mise en pause (changement de caisse)")
        conn.execute("UPDATE sessions_caisse SET statut = 'OUVERTE' WHERE id = ?", (session_id,))
        logs_caisse_repo.ajouter(conn, "REPRISE", utilisateur["id"], session_id,
                                 details=f"Session #{session_id} reprise")


def _verifier_droit(session, utilisateur) -> None:
    """Un caissier ne gère que sa propre session ; l'administrateur gère toutes les sessions."""
    if utilisateur is None:
        raise ErreurMetier("Aucun utilisateur connecté.")
    if utilisateur["role"] != "ADMIN" and session["utilisateur_id"] != utilisateur["id"]:
        raise ErreurMetier("Cette session appartient à un autre utilisateur.")


def cloturer_session(conn: sqlite3.Connection, session_id: int, especes_comptees_txt: str,
                     utilisateur, note: Optional[str] = None) -> dict:
    """Clôture la session : fige les chiffres et calcule l'écart (comptées - attendues)."""
    session = lire(conn, session_id)
    if session is None:
        raise ErreurMetier("Session introuvable.")
    if session["statut"] == "CLOTUREE":
        raise ErreurMetier("Cette session est déjà clôturée.")
    _verifier_droit(session, utilisateur)
    comptees = parse_nombre(especes_comptees_txt, "Espèces comptées", minimum=0)
    with transaction(conn):
        chiffres = calculer(conn, session_id)
        ecart = round(comptees - chiffres["attendues"], 2)
        conn.execute(
            """UPDATE sessions_caisse SET statut = 'CLOTUREE', date_cloture = datetime('now', 'localtime'),
                   total_ventes_cosmetique = ?, total_ventes_parfum = ?, total_retours = ?,
                   entrees_caisse = ?, sorties_caisse = ?, especes_attendues = ?,
                   especes_comptees = ?, ecart = ?, note = ? WHERE id = ?""",
            (chiffres["ventes_cosmetique"], chiffres["ventes_parfum"], chiffres["retours"],
             chiffres["entrees"], chiffres["sorties"], chiffres["attendues"], comptees, ecart,
             (note or "").strip() or None, session_id))
        if ecart < 0:
            etat = f"MANQUE {fmt_prix(-ecart)}"
        elif ecart > 0:
            etat = f"EXCÉDENT {fmt_prix(ecart)}"
        else:
            etat = "caisse juste"
        logs_caisse_repo.ajouter(
            conn, "CLOTURE", utilisateur["id"], session_id, prix=ecart,
            details=f"Session #{session_id} de {session['utilisateur_nom']} clôturée — attendu "
                    f"{fmt_prix(chiffres['attendues'])}, compté {fmt_prix(comptees)} : {etat}")
    return {**chiffres, "especes_comptees": comptees, "ecart": ecart, "session_id": session_id}


def ajouter_mouvement(conn: sqlite3.Connection, utilisateur, type_mouvement: str, montant_txt: str,
                      motif: str) -> int:
    """Entrée ou sortie d'argent du tiroir (retrait banque, dépense, versement...) dans la session active."""
    if type_mouvement not in ("ENTREE", "SORTIE"):
        raise ErreurMetier("Type de mouvement inconnu.")
    session = exiger_session_active(conn)
    montant = parse_nombre(montant_txt, "Montant", strictement_positif=True)
    motif = (motif or "").strip()
    if not motif:
        raise ErreurMetier("Le motif est obligatoire.")
    with transaction(conn):
        identifiant = conn.execute(
            "INSERT INTO mouvements_caisse (session_id, utilisateur_id, type, montant, motif) "
            "VALUES (?, ?, ?, ?, ?)", (session["id"], utilisateur["id"], type_mouvement, montant, motif)).lastrowid
        libelle = "Entrée" if type_mouvement == "ENTREE" else "Sortie"
        logs_caisse_repo.ajouter(
            conn, "MOUVEMENT_CAISSE", utilisateur["id"], session["id"],
            prix=montant if type_mouvement == "ENTREE" else -montant,
            details=f"{libelle} de caisse {fmt_prix(montant)} — {motif}")
    return identifiant


def lister_mouvements(conn: sqlite3.Connection, session_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT m.*, u.nom AS utilisateur_nom FROM mouvements_caisse m "
        "JOIN utilisateurs u ON u.id = m.utilisateur_id WHERE m.session_id = ? ORDER BY m.id",
        (session_id,)).fetchall()


# ---------------------------------------------------------------------- rapports
def ecarts_par_utilisateur(conn: sqlite3.Connection, debut: Optional[str] = None,
                           fin: Optional[str] = None) -> List[sqlite3.Row]:
    """Écart cumulé des sessions clôturées par utilisateur (négatif = manque)."""
    return conn.execute(
        """SELECT u.nom AS nom, COUNT(*) AS nb_sessions, COALESCE(SUM(s.ecart), 0) AS ecart_total
           FROM sessions_caisse s JOIN utilisateurs u ON u.id = s.utilisateur_id
           WHERE s.statut = 'CLOTUREE' AND (? IS NULL OR s.date_cloture >= ?) AND (? IS NULL OR s.date_cloture < ?)
           GROUP BY u.id ORDER BY ecart_total ASC""", (debut, debut, fin, fin)).fetchall()


def _libelle_ecart(ecart: Optional[float]) -> str:
    if ecart is None:
        return "—"
    if ecart < 0:
        return f"MANQUE {fmt_prix(-ecart)}"
    if ecart > 0:
        return f"excédent {fmt_prix(ecart)}"
    return "caisse juste"


def rapport_session(conn: sqlite3.Connection, session_id: int) -> str:
    """Rapport texte d'une session (à afficher ou enregistrer)."""
    session = lire(conn, session_id)
    if session is None:
        raise ErreurMetier("Session introuvable.")
    c = calculer(conn, session_id)
    lignes = [
        f"RAPPORT DE SESSION n°{session_id}",
        f"Employé : {session['utilisateur_nom']}",
        f"Ouverture : {fmt_datetime(session['date_ouverture'])}",
        f"Clôture : {fmt_datetime(session['date_cloture']) if session['date_cloture'] else '(non clôturée)'}",
        f"Statut : {LIBELLES_STATUT[session['statut']]}",
        "",
        f"Fond de caisse à l'ouverture : {fmt_prix(c['fond'])}",
        f"Ventes cosmétique ({c['nb_tickets']} ticket(s)) : {fmt_prix(c['ventes_cosmetique'])}",
        f"Ventes parfum ({c['nb_ventes_parfum']} vente(s)) : {fmt_prix(c['ventes_parfum'])}",
        f"Entrées de caisse : {fmt_prix(c['entrees'])}",
        f"Remboursements (retours) : -{fmt_prix(c['retours'])}",
        f"Sorties de caisse : -{fmt_prix(c['sorties'])}",
        f"ESPÈCES ATTENDUES : {fmt_prix(c['attendues'])}",
    ]
    if session["statut"] == "CLOTUREE":
        lignes += [f"ESPÈCES COMPTÉES : {fmt_prix(session['especes_comptees'])}",
                   f"ÉCART : {_libelle_ecart(session['ecart'])}"]
    else:
        lignes.append("(session non clôturée : chiffres provisoires)")
    if session["ecart_passation"]:
        lignes.append(f"Écart de passation à l'ouverture (fond compté ≠ clôture précédente) : "
                      f"{fmt_prix(session['ecart_passation'])}")
    mouvements = lister_mouvements(conn, session_id)
    if mouvements:
        lignes += ["", "Mouvements de caisse :"]
        for m in mouvements:
            signe = "+" if m["type"] == "ENTREE" else "-"
            lignes.append(f"  {fmt_datetime(m['date_mouvement'])}  {signe}{fmt_prix(m['montant'])}  {m['motif']}"
                          f"  ({m['utilisateur_nom']})")
    if session["note"]:
        lignes += ["", f"Note : {session['note']}"]
    return "\n".join(lignes)


def rapport_journee(conn: sqlite3.Connection, jour: str = "") -> str:
    """Rapport de fin de journée : toutes les sessions ouvertes ce jour-là, par employé, avec les écarts."""
    jour = (jour or "").strip()
    debut, fin = stats_service.bornes("Personnalisé", jour, jour) if jour else stats_service.bornes("Aujourd'hui")
    sessions = list(reversed(lister_sessions(conn, debut=debut, fin=fin)))
    titre_jour = jour or "aujourd'hui"
    lignes = [f"RAPPORT DE FIN DE JOURNÉE — {titre_jour}", ""]
    if not sessions:
        return "\n".join(lignes + ["Aucune session ce jour-là."])
    total_attendu = total_compte = total_ecart = 0.0
    nb_cloturees = 0
    for s in sessions:
        c = calculer(conn, s["id"])
        ouverture = fmt_datetime(s["date_ouverture"])
        lignes.append(f"Session n°{s['id']} — {s['utilisateur_nom']} — {LIBELLES_STATUT[s['statut']]} — ouverte {ouverture}")
        lignes.append(f"   Cosmétique {fmt_prix(c['ventes_cosmetique'])} | Parfum {fmt_prix(c['ventes_parfum'])} | "
                      f"Retours -{fmt_prix(c['retours'])} | Attendu {fmt_prix(c['attendues'])}")
        if s["statut"] == "CLOTUREE":
            lignes.append(f"   Compté {fmt_prix(s['especes_comptees'])} → {_libelle_ecart(s['ecart'])}")
            total_attendu += s["especes_attendues"] or 0
            total_compte += s["especes_comptees"] or 0
            total_ecart += s["ecart"] or 0
            nb_cloturees += 1
        else:
            lignes.append("   (non clôturée)")
        if s["ecart_passation"]:
            lignes.append(f"   Écart de passation : {fmt_prix(s['ecart_passation'])}")
    lignes += ["", f"TOTAL des {nb_cloturees} session(s) clôturée(s) : attendu {fmt_prix(total_attendu)} | "
                   f"compté {fmt_prix(total_compte)} | écart {_libelle_ecart(round(total_ecart, 2))}"]
    return "\n".join(lignes)
