"""Hachage du mot de passe (PBKDF2-SHA256 avec sel aléatoire)."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional, Tuple

ITERATIONS = 200_000


def hacher(mot_de_passe: str, sel_hex: Optional[str] = None) -> Tuple[str, str]:
    """Retourne (hash_hex, sel_hex). Un nouveau sel est créé si absent."""
    sel = bytes.fromhex(sel_hex) if sel_hex else os.urandom(16)
    empreinte = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel, ITERATIONS)
    return empreinte.hex(), sel.hex()


def verifier(mot_de_passe: str, hash_hex: str, sel_hex: str) -> bool:
    """Compare en temps constant."""
    if not hash_hex or not sel_hex:
        return False
    calcule, _ = hacher(mot_de_passe, sel_hex)
    return hmac.compare_digest(calcule, hash_hex)
