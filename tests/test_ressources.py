"""Le logo et les icônes sont présents et utilisables."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.ressources import chemin_ressource  # noqa: E402


class TestRessources(unittest.TestCase):
    def test_fichiers_presents(self):
        for nom in ("logo.png", "icone.png", "icone.ico"):
            self.assertTrue(chemin_ressource(f"assets/{nom}").is_file(), nom)

    def test_logo_a_un_fond_transparent(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow non installé")
        logo = Image.open(chemin_ressource("assets/logo.png")).convert("RGBA")
        self.assertEqual(logo.getpixel((2, 2))[3], 0)               # coin transparent
        self.assertGreater(logo.getchannel("A").getextrema()[1], 200)  # traits bien opaques


if __name__ == "__main__":
    unittest.main()
