import os
from PIL import Image

ROOT = "/Users/hamaratbey/Desktop/Projeler/sesver/assets/app_icon"
slugs = ["concept1_soundwave", "concept2_microphone", "concept3_speech_wave", "concept4_letter_s"]

# Her konsept icin acik + koyu zemin mockup (yan yana) uret -> okunabilirlik kaniti
cell = 300
pad = 40
sheet = Image.new("RGB", (cell * 2 + pad * 3, cell * len(slugs) + pad * (len(slugs) + 1)), (235, 235, 235))

for row, slug in enumerate(slugs):
    icon = Image.open(os.path.join(ROOT, slug, "icon_1024.png")).convert("RGBA")
    icon_small = icon.resize((cell - 40, cell - 40), Image.LANCZOS)
    y = pad + row * (cell + pad)

    light_bg = Image.new("RGBA", (cell, cell), (248, 248, 250, 255))
    light_bg.alpha_composite(icon_small, (20, 20))
    sheet.paste(light_bg.convert("RGB"), (pad, y))

    dark_bg = Image.new("RGBA", (cell, cell), (18, 18, 22, 255))
    dark_bg.alpha_composite(icon_small, (20, 20))
    sheet.paste(dark_bg.convert("RGB"), (pad * 2 + cell, y))

out_path = os.path.join(ROOT, "karsilastirma_acik_koyu_zemin.png")
sheet.save(out_path)
print("saved", out_path, sheet.size)
