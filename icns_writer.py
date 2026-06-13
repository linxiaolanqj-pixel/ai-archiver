#!/usr/bin/env python3
"""把 PNG 写成 macOS .icns（不依赖 iconutil）。"""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image

# Apple ICNS：PNG 嵌入类型
_SIZES = (
    (16, b"icp4"),
    (32, b"icp5"),
    (64, b"icp6"),
    (128, b"ic07"),
    (256, b"ic08"),
    (512, b"ic09"),
    (1024, b"ic10"),
)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_icns(src: Path, dst: Path) -> None:
    """写入 .icns；保留 PNG 透明通道，深色 UI（如 Cursor 侧栏）才能显出圆角。"""
    from icon_squircle import squircle_mask

    im = Image.open(src).convert("RGBA")
    if im.size != (1024, 1024):
        im = im.resize((1024, 1024), Image.LANCZOS)

    chunks: list[tuple[bytes, bytes]] = []
    for size, typ in _SIZES:
        frame = im.resize((size, size), Image.LANCZOS)
        mask = squircle_mask(size)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(frame, (0, 0), mask)
        data = _png_bytes(out)
        chunks.append((typ, data))

    body = b""
    for typ, data in chunks:
        length = 8 + len(data)
        body += typ + struct.pack(">I", length) + data

    header = b"icns" + struct.pack(">I", 8 + len(body))
    dst.write_bytes(header + body)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("用法: icns_writer.py <icon.png> <out.icns>", file=sys.stderr)
        return 2
    src, dst = Path(args[0]), Path(args[1])
    if not src.is_file():
        print(f"找不到源图: {src}", file=sys.stderr)
        return 1
    write_icns(src, dst)
    print(f"✓ {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
