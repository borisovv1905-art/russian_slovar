"""Выгрузка словаря: таблица (CSV) и страница для печати/PDF (HTML). Без Streamlit."""
from __future__ import annotations

import base64
import csv
import html
import io
from datetime import date

from PIL import Image

from utils import FIELDS, capitalize_first, norm, split_tags

CSV_HEADERS = {
    "слово": "Слово", "значение": "Значение", "пометка": "Пометка", "теги": "Теги", "произведение": "Произведение",
    "цитата": "Цитата", "картинка": "Картинка", "картинка_источник": "Источник картинки", "добавлено": "Добавлено",
}


def to_csv(words: list[dict]) -> bytes:
    """CSV для Excel/Google Таблиц: разделитель «;», кодировка UTF-8 с меткой (иначе кириллица в Excel «поплывёт»)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([CSV_HEADERS[f] for f in FIELDS])
    for w in sorted(words, key=lambda w: norm(w["слово"])):
        writer.writerow([w[f] for f in FIELDS])
    return buf.getvalue().encode("utf-8-sig")


def _thumb_data_uri(data: bytes | None, width: int = 360) -> str:
    if not data:
        return ""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001  битая картинка не должна ломать выгрузку
        return ""
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


CSS = """
@page { margin: 16mm; }
body { font-family: Georgia, 'Times New Roman', serif; color: #1b1815; background: #fff; max-width: 780px; margin: 0 auto; padding: 24px; line-height: 1.45; }
h1 { font-size: 30px; margin: 0 0 4px; }
.sub { color: #6c6250; margin-bottom: 28px; }
h2.letter { font-size: 26px; border-bottom: 2px solid #1b1815; margin: 34px 0 14px; padding-bottom: 2px; break-after: avoid; }
.entry { display: flex; gap: 18px; margin: 0 0 18px; padding-bottom: 16px; border-bottom: 1px solid #d9ccae; break-inside: avoid; }
.entry img { width: 170px; height: auto; align-self: flex-start; border: 1px solid #1b1815; }
.word { font-size: 21px; font-weight: bold; }
.meta { color: #6c6250; font-size: 14px; font-style: italic; }
.quote { margin: 6px 0 0; padding-left: 12px; border-left: 3px solid #b9ac8f; font-style: italic; }
.work { font-style: normal; color: #6c6250; font-size: 14px; }
a { color: #8b5a2b; }
@media print { body { padding: 0; } a { color: inherit; text-decoration: none; } }
"""


def to_html(words: list[dict], image_loader=None, title: str = "Словарь прочитанного", reviews: dict | None = None,
            today: date | None = None) -> str:
    """Одна самодостаточная страница (картинки внутри файла): открывается в браузере, печатается или сохраняется в PDF."""
    reviews = reviews or {}
    esc = html.escape
    parts = [f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{esc(title)}</title>',
             '<meta name="viewport" content="width=device-width, initial-scale=1">', f"<style>{CSS}</style></head><body>",
             f"<h1>{esc(title)}</h1><div class=\"sub\">Слов: {len(words)} · {(today or date.today()).strftime('%d.%m.%Y')}</div>"]
    current = ""
    for w in sorted(words, key=lambda w: norm(w["слово"])):
        letter = capitalize_first(w["слово"])[:1]
        if letter != current:
            current = letter
            parts.append(f'<h2 class="letter">{esc(letter)}</h2>')
        uri = _thumb_data_uri(image_loader(w["картинка"]) if (image_loader and w["картинка"]) else None)
        meta = " · ".join(x for x in (w["пометка"], ", ".join(split_tags(w["теги"]))) if x)
        quote = ""
        if w["цитата"]:
            work = f' <span class="work">— {esc(w["произведение"])}</span>' if w["произведение"] else ""
            quote = f'<div class="quote">«{esc(w["цитата"])}»{work}</div>'
        elif w["произведение"]:
            quote = f'<div class="work">{esc(w["произведение"])}</div>'
        review = ""
        if reviews.get(w["произведение"]):
            review = f'<div class="work"><a href="{esc(reviews[w["произведение"]], quote=True)}">Рецензия в канале «Второе чтение»</a></div>'
        parts.append(
            '<div class="entry">' + (f'<img src="{uri}" alt="">' if uri else "") +
            f'<div><div class="word">{esc(capitalize_first(w["слово"]))}</div>'
            + (f'<div class="meta">{esc(meta)}</div>' if meta else "")
            + f'<div>{esc(w["значение"])}</div>{quote}{review}</div></div>'
        )
    parts.append("</body></html>")
    return "".join(parts)
