"""Exceptions de l'application."""


class ErreurMetier(Exception):
    """Erreur de validation ou de règle métier.

    Le message est écrit en français et peut être affiché tel quel
    à l'utilisateur.
    """
