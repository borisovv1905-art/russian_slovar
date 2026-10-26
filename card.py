"""Картинка-карточка слова для поста в Telegram и текст поста. Без Streamlit."""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from utils import capitalize_first, split_tags

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
SIZE = (1080, 1350)               # 4:5, хорошо смотрится в ленте Telegram
INK, PAPER, MUTED, RULE = "#1b1815", "#efe4cb", "#6c6250", "#b9ac8f"
MARGIN = 84
CHANNEL = "Второе чтение"


def _font(name: str, size: int, fonts_dir: Path) -> ImageFont.FreeTypeFont:
    path = Path(fonts_dir) / f"LiberationSerif-{name}.ttf"
    if not path.is_file():   # без проверки Pillow молча подставил бы шрифт из системы, и вид карточки зависел бы от машины
        raise FileNotFoundError(f"Не найден шрифт {path.name} в папке fonts/ проекта.")
    return ImageFont.truetype(str(path), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Перенос по словам под заданную ширину (длинное слово без пробелов режется по буквам)."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                line = trial
                continue
            if line:
                lines.append(line)
            while draw.textlength(word, font=font) > max_width and len(word) > 1:
                cut = len(word)
                while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def _contain(img: Image.Image, width: int, height: int) -> Image.Image:
    """Вписывает картинку целиком (без обрезки, чтобы рамка рисунка осталась на месте)."""
    img = img.convert("RGB")
    scale = min(width / img.width, height / img.height)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def render_card(word: dict, image_bytes: bytes | None = None, fonts_dir: Path = FONTS_DIR) -> bytes:
    """PNG-карточка: картинка, слово, значение, цитата с источником, подпись канала."""
    W, H = SIZE
    inner = W - 2 * MARGIN
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title = capitalize_first(word["слово"])
    meaning = word["значение"]
    quote = f"«{word['цитата']}»" if word["цитата"] else ""
    source = f"— {word['произведение']}" if word["произведение"] and word["цитата"] else (word["произведение"] or "")
    meta = " · ".join(x for x in (word["пометка"], ", ".join(split_tags(word["теги"]))) if x)

    photo = None
    if image_bytes:
        try:
            photo = Image.open(io.BytesIO(image_bytes))
            photo.load()
        except Exception:  # noqa: BLE001
            photo = None

    top_block = 150            # шапка «Слово из прочитанного»
    bottom_block = 150         # подпись канала
    gap = 34

    # подбираем масштаб шрифтов, чтобы всё влезло
    for k in (1.0, 0.92, 0.84, 0.76, 0.68, 0.6):
        f_title = _font("Bold", int(112 * k), fonts_dir)
        while probe.textlength(title, font=f_title) > inner and f_title.size > 40:
            f_title = _font("Bold", f_title.size - 4, fonts_dir)
        f_meta = _font("Italic", int(34 * k), fonts_dir)
        f_text = _font("Regular", int(44 * k), fonts_dir)
        f_quote = _font("Italic", int(40 * k), fonts_dir)
        f_src = _font("Regular", int(32 * k), fonts_dir)
        meaning_lines = wrap(probe, capitalize_first(meaning), f_text, inner)
        quote_lines = wrap(probe, quote, f_quote, inner - 36) if quote else []
        src_lines = wrap(probe, source, f_src, inner - 36) if source else []
        h_title = f_title.size + 14
        h_meta = (f_meta.size + 12) if meta else 0
        h_meaning = len(meaning_lines) * int(f_text.size * 1.28)
        h_quote = (len(quote_lines) * int(f_quote.size * 1.3) + 8) if quote_lines else 0
        h_src = (len(src_lines) * int(f_src.size * 1.3) + 6) if src_lines else 0
        text_h = h_title + h_meta + gap // 2 + h_meaning + (gap + h_quote + h_src if (quote_lines or src_lines) else 0)
        free = H - top_block - bottom_block - text_h - gap
        if free >= (300 if photo else 0):
            break
    img_h = min(free, 640) if photo else 0

    canvas = Image.new("RGB", SIZE, PAPER)
    d = ImageDraw.Draw(canvas)
    d.rectangle((24, 24, W - 24, H - 24), outline=INK, width=4)
    d.rectangle((38, 38, W - 38, H - 38), outline=INK, width=1)

    f_head = _font("Regular", 28, fonts_dir)
    head = "С Л О В О   И З   П Р О Ч И Т А Н Н О Г О"
    d.text((W / 2, 96), head, font=f_head, fill=MUTED, anchor="mm")
    d.line((MARGIN + 120, 128, W - MARGIN - 120, 128), fill=RULE, width=2)

    y = top_block
    if photo:
        fitted = _contain(photo, inner, img_h)
        px = MARGIN + (inner - fitted.width) // 2
        canvas.paste(fitted, (px, y))
        d.rectangle((px - 1, y - 1, px + fitted.width, y + fitted.height), outline=INK, width=3)
        y += fitted.height + gap
    else:
        # без картинки: свободное место делим пополам, текст стоит по центру
        y += max(0, free) // 2

    d.text((MARGIN, y), title, font=f_title, fill=INK)
    y += h_title
    if meta:
        d.text((MARGIN, y), meta, font=f_meta, fill=MUTED)
        y += h_meta
    y += gap // 2
    for line in meaning_lines:
        d.text((MARGIN, y), line, font=f_text, fill=INK)
        y += int(f_text.size * 1.28)

    if quote_lines or src_lines:
        y += gap
        top = y
        for line in quote_lines:
            d.text((MARGIN + 36, y), line, font=f_quote, fill=INK)
            y += int(f_quote.size * 1.3)
        y += 8
        for line in src_lines:
            d.text((MARGIN + 36, y), line, font=f_src, fill=MUTED)
            y += int(f_src.size * 1.3)
        d.line((MARGIN + 8, top, MARGIN + 8, y - 6), fill=RULE, width=5)

    d.line((MARGIN + 120, H - 118, W - MARGIN - 120, H - 118), fill=RULE, width=2)
    d.text((W / 2, H - 80), CHANNEL, font=_font("Italic", 36, fonts_dir), fill=MUTED, anchor="mm")

    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


def hashtag(text: str) -> str:
    """«Пиковая дама» → #Пиковая_дама (в хэштеге Telegram только буквы, цифры и подчёркивание)."""
    tag = re.sub(r"[^\w]+", "_", text.strip(), flags=re.UNICODE).strip("_")
    return f"#{tag}" if tag else ""


def post_text(word: dict, review_url: str = "") -> str:
    """Готовый текст поста для канала (простой текст, без разметки)."""
    head = f"📖 Слово из прочитанного: {capitalize_first(word['слово']).upper()}"
    if word["пометка"]:
        head += f" ({word['пометка']})"
    lines = [head, "", capitalize_first(word["значение"]) + ("" if word["значение"].rstrip().endswith((".", "!", "?")) else ".")]
    if word["цитата"]:
        lines += ["", f"«{word['цитата']}»"]
        if word["произведение"]:
            lines.append(f"— {word['произведение']}")
    elif word["произведение"]:
        lines += ["", word["произведение"]]
    if review_url:
        lines += ["", f"Рецензия на это произведение: {review_url}"]
    tags = ["#второечтение", "#словоизпрочитанного"]
    m = re.search(r"«([^»]+)»", word["произведение"] or "")
    if m:
        tags.append(hashtag(m.group(1)))
    tags += [hashtag(t) for t in split_tags(word["теги"])]
    lines += ["", " ".join(dict.fromkeys(t for t in tags if t))]
    return "\n".join(lines)
