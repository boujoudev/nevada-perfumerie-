"""Module COSMÉTIQUE : la caisse (scan, panier, retours, stock, logs) + session de caisse."""

from __future__ import annotations

import sqlite3

from utils.contexte import Contexte
from views.caisse_view import CaisseView
from views.logs_caisse_view import LogsCaisseView
from views.module_base import ModuleBase
from views.retours_view import RetoursView
from views.sessions_view import SessionsView
from views.stock_caisse_view import StockCaisseView


class ModuleCosmetique(ModuleBase):
    def __init__(self, master, app, ctx: Contexte):
        conn: sqlite3.Connection = ctx.conn
        definitions = [
            ("Caisse", "🧾  Caisse", "caisse_vente", lambda c: CaisseView(c, conn, ctx)),
            ("Retours", "↩  Retours", "caisse_retour", lambda c: RetoursView(c, conn, ctx)),
            ("Stock", "📦  Stock", "caisse_stock_lecture", lambda c: StockCaisseView(c, conn, ctx)),
            ("Logs", "📊  Logs & Stats", "caisse_logs_stats", lambda c: LogsCaisseView(c, conn, ctx)),
            ("Session", "💰  Session de caisse", "session", lambda c: SessionsView(c, conn, ctx)),
        ]
        super().__init__(master, app, ctx, "Cosmétique", definitions, ("Caisse",))
