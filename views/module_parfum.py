"""Module PARFUM : le logiciel de la parfumerie (création, stock, vente, logs) + session de caisse."""

from __future__ import annotations

import sqlite3

from utils.contexte import Contexte
from views.creation_view import CreationView
from views.logs_view import LogsView
from views.module_base import ModuleBase
from views.parametres_view import ParametresView
from views.sessions_view import SessionsView
from views.stock_view import StockView
from views.vente_view import VenteView


class ModuleParfum(ModuleBase):
    def __init__(self, master, app, ctx: Contexte):
        conn: sqlite3.Connection = ctx.conn
        definitions = [
            ("Création", "➕  Création", "parfum_creation", lambda c: CreationView(c, conn)),
            ("Stock", "📦  Stock", "parfum_stock", lambda c: StockView(c, conn)),
            ("Vente", "🛒  Vente", "parfum_vente", lambda c: VenteView(c, conn, ctx)),
            ("Logs", "📊  Logs & Stats", "parfum_logs", lambda c: LogsView(c, conn, ctx)),
            ("Session", "💰  Session de caisse", "session", lambda c: SessionsView(c, conn, ctx)),
            ("Paramètres", "⚙  Paramètres", "parfum_parametres", lambda c: ParametresView(c, conn, ctx)),
        ]
        super().__init__(master, app, ctx, "Parfumerie", definitions, ("Vente", "Stock"))
