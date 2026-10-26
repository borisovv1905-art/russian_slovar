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
    "теги",
    "произведение",
    "цитата",
    "картинка",
    "картинка_источник",
    "добавлено",
)


def norm(text) -> str:
    """Приводит текст к виду для поиска: строчные буквы, «ё» = «е»."""
    return str(text).lower().replace("ё", "е").strip()


def word_stem(part: str) -> str:
    """Грубая основа слова для поиска его форм в тексте: отбрасываем окончание («кибитке» → «кибит»)."""
    part = norm(part)
    n = len(part)
    return part if n <= 3 else part[:-1] if n <= 5 else part[:-2] if n <= 7 else part[:-3]


def capitalize_first(text: str) -> str:
    """Делает заглавной только первую букву, остальное не трогает («ёлка-палка» → «Ёлка-палка»)."""
    return text[:1].upper() + text[1:]


def _as_text(value) -> str:
    """Значение поля как текст; список (теги в виде списка YAML) склеивается через запятую."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def parse_words(text: str, name: str = "words.yaml") -> tuple[list[dict], list[str]]:
    """Разбирает текст words.yaml. Возвращает (слова, список понятных ошибок)."""
    errors: list[str] = []
    try:
        raw = yaml.safe_load(text) or []
    except yaml.YAMLError as exc:
        return [], [
            f"В файле {name} ошибка разметки: {exc}. "
            "Частая причина: в тексте есть двоеточие или кавычки, а сам текст не взят в двойные кавычки."
        ]

    if not isinstance(raw, list):
        return [], [f"Файл {name} должен быть списком слов."]

    words: list[dict] = []
    seen: set[str] = set()
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"Запись №{number}: это не набор полей, пропущена.")
            continue
        word = {key: _as_text(item.get(key)) for key in FIELDS}
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


def load_words(path) -> tuple[list[dict], list[str]]:
    """Читает words.yaml. Возвращает (слова, список понятных ошибок)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], [f"Файл {Path(path).name} не найден."]
    return parse_words(text, Path(path).name)


def split_tags(text: str) -> list[str]:
    """«Одежда,  быт, одежда» → ["одежда", "быт"]: строчные, без повторов, порядок сохраняется."""
    seen: dict[str, None] = {}
    for part in str(text or "").replace(";", ",").replace("#", " ").split(","):
        tag = " ".join(part.split()).lower()
        if tag:
            seen.setdefault(tag, None)
    return list(seen)


def unique_tags(words: list[dict]) -> list[str]:
    """Все теги словаря по алфавиту."""
    return sorted({t for w in words for t in split_tags(w["теги"])}, key=norm)


def filter_words(words: list[dict], query: str = "", work: str = "", label: str = "", tags: list[str] | None = None) -> list[dict]:
    """Фильтрует по тексту поиска, произведению, пометке и тегам (нужны все выбранные теги)."""
    q = norm(query)
    wanted = {norm(t) for t in (tags or [])}
    result = []
    for w in words:
        if work and w["произведение"] != work:
            continue
        if label and w["пометка"] != label:
            continue
        if wanted and not wanted <= {norm(t) for t in split_tags(w["теги"])}:
            continue
        if q:
            haystack = norm(" ".join((w["слово"], w["значение"], w["цитата"], w["произведение"], w["теги"])))
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


# ---------- полка и статистика ----------

NO_WORK_TITLE = "Без произведения"


def shelf(words: list[dict], order: str = "count") -> list[tuple[str, list[dict]]]:
    """Слова по произведениям: [(произведение, [слова по алфавиту])]. order: «count» — больше слов выше, «az» — по алфавиту.

    Слова без произведения собираются в конце под заголовком «Без произведения».
    """
    groups: dict[str, list[dict]] = {}
    for w in words:
        groups.setdefault(w["произведение"] or NO_WORK_TITLE, []).append(w)
    for items in groups.values():
        items.sort(key=lambda w: norm(w["слово"]))
    named = [(k, v) for k, v in groups.items() if k != NO_WORK_TITLE]
    named.sort(key=(lambda kv: (-len(kv[1]), norm(kv[0]))) if order == "count" else (lambda kv: norm(kv[0])))
    if NO_WORK_TITLE in groups:
        named.append((NO_WORK_TITLE, groups[NO_WORK_TITLE]))
    return named


def count_by(words: list[dict], field: str) -> dict[str, int]:
    """Сколько слов с каждым значением поля (пустые значения не считаются), по убыванию."""
    counts: dict[str, int] = {}
    for w in words:
        if w[field]:
            counts[w[field]] = counts.get(w[field], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], norm(kv[0]))))


def count_tags(words: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for w in words:
        for t in split_tags(w["теги"]):
            counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], norm(kv[0]))))


def week_start(day: date) -> date:
    return date.fromordinal(day.toordinal() - day.weekday())


def words_per_week(words: list[dict], today: date | None = None, weeks: int = 12) -> list[tuple[date, int]]:
    """Сколько слов добавлено в каждую из последних недель (с понедельника), включая пустые недели."""
    today = today or date.today()
    start = week_start(today)
    firsts = [date.fromordinal(start.toordinal() - 7 * i) for i in range(weeks - 1, -1, -1)]
    counts = {d: 0 for d in firsts}
    for w in words:
        try:
            added = date.fromisoformat(w["добавлено"])
        except ValueError:
            continue
        ws = week_start(added)
        if ws in counts:
            counts[ws] += 1
    return list(counts.items())


def summary(words: list[dict], today: date | None = None) -> dict:
    """Итоги для вкладки статистики."""
    today = today or date.today()
    dated = []
    for w in words:
        try:
            dated.append(date.fromisoformat(w["добавлено"]))
        except ValueError:
            pass
    return {
        "всего": len(words),
        "произведений": len({w["произведение"] for w in words if w["произведение"]}),
        "за неделю": sum(1 for d in dated if 0 <= (today - d).days < 7),
        "за месяц": sum(1 for d in dated if 0 <= (today - d).days < 30),
        "с картинкой": sum(1 for w in words if w["картинка"]),
        "с цитатой": sum(1 for w in words if w["цитата"]),
        "без даты": len(words) - len(dated),
    }


# ---------- рецензии на произведения ----------

def parse_reviews(text: str) -> dict[str, str]:
    """reviews.yaml: «произведение» → ссылка на рецензию. Испорченный файл даёт пустой словарь."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}


def load_reviews(path) -> dict[str, str]:
    try:
        return parse_reviews(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
