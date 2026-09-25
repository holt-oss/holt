"""BYOK keys at rest: AES-256-GCM, key from `HOLT_SECRET_KEY`.

`HOLT_SECRET_KEY` is ideally 32 random bytes, base64-encoded
(`python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`).
Any other string is accepted and stretched with SHA-256, so a passphrase works,
but a random key is better. The user id is bound in as associated data, so a
ciphertext copied onto another user's row does not decrypt.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"


class SecretKeyMissing(RuntimeError):
    pass


def _key(secret: str) -> bytes:
    if not secret:
        raise SecretKeyMissing("HOLT_SECRET_KEY is not set")
    try:
        raw = base64.b64decode(secret, validate=True)
        if len(raw) == 32:
            return raw
    except (binascii.Error, ValueError):
        pass
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(secret: str, plaintext: str, user_id: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key(secret)).encrypt(nonce, plaintext.encode("utf-8"),
                                          user_id.encode("utf-8"))
    return base64.b64encode(VERSION + nonce + sealed).decode("ascii")


def decrypt(secret: str, token: str, user_id: str) -> str:
    blob = base64.b64decode(token)
    if blob[:1] != VERSION:
        raise ValueError("unknown ciphertext version")
    nonce, sealed = blob[1:13], blob[13:]
    return AESGCM(_key(secret)).decrypt(nonce, sealed, user_id.encode("utf-8")).decode("utf-8")
