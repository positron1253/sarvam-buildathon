"""Generate the sample medicine-strip images in ./samples (no network, needs Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "samples"


def font(name, size):
    for f in (name, "DejaVuSans-Bold.ttf" if "bd" in name else "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make(path, lines):
    im = Image.new("RGB", (900, 520), (235, 235, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 880, 500], outline=(40, 40, 160), width=6)
    d.text((50, 40), lines[0], font=font("arialbd.ttf", 54), fill=(20, 20, 120))
    for i, line in enumerate(lines[1:]):
        d.text((50, 130 + i * 62), line, font=font("arial.ttf", 34), fill=(30, 30, 30))
    im.save(path, quality=92)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make(OUT / "expired_paracetamol.jpg", ["Crocin Advance", "Paracetamol Tablets IP 500 mg", "Take as directed by the physician",
         "B.No. CT2231  Mfg. Lic. No. 12/AB", "EXP 08/2024    MRP Rs. 30.00"])
    make(OUT / "painkiller_nsaid.jpg", ["Voveran SR 100", "Diclofenac Sodium 100 mg SR Tablets",
         "B.No. VS991  Mfd. by Novartis Lic. 55/KD", "EXP 11/2028    MRP Rs. 95.00"])
    make(OUT / "antibiotic.jpg", ["Azithral 500", "Azithromycin Tablets IP 500 mg", "Take as directed by the physician",
         "B.No. AZ551  Mfg. Lic. No. 21/KA", "EXP 03/2029   MRP Rs. 120.00"])
    print("wrote", *sorted(p.name for p in OUT.glob("*.jpg")))
