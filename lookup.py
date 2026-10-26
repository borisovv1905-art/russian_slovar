"""Подсказки из интернета: значение слова (Викисловарь) и поиск цитаты (Викитека).

Обе функции только подсказывают: если сайт недоступен или ничего не нашёл, возвращают пустой результат,
а слово можно спокойно вписать вручную. Без Streamlit, чтобы разбор можно было проверять тестами.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote as urlquote

from utils import norm, word_stem

UA = {"User-Agent": "slovar-prochitannogo/1.0 (personal reading dictionary; https://github.com/borisovv1905-art/russian_slovar)"}
WIKT_API = "https://ru.wiktionary.org/w/api.php"
WSRC_API = "https://ru.wikisource.org/w/api.php"

_LABELS = {
    "устар": "устар.", "устаревшее": "устар.", "устаревш": "устар.",
    "истор": "историзм", "историзм": "историзм",
    "разг": "разг.", "разговорное": "разг.",
    "книжн": "книжн.", "книжное": "книжн.",
    "диал": "диал.", "диалектное": "диал.", "обл": "диал.", "областное": "диал.",
}


def _normalize_label(raw: str) -> str:
    key = raw.strip().lower().rstrip(".").strip()
    return _LABELS.get(key, "")


def _clean(raw: str) -> tuple[str, list[str]]:
    """Wiki-разметка → простой текст и найденные пометки (устар., разг. …)."""
    text = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    text = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    labels: list[str] = []
    # шаблоны вырезаем изнутри наружу; из «помета» достаём пометки
    while True:
        m = re.search(r"\{\{([^{}]*)\}\}", text)
        if not m:
            break
        parts = m.group(1).split("|")
        name = parts[0].strip().lower()
        if name.startswith(("помета", "п.")):
            candidates = parts[1:]
        elif _normalize_label(name):          # шаблон-пометка вроде {{разг.}}
            candidates = [name]
        else:
            candidates = []
        for p in candidates:
            lab = _normalize_label(p.split("=")[-1])
            if lab and lab not in labels:
                labels.append(lab)
        text = text[: m.start()] + text[m.end():]
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip(" ;,.:—-")
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text, labels


def parse_wiktionary(wikitext: str, limit: int = 3) -> list[dict]:
    """Значения русского слова из текста статьи Викисловаря: [{"text": ..., "labels": [...]}, ...]."""
    lines = wikitext.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if re.search(r"\{\{-ru-\}\}|^=+\s*Русский\s*=+\s*$", line):
            start = i
            break
    senses: list[dict] = []
    inside = False
    for line in lines[start:]:
        if re.match(r"^=+\s*Значение\s*=+\s*$", line):
            inside = True
            continue
        if inside:
            if line.startswith("="):
                break
            if line.startswith("#") and not line.startswith(("#*", "#:", "##", "#!")):
                if re.search(r"\{\{\s*форма-", line, re.I):
                    continue
                text, labels = _clean(line.lstrip("# "))
                if len(text) >= 3:
                    senses.append({"text": text, "labels": labels})
                if len(senses) >= limit:
                    break
    return senses


def suggest_meaning(word: str, http=None) -> list[dict]:
    """Значения слова из Викисловаря (до трёх). Пусто, если не нашлось или сайт недоступен."""
    word = word.strip().lower()
    if not word:
        return []
    http = http or _requests()
    try:
        resp = http.get(
            WIKT_API,
            params={"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                    "titles": word, "redirects": 1, "format": "json", "formatversion": 2},
            headers=UA, timeout=10,
        )
        if resp.status_code != 200:
            return []
        pages = resp.json().get("query", {}).get("pages", [])
        page = pages[0] if pages else {}
        if page.get("missing") or not page.get("revisions"):
            return []
        return parse_wiktionary(page["revisions"][0]["slots"]["main"]["content"])
    except Exception:  # noqa: BLE001  сеть, неожиданный ответ — подсказка просто не покажется
        return []


def _search_phrase(quote: str, max_words: int = 14) -> str:
    words = re.sub(r"[^\w\s]|_", " ", quote).split()
    return " ".join(words[:max_words])


def search_wikisource(quote: str, http=None, limit: int = 3) -> list[dict]:
    """Ищет цитату в Викитеке: [{"title", "url", "snippet"}]. Пусто, если не нашлось или сайт недоступен."""
    phrase = _search_phrase(quote)
    if len(phrase.split()) < 3:
        return []
    http = http or _requests()
    try:
        resp = http.get(
            WSRC_API,
            params={"action": "query", "list": "search", "srsearch": f'"{phrase}"', "srwhat": "text",
                    "srnamespace": 0, "srlimit": limit, "format": "json", "formatversion": 2},
            headers=UA, timeout=10,
        )
        if resp.status_code != 200:
            return []
        hits = resp.json().get("query", {}).get("search", [])
        out = []
        for h in hits:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", h.get("snippet", "")))
            snippet = re.sub(r"\s+", " ", snippet).strip()
            out.append({"title": h["title"], "url": "https://ru.wikisource.org/wiki/" + urlquote(h["title"].replace(" ", "_")),
                        "snippet": snippet})
        return out
    except Exception:  # noqa: BLE001
        return []


def quote_has_word(word: str, quote: str) -> bool:
    """Есть ли слово (в любой форме, по основе) в цитате. Для составных слов нужны все части."""
    q = norm(quote)
    for part in re.split(r"[\s-]+", norm(word)):
        if not part:
            continue
        if word_stem(part) not in q:
            return False
    return True


def _requests():
    import requests

    return requests
