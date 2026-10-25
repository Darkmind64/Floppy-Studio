"""Génère icon.ico (disquette stylisée)."""
from PIL import Image, ImageDraw

def frame(s):
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = s / 256
    d.rounded_rectangle([16*k, 16*k, 240*k, 240*k], radius=28*k, fill=(79, 140, 255))
    d.polygon([(196*k, 16*k), (240*k, 60*k), (240*k, 16*k)], fill=(15, 17, 21, 0))
    d.rounded_rectangle([64*k, 16*k, 184*k, 96*k], radius=8*k, fill=(225, 232, 245))
    d.rectangle([140*k, 30*k, 168*k, 84*k], fill=(40, 52, 75))
    d.rounded_rectangle([48*k, 132*k, 208*k, 228*k], radius=10*k, fill=(15, 17, 21))
    for i, c in enumerate([(52, 196, 124), (52, 196, 124), (227, 167, 59)]):
        y = (150 + i * 24) * k
        d.rounded_rectangle([68*k, y, (188 - i * 30)*k, y + 10*k], radius=4*k, fill=c)
    return im

frame(256).save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
