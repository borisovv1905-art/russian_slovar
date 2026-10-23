"""Логика словаря без Streamlit: загрузка, поиск, фильтры.

Вынесена отдельно, чтобы её можно было проверять тестами без запуска приложения.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

# Поля записи в words.yaml. Обязательны только «слово» и «значение».
FIELDS = (
    "слово",
    "значение",
    "пометка",
    "произведение",
    "цитата",
    "картинка",
    "картинка_источник",
    "добавлено",
)


def norm(text) -> str:
    """Приводит текст к виду для поиска: строчные буквы, «ё» = «е»."""
    return str(text).lower().replace("ё", "е").strip()


def capitalize_first(text: str) -> str:
    """Делает заглавной только первую букву, остальное не трогает («ёлка-палка» → «Ёлка-палка»)."""
    return text[:1].upper() + text[1:]


def load_words(path) -> tuple[list[dict], list[str]]:
    """Читает words.yaml. Возвращает (слова, список понятных ошибок)."""
    errors: list[str] = []
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    except FileNotFoundError:
        return [], [f"Файл {Path(path).name} не найден."]
    except yaml.YAMLError as exc:
        return [], [
            f"В файле {Path(path).name} ошибка разметки: {exc}. "
            "Частая причина: в тексте есть двоеточие или кавычки, а сам текст не взят в двойные кавычки."
        ]

    if not isinstance(raw, list):
        return [], [f"Файл {Path(path).name} должен быть списком слов."]

    words: list[dict] = []
    seen: set[str] = set()
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"Запись №{number}: это не набор полей, пропущена.")
            continue
        word = {
            key: ("" if item.get(key) is None else str(item.get(key)).strip())
            for key in FIELDS
        }
        if not word["слово"] or not word["значение"]:
            errors.append(f"Запись №{number}: нужны поля «слово» и «значение», пропущена.")
            continue
        key = norm(word["слово"])
        if key in seen:
            errors.append(f"Слово «{word['слово']}» (запись №{number}) повторяется, пропущено.")
            continue
        seen.add(key)
        words.append(word)
    return words, errors


def filter_words(words: list[dict], query: str = "", work: str = "", label: str = "") -> list[dict]:
    """Фильтрует по тексту поиска, произведению и пометке."""
    q = norm(query)
    result = []
    for w in words:
        if work and w["произведение"] != work:
            continue
        if label and w["пометка"] != label:
            continue
        if q:
            haystack = norm(" ".join((w["слово"], w["значение"], w["цитата"], w["произведение"])))
            if q not in haystack:
                continue
        result.append(w)
    return result


def sort_words(words: list[dict], mode: str = "az") -> list[dict]:
    """mode: «az» — по алфавиту, «new» — сначала недавно добавленные."""
    if mode == "new":
        indexed = list(enumerate(words))
        indexed.sort(key=lambda pair: (pair[1]["добавлено"], pair[0]), reverse=True)
        return [w for _, w in indexed]
    return sorted(words, key=lambda w: norm(w["слово"]))


def unique_values(words: list[dict], field: str) -> list[str]:
    """Непустые значения поля без повторов, по алфавиту (для списков фильтров)."""
    return sorted({w[field] for w in words if w[field]}, key=norm)


def word_of_day(words: list[dict], today: date | None = None) -> dict | None:
    """Слово дня: один и тот же выбор в течение суток."""
    if not words:
        return None
    today = today or date.today()
    ordered = sorted(words, key=lambda w: norm(w["слово"]))
    return ordered[today.toordinal() % len(ordered)]
