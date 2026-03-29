"""Generate a circular favicon PNG from team-logo.png using Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent.parent
SRC = ROOT / "client" / "public" / "team-logo.png"
DST = ROOT / "client" / "public" / "team-logo-round.png"

img = Image.open(SRC).convert("RGBA")
size = min(img.size)
img = img.crop(((img.width - size) // 2, (img.height - size) // 2,
                (img.width + size) // 2, (img.height + size) // 2))
img = img.resize((256, 256), Image.LANCZOS)

mask = Image.new("L", (256, 256), 0)
ImageDraw.Draw(mask).ellipse((0, 0, 255, 255), fill=255)

result = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
result.paste(img, mask=mask)
result.save(DST, "PNG")
print(f"Saved round favicon: {DST}")
