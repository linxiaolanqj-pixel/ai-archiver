#!/usr/bin/env python3
"""给 App 图标套上 macOS squircle（超椭圆）圆角。

Apple 官方建议源图方角铺满、由系统在 Dock/Finder 自动裁圆；
但源 PNG 在深色背景（Cursor 预览、引导页）里会显得「方角尖」。
本脚本把可见区域裁成与 macOS App 图标一致的 squircle。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# 超椭圆指数：越小四角越圆（2≈椭圆，5+ 趋近方角）；3.75 比系统默认更圆一点
_EXPONENT = 3.75


def squircle_mask(size: int, *, exponent: float = _EXPONENT) -> Image.Image:
    """生成 size×size 的 squircle 灰度蒙版（先算小图再放大，够快也够平滑）。"""
    small = 256
    small_mask = Image.new("L", (small, small), 0)
    sp = small_mask.load()
    sa = sb = small / 2.0
    scx = scy = (small - 1) / 2.0
    for y in range(small):
        ny = (y - scy) / sb
        ay = abs(ny) ** exponent
        for x in range(small):
            nx = (x - scx) / sa
            if ay + abs(nx) ** exponent <= 1.0:
                sp[x, y] = 255
    return small_mask.resize((size, size), Image.LANCZOS)


def export_png(src: Path, size: int, dst: Path, *, inset: float = 0.0) -> None:
    """导出指定边长 PNG，在目标尺寸重新套 squircle（小图圆角才明显）。"""
    im = Image.open(src).convert("RGBA")
    if im.size != (1024, 1024):
        im = im.resize((1024, 1024), Image.LANCZOS)

    if inset > 0:
        inner = int(1024 * (1 - inset * 2))
        inner = max(880, inner)
        scaled = im.resize((inner, inner), Image.LANCZOS)
        canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        ox = (1024 - inner) // 2
        canvas.paste(scaled, (ox, ox))
        im = canvas

    frame = im.resize((size, size), Image.LANCZOS)
    mask = squircle_mask(size)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(frame, (0, 0), mask)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "PNG", optimize=True)


def apply_squircle(src: Path, dst: Path | None = None, *, inset: float = 0.0) -> Path:
    """inset：内容略缩小，圆角轮廓更明显（类似 Typeless 白底圆角标）。"""
    im = Image.open(src).convert("RGBA")
    if im.size != (1024, 1024):
        im = im.resize((1024, 1024), Image.LANCZOS)

    if inset > 0:
        inner = int(1024 * (1 - inset * 2))
        inner = max(880, inner)
        scaled = im.resize((inner, inner), Image.LANCZOS)
        canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        ox = (1024 - inner) // 2
        canvas.paste(scaled, (ox, ox))
        im = canvas

    mask = squircle_mask(1024)
    out_im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    out_im.paste(im, (0, 0), mask)

    target = dst or src
    out_im.save(target, "PNG", optimize=True)
    return target


def export_all_sizes(src: Path, assets_dir: Path) -> None:
    """生成 iconset 临时文件 + UI 用 icon-128/256（源图已 squircle 时不再内缩）。"""
    sizes = (16, 32, 64, 128, 256, 512, 1024)
    for sz in sizes:
        export_png(src, sz, assets_dir / f"_tmp_{sz}.png", inset=0)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("用法:", file=sys.stderr)
        print("  icon_squircle.py <icon.png> [out.png]", file=sys.stderr)
        print("  icon_squircle.py --all <icon.png> <assets_dir>", file=sys.stderr)
        return 2
    if args[0] == "--all":
        if len(args) < 3:
            print("用法: icon_squircle.py --all <icon.png> <assets_dir>", file=sys.stderr)
            return 2
        src, assets = Path(args[1]), Path(args[2])
        if not src.is_file():
            print(f"找不到: {src}", file=sys.stderr)
            return 1
        export_all_sizes(src, assets)
        print(f"✓ 已导出各尺寸 squircle → {assets}")
        return 0
    src = Path(args[0])
    dst = Path(args[1]) if len(args) > 1 else src
    if not src.is_file():
        print(f"找不到: {src}", file=sys.stderr)
        return 1
    apply_squircle(src, dst)
    print(f"✓ squircle → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
