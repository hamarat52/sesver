#!/usr/bin/env python3
"""
SesVer uygulama ikonu - 4 tasarim konsepti ureteci.

NOT (seffaflik): Bu gorseller bir AI goruntu modeliyle degil, bu script
icindeki Pillow/numpy vektor-benzeri cizim komutlariyle programatik olarak
uretilmistir (gradyan + geometrik sekil + anti-aliasing icin supersample).
Model uretimi gibi sunulmaz.

Her konsept icin:
  - icon_1024.png  : 1024x1024 RGBA, supersample edilip LANCZOS ile kucultulmus
  - icon.svg        : elle yazilmis esdeger vektor kaynagi (SVG)

Kullanim:
  python3 generate_icons.py
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SS = 2048          # supersample calisma boyu (sonra 1024'e indirilir)
FINAL = 1024
OUT_ROOT = os.path.dirname(os.path.abspath(__file__))

FONT_ROUNDED = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def make_gradient_rgba(size, c1, c2, angle_deg=45):
    """Vektorlestirilmis (numpy) diyagonal linear gradient -> RGBA Image."""
    c1 = np.array(hex2rgb(c1), dtype=np.float32)
    c2 = np.array(hex2rgb(c2), dtype=np.float32)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    angle = math.radians(angle_deg)
    dx, dy = math.cos(angle), math.sin(angle)
    proj = xs * dx + ys * dy
    proj -= proj.min()
    proj /= proj.max()
    proj = proj[..., None]
    rgb = c1[None, None, :] * (1 - proj) + c2[None, None, :] * proj
    rgb = rgb.astype(np.uint8)
    alpha = np.full((size, size, 1), 255, dtype=np.uint8)
    arr = np.concatenate([rgb, alpha], axis=2)
    return Image.fromarray(arr, mode="RGBA")


def rounded_rect_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def apple_tile(size, c1, c2, angle=45, radius_ratio=0.2237):
    """Big Sur tarzi yuvarlatilmis kare 'app tile' arka plani."""
    grad = make_gradient_rgba(size, c1, c2, angle)
    mask = rounded_rect_mask(size, int(size * radius_ratio))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)
    return tile


def soft_shadow_text(draw_img, text, font, fill, center, shadow_alpha=40):
    pass  # basit tutuldu, gerek yok


# ---------------------------------------------------------------------------
# Konsept 1: Ses Dalgasi (equalizer / waveform) soyutlamasi
# ---------------------------------------------------------------------------
def concept_soundwave():
    size = SS
    tile = apple_tile(size, "#6D28D9", "#06B6D4", angle=40)
    draw = ImageDraw.Draw(tile)

    n_bars = 7
    bar_w = size * 0.062
    gap = size * 0.045
    total_w = n_bars * bar_w + (n_bars - 1) * gap
    start_x = (size - total_w) / 2
    cy = size / 2
    # ortadan disa dogru azalan yukseklikler (simetrik equalizer)
    heights_ratio = [0.30, 0.52, 0.74, 0.92, 0.74, 0.52, 0.30]
    color = (255, 255, 255, 255)
    for i, hr in enumerate(heights_ratio):
        x0 = start_x + i * (bar_w + gap)
        x1 = x0 + bar_w
        h = size * 0.62 * hr
        y0 = cy - h / 2
        y1 = cy + h / 2
        radius = bar_w / 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=color)

    return tile.resize((FINAL, FINAL), Image.LANCZOS)


def svg_soundwave():
    bars = [0.30, 0.52, 0.74, 0.92, 0.74, 0.52, 0.30]
    n = len(bars)
    bar_w = 1024 * 0.062
    gap = 1024 * 0.045
    total_w = n * bar_w + (n - 1) * gap
    start_x = (1024 - total_w) / 2
    cy = 512
    rects = []
    for i, hr in enumerate(bars):
        x0 = start_x + i * (bar_w + gap)
        h = 1024 * 0.62 * hr
        y0 = cy - h / 2
        rects.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'rx="{bar_w/2:.1f}" fill="#FFFFFF"/>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6D28D9"/>
      <stop offset="100%" stop-color="#06B6D4"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="1024" height="1024" rx="229" fill="url(#g)"/>
  {''.join(rects)}
</svg>
"""


# ---------------------------------------------------------------------------
# Konsept 2: Stilize Mikrofon
# ---------------------------------------------------------------------------
def concept_microphone():
    size = SS
    tile = apple_tile(size, "#0D9488", "#2563EB", angle=50)
    draw = ImageDraw.Draw(tile)
    white = (255, 255, 255, 255)

    cx = size / 2
    cap_w = size * 0.26
    cap_h = size * 0.40
    cap_top = size * 0.20
    cap_bottom = cap_top + cap_h
    draw.rounded_rectangle(
        [cx - cap_w / 2, cap_top, cx + cap_w / 2, cap_bottom],
        radius=cap_w / 2,
        fill=white,
    )
    # mikrofon govdesindeki ince yatay izgara cizgileri (grille)
    grille_color = (13, 148, 136, 255)
    for i in range(1, 5):
        gy = cap_top + cap_h * (i / 5.0)
        draw.line(
            [cx - cap_w / 2 + size * 0.02, gy, cx + cap_w / 2 - size * 0.02, gy],
            fill=grille_color,
            width=max(2, int(size * 0.006)),
        )

    # kafes/tutucu yay (basket arc) - mikrofonu saran U seklinde kavis
    arc_r = cap_w * 0.95
    arc_box = [cx - arc_r, cap_top + cap_h * 0.15, cx + arc_r, cap_top + cap_h * 0.15 + arc_r * 1.9]
    stroke = max(6, int(size * 0.022))
    draw.arc(arc_box, start=20, end=160, fill=white, width=stroke)

    # sap (stand)
    stand_top = cap_top + cap_h * 0.15 + arc_r * 1.9 * 0.55
    stand_bottom = size * 0.82
    draw.line([cx, stand_top, cx, stand_bottom], fill=white, width=stroke)
    base_w = size * 0.20
    draw.rounded_rectangle(
        [cx - base_w / 2, stand_bottom - stroke / 2, cx + base_w / 2, stand_bottom + stroke],
        radius=stroke,
        fill=white,
    )

    # yaninda kucuk ses dalgasi yarim daireler (sag ust)
    for i, r in enumerate([size * 0.10, size * 0.16, size * 0.22]):
        bbox = [cx + cap_w * 0.55 - r, cap_top - r * 0.2, cx + cap_w * 0.55 + r, cap_top - r * 0.2 + 2 * r]
        draw.arc(bbox, start=300, end=60, fill=white, width=max(5, int(size * 0.014)))

    return tile.resize((FINAL, FINAL), Image.LANCZOS)


def svg_microphone():
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0D9488"/>
      <stop offset="100%" stop-color="#2563EB"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="1024" height="1024" rx="229" fill="url(#g)"/>
  <rect x="379" y="205" width="266" height="410" rx="133" fill="#FFFFFF"/>
  <g stroke="#0D9488" stroke-width="12">
    <line x1="399" y1="287" x2="625" y2="287"/>
    <line x1="399" y1="369" x2="625" y2="369"/>
    <line x1="399" y1="451" x2="625" y2="451"/>
    <line x1="399" y1="533" x2="625" y2="533"/>
  </g>
  <path d="M 262 471 A 250 250 0 0 0 762 471" fill="none" stroke="#FFFFFF" stroke-width="45" stroke-linecap="round"/>
  <line x1="512" y1="700" x2="512" y2="840" stroke="#FFFFFF" stroke-width="45" stroke-linecap="round"/>
  <rect x="410" y="830" width="204" height="40" rx="20" fill="#FFFFFF"/>
</svg>
"""


# ---------------------------------------------------------------------------
# Konsept 3: Konusma Balonu + Dalga
# ---------------------------------------------------------------------------
def concept_speech_wave():
    size = SS
    tile = apple_tile(size, "#F97316", "#EC4899", angle=35)
    draw = ImageDraw.Draw(tile)
    white = (255, 255, 255, 255)

    bubble_w = size * 0.70
    bubble_h = size * 0.52
    bx0 = (size - bubble_w) / 2
    by0 = size * 0.20
    bx1 = bx0 + bubble_w
    by1 = by0 + bubble_h
    radius = bubble_h * 0.5
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=radius, fill=white)

    # kuyruk (tail) - sol alt
    tail_cx = bx0 + bubble_w * 0.22
    tail = [
        (tail_cx, by1 - size * 0.01),
        (tail_cx - size * 0.10, by1 + size * 0.13),
        (tail_cx + size * 0.11, by1 - size * 0.04),
    ]
    draw.polygon(tail, fill=white)

    # balonun icinde renkli dalga cubuklari
    n_bars = 5
    bar_w = bubble_w * 0.07
    gap = bubble_w * 0.045
    total_w = n_bars * bar_w + (n_bars - 1) * gap
    sx = (size - total_w) / 2
    cy = by0 + bubble_h / 2
    heights_ratio = [0.35, 0.65, 1.0, 0.65, 0.35]
    wave_color = (236, 72, 153, 255)
    for i, hr in enumerate(heights_ratio):
        x0 = sx + i * (bar_w + gap)
        x1 = x0 + bar_w
        h = bubble_h * 0.55 * hr
        y0 = cy - h / 2
        y1 = cy + h / 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=bar_w / 2, fill=wave_color)

    return tile.resize((FINAL, FINAL), Image.LANCZOS)


def svg_speech_wave():
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#F97316"/>
      <stop offset="100%" stop-color="#EC4899"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="1024" height="1024" rx="229" fill="url(#g)"/>
  <rect x="154" y="205" width="717" height="532" rx="266" fill="#FFFFFF"/>
  <path d="M 380 727 L 329 860 L 420 790 Z" fill="#FFFFFF"/>
  <g fill="#EC4899">
    <rect x="408" y="392" width="50" height="96" rx="25"/>
    <rect x="479" y="330" width="50" height="220" rx="25"/>
    <rect x="550" y="300" width="50" height="280" rx="25"/>
    <rect x="621" y="330" width="50" height="220" rx="25"/>
    <rect x="692" y="392" width="50" height="96" rx="25"/>
  </g>
</svg>
"""


# ---------------------------------------------------------------------------
# Konsept 4: Minimalist "S" harfi (ses dalgasi ile kesisen)
# ---------------------------------------------------------------------------
def concept_letter_s():
    size = SS
    tile = apple_tile(size, "#4338CA", "#A855F7", angle=45)
    draw = ImageDraw.Draw(tile)
    white = (255, 255, 255, 255)

    font_size = int(size * 0.74)
    font = ImageFont.truetype(FONT_ROUNDED, font_size)
    text = "S"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=white)

    # S'in ortasindan gecen kucuk ses dalgasi (equalizer) aksani - alt kisimda
    n_bars = 5
    bar_w = size * 0.028
    gap = size * 0.022
    total_w = n_bars * bar_w + (n_bars - 1) * gap
    sx = (size - total_w) / 2
    base_y = size * 0.845
    heights = [0.025, 0.05, 0.075, 0.05, 0.025]
    accent = (255, 255, 255, 230)
    for i, hr in enumerate(heights):
        x0 = sx + i * (bar_w + gap)
        x1 = x0 + bar_w
        h = size * hr
        y0 = base_y - h
        y1 = base_y + h
        draw.rounded_rectangle([x0, y0, x1, y1], radius=bar_w / 2, fill=accent)

    return tile.resize((FINAL, FINAL), Image.LANCZOS)


def svg_letter_s():
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4338CA"/>
      <stop offset="100%" stop-color="#A855F7"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="1024" height="1024" rx="229" fill="url(#g)"/>
  <text x="512" y="650" font-family="Arial Rounded MT Bold, Arial, sans-serif"
        font-size="760" font-weight="bold" fill="#FFFFFF" text-anchor="middle">S</text>
  <g fill="#FFFFFF" fill-opacity="0.9">
    <rect x="399" y="845" width="28" height="50" rx="14"/>
    <rect x="455" y="820" width="28" height="100" rx="14"/>
    <rect x="511" y="795" width="28" height="150" rx="14"/>
    <rect x="567" y="820" width="28" height="100" rx="14"/>
    <rect x="623" y="845" width="28" height="50" rx="14"/>
  </g>
</svg>
"""


CONCEPTS = [
    ("concept1_soundwave", "Ses Dalgasi (Equalizer)", concept_soundwave, svg_soundwave),
    ("concept2_microphone", "Stilize Mikrofon", concept_microphone, svg_microphone),
    ("concept3_speech_wave", "Konusma Balonu + Dalga", concept_speech_wave, svg_speech_wave),
    ("concept4_letter_s", "Minimalist S Harfi", concept_letter_s, svg_letter_s),
]


def main():
    for slug, label, png_fn, svg_fn in CONCEPTS:
        out_dir = os.path.join(OUT_ROOT, slug)
        os.makedirs(out_dir, exist_ok=True)
        img = png_fn()
        png_path = os.path.join(out_dir, "icon_1024.png")
        img.save(png_path, "PNG")
        svg_path = os.path.join(out_dir, "icon.svg")
        with open(svg_path, "w") as f:
            f.write(svg_fn())
        print(f"[OK] {label} -> {png_path} ({img.size[0]}x{img.size[1]}, mode={img.mode})")
        print(f"[OK] {label} -> {svg_path}")


if __name__ == "__main__":
    main()
