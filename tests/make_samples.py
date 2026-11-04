"""生成合成样图，供测试夹具与人工验证 Ranking/Grid 使用。

用法：

    python tests/make_samples.py --out tests/samples --count 24 --flawed 6

样图特征：
- 尺寸在 512 / 768 / 1024 之间轮换，内容在渐变 / 几何形状 / 网格 / 噪声之间轮换。
- 一半文件放到 ``<out>/batch/`` 子目录，模拟 ComfyUI 按日期/批次输出的结构。
- ``--flawed N`` 额外生成 N 张明显有瑕疵的图（严重模糊 / 过曝 / 色偏 / 大片黑边 / 噪点），
  文件名以 ``flawed_`` 开头，供 Leo 人工验证 Ranking 快捷键手感。

本模块不依赖 pytest，测试里可直接 ``from tests import make_samples`` 调用函数。
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

#: 轮换的图片尺寸（正方形，便于目测 Ranking 对齐）
SIZES = (512, 768, 1024)

#: 正常图内容类型
KINDS = ("gradient", "shapes", "grid", "noise")

#: 瑕疵类型
FLAW_KINDS = ("blur", "overexposed", "colorcast", "blackbars", "noisy")

#: Pillow 格式映射
_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".gif": "GIF",
    ".bmp": "BMP",
}


def _gradient(size: int, seed: int) -> Image.Image:
    """线性双色渐变（用 ImageDraw 画横线，避免逐像素循环）。"""
    rnd = random.Random(seed)
    c0 = tuple(rnd.randrange(256) for _ in range(3))
    c1 = tuple(rnd.randrange(256) for _ in range(3))
    img = Image.new("RGB", (size, size), c0)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
        draw.line([(0, y), (size - 1, y)], fill=color)
    return img


def _shapes(size: int, seed: int) -> Image.Image:
    """随机几何形状（圆 / 矩形 / 三角形）。"""
    rnd = random.Random(seed)
    img = Image.new("RGB", (size, size), (18, 20, 26))
    draw = ImageDraw.Draw(img)
    for _ in range(9):
        x0 = rnd.randrange(size)
        y0 = rnd.randrange(size)
        x1 = min(size - 1, x0 + rnd.randrange(size // 3, size))
        y1 = min(size - 1, y0 + rnd.randrange(size // 3, size))
        color = tuple(rnd.randrange(60, 256) for _ in range(3))
        kind = rnd.randrange(3)
        if kind == 0:
            draw.ellipse([x0, y0, x1, y1], fill=color)
        elif kind == 1:
            draw.rectangle([x0, y0, x1, y1], fill=color)
        else:
            draw.polygon([(x0, y1), ((x0 + x1) // 2, y0), (x1, y1)], fill=color)
    return img


def _grid(size: int, seed: int) -> Image.Image:
    """等距网格 + 交叉点标记，方便目测缩放比例。"""
    rnd = random.Random(seed)
    bg = tuple(rnd.randrange(10, 60) for _ in range(3))
    fg = tuple(rnd.randrange(140, 256) for _ in range(3))
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)
    step = max(8, size // rnd.choice((8, 12, 16)))
    for pos in range(0, size, step):
        draw.line([(pos, 0), (pos, size - 1)], fill=fg, width=2)
        draw.line([(0, pos), (size - 1, pos)], fill=fg, width=2)
    return img


def _noise(size: int, seed: int) -> Image.Image:
    """彩色噪点（Pillow 的 C 实现 effect_noise 生成灰度再上色）。"""
    rnd = random.Random(seed)
    noise = Image.effect_noise((size, size), rnd.randrange(40, 110)).convert("RGB")
    tint = Image.new("RGB", (size, size), tuple(rnd.randrange(80, 256) for _ in range(3)))
    return Image.blend(noise, tint, 0.55)


_RENDERERS = {
    "gradient": _gradient,
    "shapes": _shapes,
    "grid": _grid,
    "noise": _noise,
}


def make_image(path, size: int = 512, kind: str | None = None, seed: int = 0) -> Path:
    """按后缀格式生成一张普通样图，返回路径。"""
    path = Path(path)
    kind = kind or KINDS[seed % len(KINDS)]
    render = _RENDERERS[kind]
    img = render(size, seed)
    path.parent.mkdir(parents=True, exist_ok=True)

    fmt = _FORMATS[path.suffix.lower()]
    save_kwargs: dict = {}
    if fmt == "JPEG":
        img = img.convert("RGB")
        save_kwargs["quality"] = 92
    elif fmt == "WEBP":
        save_kwargs["quality"] = 92
    elif fmt == "GIF":
        img = img.convert("P", palette=Image.Palette.ADAPTIVE)
    img.save(path, fmt, **save_kwargs)
    return path


def make_flawed(path, size: int = 768, kind: str = "blur", seed: int = 0) -> Path:
    """生成一张**明显有瑕疵**的图，用于人工验证 Ranking 手感。"""
    path = Path(path)
    base_kind = KINDS[seed % len(KINDS)]
    img = _RENDERERS[base_kind](size, seed)

    if kind == "blur":  # 严重模糊
        img = img.filter(ImageFilter.GaussianBlur(radius=size / 24))
    elif kind == "overexposed":  # 过曝
        img = ImageEnhance.Brightness(img).enhance(2.8)
        img = ImageEnhance.Contrast(img).enhance(0.6)
    elif kind == "colorcast":  # 严重色偏（偏品红）
        r, g, b = img.split()
        boost = [min(255, v * 2) for v in range(256)]
        cut = [v // 3 for v in range(256)]
        img = Image.merge("RGB", (r.point(boost), g.point(cut), b.point(boost)))
    elif kind == "blackbars":  # 上下各 40% 黑边
        img = img.copy()
        draw = ImageDraw.Draw(img)
        bar = int(size * 0.4)
        draw.rectangle([0, 0, size, bar], fill=(0, 0, 0))
        draw.rectangle([0, size - bar, size, size], fill=(0, 0, 0))
    elif kind == "noisy":  # 噪点糊满
        noise = Image.effect_noise((size, size), 220).convert("RGB")
        img = Image.blend(img, noise, 0.7)
    else:
        raise ValueError(f"未知瑕疵类型: {kind}")

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


def generate(out_dir, count: int = 24, flawed: int = 0, seed: int = 1) -> list[Path]:
    """生成一批样图：``count`` 张正常图（一半在 batch/ 子目录）+ ``flawed`` 张瑕疵图。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for i in range(count):
        size = SIZES[i % len(SIZES)]
        kind = KINDS[i % len(KINDS)]
        in_batch = i % 2 == 1
        sub = out / "batch" if in_batch else out
        # ComfyUI 风格的递增文件名，保证互不重名
        stem = f"ComfyUI_{10001 + i:05d}_" if in_batch else f"ComfyUI_{i + 1:05d}_"
        paths.append(make_image(sub / f"{stem}.png", size=size, kind=kind, seed=seed + i))

    for j in range(flawed):
        size = SIZES[j % len(SIZES)]
        kind = FLAW_KINDS[j % len(FLAW_KINDS)]
        paths.append(
            make_flawed(out / f"flawed_{j + 1:02d}_{kind}.png", size=size, kind=kind, seed=seed + 100 + j)
        )

    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 ImageRating 合成样图")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--count", type=int, default=24, help="正常图片数量（默认 24）")
    parser.add_argument("--flawed", type=int, default=0, help="瑕疵图片数量（默认 0）")
    parser.add_argument("--seed", type=int, default=1, help="随机种子")
    args = parser.parse_args(argv)

    paths = generate(args.out, count=args.count, flawed=args.flawed, seed=args.seed)
    print(f"生成 {len(paths)} 张样图 -> {Path(args.out).resolve()}")
    for p in paths:
        print(f"  {p.relative_to(Path(args.out))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
