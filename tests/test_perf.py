"""Chronomètre de lenteur."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import perf  # noqa: E402


def horloge(*valeurs):
    suite = iter(valeurs)
    return lambda: next(suite)


class TestChrono(unittest.TestCase):
    def test_action_lente_journalisee_avec_le_detail(self):
        chrono = perf.Chrono("Parfum › Stock", horloge(0.0, 0.8, 1.0, 1.0))
        chrono.etape("construction")                  # 800 ms
        chrono.etape("données")                       # 200 ms
        with self.assertLogs("perf", level="WARNING") as sortie:
            total = chrono.fin()
        self.assertAlmostEqual(total, 1.0)
        self.assertIn("LENT", sortie.output[0])
        self.assertIn("Parfum › Stock", sortie.output[0])
        self.assertIn("construction 800 ms", sortie.output[0])

    def test_action_rapide_non_journalisee(self):
        chrono = perf.Chrono("Accueil", horloge(0.0, 0.05, 0.05))
        chrono.etape("affichage")
        with self.assertNoLogs("perf", level="INFO"):
            chrono.fin()


if __name__ == "__main__":
    unittest.main()
