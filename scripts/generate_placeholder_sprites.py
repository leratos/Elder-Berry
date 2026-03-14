"""Generiert Placeholder-Sprites für Saleria Berry (alle Emotionen).

Erstellt einfache 512x512 PNGs mit:
- Farbiger Silhouette (Kreis als Kopf)
- Emotions-spezifischer Farbe und Gesichtsausdruck
- Transparentem Hintergrund

Wird nur einmal ausgeführt – die Sprites werden danach manuell
durch richtige Assets ersetzt.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).parent.parent / "src" / "elder_berry" / "avatar" / "assets"
SIZE = 512
HEAD_RADIUS = 140
HEAD_CENTER = (SIZE // 2, SIZE // 2 - 40)

# Emotion → (Hintergrundfarbe, Augenform, Mundform)
EMOTION_STYLES = {
    "neutral":    {"color": (120, 90, 160), "eyes": "normal",  "mouth": "neutral"},
    "cheerful":   {"color": (200, 130, 60), "eyes": "happy",   "mouth": "smile"},
    "sarcastic":  {"color": (160, 80, 120), "eyes": "half",    "mouth": "smirk"},
    "motivated":  {"color": (60, 160, 100), "eyes": "wide",    "mouth": "grin"},
    "thoughtful": {"color": (80, 100, 170), "eyes": "half",    "mouth": "neutral"},
    "whisper":    {"color": (100, 80, 130), "eyes": "normal",  "mouth": "small_o"},
    "shy":        {"color": (180, 120, 140), "eyes": "down",   "mouth": "small"},
    "depressed":  {"color": (70, 70, 90),   "eyes": "down",    "mouth": "frown"},
    "sad":        {"color": (80, 90, 140),  "eyes": "sad",     "mouth": "frown"},
    "angry":      {"color": (180, 50, 50),  "eyes": "angry",   "mouth": "teeth"},
}


def draw_eyes(draw: ImageDraw.Draw, cx: int, cy: int, style: str) -> None:
    """Zeichnet Augen basierend auf dem Stil."""
    left_x, right_x = cx - 45, cx + 45
    eye_y = cy - 15

    if style == "normal":
        for x in (left_x, right_x):
            draw.ellipse([x - 12, eye_y - 12, x + 12, eye_y + 12], fill=(255, 255, 255))
            draw.ellipse([x - 6, eye_y - 6, x + 6, eye_y + 6], fill=(40, 40, 60))
    elif style == "happy":
        for x in (left_x, right_x):
            draw.arc([x - 14, eye_y - 10, x + 14, eye_y + 14], 200, 340, fill=(40, 40, 60), width=3)
    elif style == "half":
        for x in (left_x, right_x):
            draw.ellipse([x - 12, eye_y - 6, x + 12, eye_y + 8], fill=(255, 255, 255))
            draw.ellipse([x - 6, eye_y - 3, x + 6, eye_y + 5], fill=(40, 40, 60))
    elif style == "wide":
        for x in (left_x, right_x):
            draw.ellipse([x - 14, eye_y - 16, x + 14, eye_y + 16], fill=(255, 255, 255))
            draw.ellipse([x - 7, eye_y - 7, x + 7, eye_y + 7], fill=(40, 40, 60))
    elif style == "down":
        for x in (left_x, right_x):
            draw.ellipse([x - 10, eye_y, x + 10, eye_y + 14], fill=(255, 255, 255))
            draw.ellipse([x - 5, eye_y + 3, x + 5, eye_y + 11], fill=(40, 40, 60))
    elif style == "sad":
        for x in (left_x, right_x):
            draw.ellipse([x - 12, eye_y - 10, x + 12, eye_y + 10], fill=(255, 255, 255))
            draw.ellipse([x - 6, eye_y - 4, x + 6, eye_y + 6], fill=(40, 40, 60))
            # Träne
            draw.ellipse([x + 8, eye_y + 8, x + 14, eye_y + 20], fill=(100, 150, 255))
    elif style == "angry":
        for x in (left_x, right_x):
            draw.ellipse([x - 12, eye_y - 10, x + 12, eye_y + 10], fill=(255, 255, 255))
            draw.ellipse([x - 6, eye_y - 4, x + 6, eye_y + 6], fill=(180, 30, 30))
            # Augenbraue
            direction = -1 if x == left_x else 1
            draw.line(
                [x - 16, eye_y - 20 + direction * 6, x + 16, eye_y - 20 - direction * 6],
                fill=(40, 40, 60), width=4,
            )


def draw_mouth(draw: ImageDraw.Draw, cx: int, cy: int, style: str) -> None:
    """Zeichnet den Mund basierend auf dem Stil."""
    mouth_y = cy + 40

    if style == "neutral":
        draw.line([cx - 20, mouth_y, cx + 20, mouth_y], fill=(40, 40, 60), width=3)
    elif style == "smile":
        draw.arc([cx - 25, mouth_y - 10, cx + 25, mouth_y + 20], 10, 170, fill=(40, 40, 60), width=3)
    elif style == "smirk":
        draw.arc([cx - 5, mouth_y - 5, cx + 30, mouth_y + 15], 10, 170, fill=(40, 40, 60), width=3)
    elif style == "grin":
        draw.arc([cx - 30, mouth_y - 12, cx + 30, mouth_y + 22], 10, 170, fill=(40, 40, 60), width=4)
        draw.line([cx - 25, mouth_y + 2, cx + 25, mouth_y + 2], fill=(255, 255, 255), width=2)
    elif style == "small_o":
        draw.ellipse([cx - 10, mouth_y - 8, cx + 10, mouth_y + 8], fill=(40, 40, 60))
    elif style == "small":
        draw.line([cx - 10, mouth_y, cx + 10, mouth_y], fill=(40, 40, 60), width=2)
    elif style == "frown":
        draw.arc([cx - 25, mouth_y, cx + 25, mouth_y + 25], 200, 340, fill=(40, 40, 60), width=3)
    elif style == "teeth":
        draw.arc([cx - 28, mouth_y - 8, cx + 28, mouth_y + 18], 10, 170, fill=(40, 40, 60), width=3)
        draw.line([cx - 22, mouth_y + 2, cx + 22, mouth_y + 2], fill=(255, 255, 255), width=3)


def generate_sprite(emotion: str, style: dict) -> Image.Image:
    """Generiert ein einzelnes Sprite für eine Emotion."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color = style["color"]
    cx, cy = HEAD_CENTER

    # Körper (einfaches Trapez)
    body_top = cy + HEAD_RADIUS - 20
    draw.polygon(
        [(cx - 80, body_top), (cx + 80, body_top),
         (cx + 120, SIZE - 20), (cx - 120, SIZE - 20)],
        fill=color,
    )

    # Kopf
    draw.ellipse(
        [cx - HEAD_RADIUS, cy - HEAD_RADIUS,
         cx + HEAD_RADIUS, cy + HEAD_RADIUS],
        fill=color,
    )

    # Gesicht
    draw_eyes(draw, cx, cy, style["eyes"])
    draw_mouth(draw, cx, cy, style["mouth"])

    # Emotions-Label unten
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font = ImageFont.load_default()

    label = emotion.upper()
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    draw.text(
        ((SIZE - text_w) // 2, SIZE - 35),
        label, fill=(255, 255, 255, 180), font=font,
    )

    return img


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    for emotion, style in EMOTION_STYLES.items():
        img = generate_sprite(emotion, style)
        path = ASSETS_DIR / f"saleria-{emotion}.png"
        img.save(path)
        print(f"  Erstellt: {path.name} ({style['color']})")

    print(f"\n{len(EMOTION_STYLES)} Sprites generiert in {ASSETS_DIR}")


if __name__ == "__main__":
    main()
