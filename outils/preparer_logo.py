"""Prépare les images du logo pour l'application.

Usage :  python outils/preparer_logo.py chemin/vers/logo.jpg

Crée dans assets/ :
  logo.png      logo sans fond (transparent), sans les traits latéraux -> menu et connexion
  icone.png     icône 256 px (emblème sur fond clair)                 -> fenêtre (Mac/Linux)
  icone.ico     icône Windows multi-tailles                           -> fenêtre, .exe, installateur
  icone.icns    icône macOS (si supporté par Pillow)

Les zones de découpe sont exprimées en fractions de l'image (valables pour le logo Nevada
carré ; ajustez ZONE_LOGO / ZONE_EMBLEME pour un autre logo).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ZONE_LOGO = (0.15, 0.16, 0.86, 0.865)       # emblème + nom, sans les traits des côtés
ZONE_EMBLEME = (0.29, 0.17, 0.71, 0.585)    # le flacon dans son cadre de feuillage
LARGEUR_LOGO = 700


def _fraction(image: Image.Image, zone) -> Image.Image:
    l, h = image.size
    return image.crop((int(zone[0] * l), int(zone[1] * h), int(zone[2] * l), int(zone[3] * h)))


def _couleurs(image: Image.Image):
    """Couleur du fond (coins) et de l'encre (pixels les plus foncés)."""
    l, h = image.size
    coins = [image.getpixel(p) for p in ((3, 3), (l - 4, 3), (3, h - 4), (l - 4, h - 4))]
    fond = tuple(sum(c[i] for c in coins) // 4 for i in range(3))
    gris = image.convert("L").tobytes()
    rvb = image.tobytes()
    seuil = sorted(gris)[len(gris) // 50]                               # 2 % des pixels les plus foncés
    indices = [i for i, g in enumerate(gris) if g <= seuil]
    encre = tuple(sum(rvb[3 * i + c] for i in indices) // len(indices) for c in range(3))
    return fond, encre


def _rendre_transparent(image: Image.Image, fond, encre) -> Image.Image:
    """Le fond devient transparent ; le trait garde la couleur d'encre (bords lissés)."""
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]          # noqa: E731
    l_fond, l_encre = lum(fond), lum(encre)
    plage = max(l_fond - l_encre, 1)
    alpha = image.convert("L").point(lambda v: max(0, min(255, int((l_fond - v) / plage * 255))))
    resultat = Image.new("RGBA", image.size, encre + (0,))
    resultat.putalpha(alpha)
    return resultat


def _recadrer(image: Image.Image, marge: int = 4) -> Image.Image:
    boite = image.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    if boite:
        image = image.crop((max(boite[0] - marge, 0), max(boite[1] - marge, 0),
                            min(boite[2] + marge, image.width), min(boite[3] + marge, image.height)))
    return image


def main(source: str, dossier: str = "assets") -> None:
    sortie = Path(dossier)
    sortie.mkdir(parents=True, exist_ok=True)
    original = Image.open(source).convert("RGB")
    fond, encre = _couleurs(original)

    # --- logo transparent (menu, connexion)
    logo = _recadrer(_rendre_transparent(_fraction(original, ZONE_LOGO), fond, encre))
    logo = logo.resize((LARGEUR_LOGO, round(logo.height * LARGEUR_LOGO / logo.width)), Image.LANCZOS)
    logo.save(sortie / "logo.png")

    # --- icône : emblème sur fond clair, coins arrondis
    emb = _recadrer(_rendre_transparent(_fraction(original, ZONE_EMBLEME), fond, encre))
    taille = 1024
    toile = Image.new("RGBA", (taille, taille), (0, 0, 0, 0))
    masque = Image.new("L", (taille, taille), 0)
    ImageDraw.Draw(masque).rounded_rectangle((0, 0, taille - 1, taille - 1), radius=taille // 5, fill=255)
    toile.paste(Image.new("RGBA", (taille, taille), fond + (255,)), (0, 0), masque)
    cote = int(taille * 0.80)
    echelle = cote / max(emb.size)                                       # agrandit l'emblème pour remplir l'icône
    emb = emb.resize((round(emb.width * echelle), round(emb.height * echelle)), Image.LANCZOS)
    toile.alpha_composite(emb, ((taille - emb.width) // 2, (taille - emb.height) // 2))
    toile.resize((256, 256), Image.LANCZOS).save(sortie / "icone.png")
    toile.save(sortie / "icone.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    try:
        toile.save(sortie / "icone.icns")
    except Exception:  # noqa: BLE001 - facultatif (macOS)
        pass
    print(f"Images créées dans {sortie.resolve()}  (fond {fond}, encre {encre})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "assets")
