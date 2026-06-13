#!/usr/bin/env python3
"""把 secrets/platform.env 里的 Key 加密成 platform.key.enc（供 PyInstaller 打进包）。"""

from __future__ import annotations

import sys
from pathlib import Path

from platform_crypto import write_encrypted_key
from settings_util import _read_key_from_env_file


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("secrets/platform.env")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("platform.key.enc")
    if not src.exists():
        print(f"[pack] ✗ 找不到 {src}", file=sys.stderr)
        return 1
    key = _read_key_from_env_file(src)
    if not key.startswith("sk-") or len(key) < 20:
        print(f"[pack] ✗ {src} 里没有有效的 DEEPSEEK_API_KEY", file=sys.stderr)
        return 1
    write_encrypted_key(key, out)
    print(f"[pack] ✓ 已写入 {out}（密文，非明文 sk-）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
