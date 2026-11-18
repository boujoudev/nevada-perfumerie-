"""Contexte partagé par tous les écrans : base de données, utilisateur connecté, droits."""

from __future__ import annotations

import sqlite3
from typing import Optional

from services.utilisateurs_service import autorise


class Contexte:
    def __init__(self, conn: sqlite3.Connection, app=None):
        self.conn = conn
        self.app = app                       # l'application (pour revenir à l'accueil, etc.)
        self.utilisateur: Optional[sqlite3.Row] = None

    @property
    def utilisateur_id(self) -> Optional[int]:
        return self.utilisateur["id"] if self.utilisateur is not None else None

    @property
    def est_admin(self) -> bool:
        return self.utilisateur is not None and self.utilisateur["role"] == "ADMIN"

    def peut(self, action: str) -> bool:
        """Le rôle de l'utilisateur connecté a-t-il le droit d'effectuer cette action ?"""
        return self.utilisateur is not None and autorise(self.utilisateur["role"], action)
