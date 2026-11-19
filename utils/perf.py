"""Mesure de la lenteur de l'interface, écrite dans application.log (marche aussi dans l'.exe).

  * Toute action plus lente que SEUIL_S est journalisée : « LENT : Parfum › Stock = 850 ms (construction 600 ms ... ) ».
  * NEVADA_PERF=1   : journalise TOUTES les actions (pour comparer).
  * NEVADA_EMPILER=1: affichage alternatif des écrans (empilés + tkraise au lieu de cacher/réafficher),
                      parfois plus rapide avec CustomTkinter. À comparer avec le mode normal.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, List, Tuple

VERBEUX = os.environ.get("NEVADA_PERF") == "1"
EMPILER = os.environ.get("NEVADA_EMPILER") == "1"
SEUIL_S = 0.30
journal = logging.getLogger("perf")


class Chrono:
    """Chronomètre avec étapes : construction, affichage, rechargement des données, mise en page."""

    def __init__(self, nom: str, horloge: Callable[[], float] = time.perf_counter):
        self.nom, self._horloge = nom, horloge
        self.debut = self._dernier = horloge()
        self.etapes: List[Tuple[str, float]] = []

    def etape(self, libelle: str) -> None:
        maintenant = self._horloge()
        self.etapes.append((libelle, maintenant - self._dernier))
        self._dernier = maintenant

    def fin(self) -> float:
        total = self._horloge() - self.debut
        detail = ", ".join(f"{lib} {duree * 1000:.0f} ms" for lib, duree in self.etapes if duree >= 0.005) or "—"
        if total >= SEUIL_S:
            journal.warning("LENT : %s = %.0f ms (%s)", self.nom, total * 1000, detail)
        elif VERBEUX:
            journal.info("%s = %.0f ms (%s)", self.nom, total * 1000, detail)
        return total
