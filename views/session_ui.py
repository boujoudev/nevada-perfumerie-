"""Aide à l'interface pour les sessions de caisse (bandeau d'état, ouverture à la demande)."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from services import session_service
from utils.contexte import Contexte
from utils.erreurs import ErreurMetier
from utils.formatage import fmt_datetime
from views.dialogues_session import DialogueOuvertureSession
from views.style import ROUGE, VERT
from views.widgets import afficher_erreur, afficher_info, confirmer

ORANGE = "#b45309"


def etat_session(ctx: Contexte) -> Tuple[str, str, bool]:
    """(texte, couleur, action_necessaire) pour le bandeau « session » des écrans de vente."""
    active = session_service.session_active(ctx.conn)
    if active is None:
        return "⚠ Aucune session de caisse ouverte", ROUGE, True
    texte = (f"Session n°{active['id']} — {active['utilisateur_nom']} "
             f"(ouverte {fmt_datetime(active['date_ouverture'])})")
    if active["utilisateur_id"] != ctx.utilisateur_id:
        return texte + " — ce n'est pas votre session", ORANGE, True
    return texte, VERT, False


def ouvrir_ma_session(ctx: Contexte, parent, apres: Optional[Callable[[int], None]] = None) -> None:
    """Ouvre la session de l'utilisateur connecté, ou reprend la sienne si elle est en pause.

    `apres(session_id)` est appelé quand la session est prête (les dialogues ne bloquent pas).
    """
    existante = session_service.session_de_utilisateur(ctx.conn, ctx.utilisateur_id)
    if existante is None:
        DialogueOuvertureSession(parent.winfo_toplevel(), ctx, apres)
        return
    if existante["statut"] == "OUVERTE":
        afficher_info(parent, "Votre session est déjà la session active.")
        return
    if confirmer(parent, f"Vous avez la session n°{existante['id']} en pause.\n"
                         "La reprendre ? (la session active actuelle passera en pause)"):
        try:
            session_service.reprendre_session(ctx.conn, existante["id"], ctx.utilisateur)
        except ErreurMetier as erreur:
            afficher_erreur(parent, str(erreur))
            return
        if apres:
            apres(existante["id"])


def assurer_session(ctx: Contexte, parent, apres: Optional[Callable[[int], None]] = None) -> bool:
    """True si une session est active. Sinon propose d'en ouvrir une (et retourne False)."""
    if session_service.session_active(ctx.conn) is not None:
        return True
    afficher_info(parent, "Aucune session de caisse n'est ouverte : ouvrez la vôtre pour pouvoir vendre.")
    ouvrir_ma_session(ctx, parent, apres)
    return False
