"""打包内置 API Key 的轻量加解密。

目的：避免 .app 里出现明文 sk-…（strings / grep 一扫就露）。
说明：客户端可逆加密无法防专业逆向，真正藏 Key 需自建 API 代理。
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

_P1, _P2, _P3, _P4, _P5 = "Skill", "less", "·plat", "form·", "v1"
_BUNDLE = "com.skillless.app"


def _derive_key() -> bytes:
    material = f"{_P1}{_P2}{_P3}{_P4}{_P5}|{_BUNDLE}"
    return hashlib.sha256(material.encode("utf-8")).digest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encrypt_platform_key(plain: str) -> str:
    plain = (plain or "").strip()
    if not plain:
        return ""
    return base64.urlsafe_b64encode(_xor_bytes(plain.encode("utf-8"), _derive_key())).decode("ascii")


def decrypt_platform_key(blob: str) -> str:
    blob = (blob or "").strip()
    if not blob:
        return ""
    try:
        ct = base64.urlsafe_b64decode(blob.encode("ascii"))
        return _xor_bytes(ct, _derive_key()).decode("utf-8")
    except Exception:
        return ""


def write_encrypted_key(plain: str, out_path: Path) -> None:
    out_path.write_text(encrypt_platform_key(plain) + "\n", encoding="utf-8")


def read_encrypted_key(path: Path) -> str:
    if not path.exists():
        return ""
    return decrypt_platform_key(path.read_text(encoding="utf-8").strip())
