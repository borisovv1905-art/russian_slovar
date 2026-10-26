"""Тренировка: подбор слов, карточки с пропуском, викторина, прогресс (без Streamlit).

Прогресс — словарь «слово → запись»:
  {"верно": 3, "неверно": 1, "серия": 2, "выучено": False, "последний": "2026-10-26", "обновлено": "2026-10-26T08:00:00"}
Ключ — слово в нижнем регистре с «е» вместо «ё» (utils.norm), поэтому правка регистра прогресс не сбивает.
"""
from __future__ import annotations

import json
import random
import re
from datetime import date, datetime, timezone

from utils import norm, word_stem

LEARNED_STREAK = 3          # столько верных ответов подряд — и слово считается выученным
BLANK = "_____"
DIRECTIONS = ("Слово → значение", "Значение → слово")


# ---------- прогресс ----------

def key_of(word: dict | str) -> str:
    return norm(word["слово"] if isinstance(word, dict) else word)


def is_learned(progress: dict, word: dict | str) -> bool:
    return bool(progress.get(key_of(word), {}).get("выучено"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def record_answer(progress: dict, word: dict | str, correct: bool, today: date | None = None, now: str | None = None) -> dict:
    """Записывает ответ. Верно ×3 подряд — «выучено»; ошибка сбрасывает серию и снимает «выучено»."""
    rec = dict(progress.get(key_of(word), {}))
    rec.setdefault("верно", 0), rec.setdefault("неверно", 0), rec.setdefault("серия", 0)
    rec.setdefault("выучено", False)
    if correct:
        rec["верно"] += 1
        rec["серия"] += 1
        if rec["серия"] >= LEARNED_STREAK:
            rec["выучено"] = True
    else:
        rec["неверно"] += 1
        rec["серия"] = 0
        rec["выучено"] = False
    rec["последний"] = (today or date.today()).isoformat()
    rec["обновлено"] = now or _now_iso()
    progress[key_of(word)] = rec
    return rec


def set_learned(progress: dict, word: dict | str, learned: bool, now: str | None = None) -> None:
    """Ручная отметка. «Вернуть в изучение» обнуляет серию, чтобы слово снова не стало выученным с одного ответа."""
    rec = dict(progress.get(key_of(word), {}))
    rec.setdefault("верно", 0), rec.setdefault("неверно", 0)
    rec["выучено"] = learned
    rec["серия"] = LEARNED_STREAK if learned else 0
    rec["обновлено"] = now or _now_iso()
    progress[key_of(word)] = rec


def merge_progress(local: dict, remote: dict) -> dict:
    """Объединяет два прогресса: для каждого слова побеждает более поздняя запись."""
    out = dict(remote)
    for k, rec in local.items():
        if k not in out or rec.get("обновлено", "") >= out[k].get("обновлено", ""):
            out[k] = rec
    return out


def dump_progress(progress: dict) -> str:
    return json.dumps(progress, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def load_progress_text(text: str) -> dict:
    """Читает файл прогресса; испорченный или пустой файл даёт пустой прогресс, а не ошибку."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def stats(words: list[dict], progress: dict) -> dict:
    learned = sum(1 for w in words if is_learned(progress, w))
    seen = sum(1 for w in words if key_of(w) in progress)
    shaky = sum(1 for w in words if progress.get(key_of(w), {}).get("неверно", 0) > progress.get(key_of(w), {}).get("верно", 0))
    return {"всего": len(words), "выучено": learned, "в работе": seen - learned, "новых": len(words) - seen, "шатких": shaky}


# ---------- подбор слов ----------

def priority(rec: dict | None, today: date) -> float:
    """Чем выше, тем скорее слово попадёт в раунд: новые, ошибочные и давно не виденные."""
    if not rec:
        return 3.0
    total = rec.get("верно", 0) + rec.get("неверно", 0)
    err = rec.get("неверно", 0) / total if total else 0.0
    try:
        days = (today - date.fromisoformat(rec.get("последний", ""))).days
    except ValueError:
        days = 14
    return max(0.2, 1 + 3 * err + min(max(days, 0), 14) / 7 - 0.5 * min(rec.get("серия", 0), 3))


def pick_words(words: list[dict], progress: dict, n: int, rng: random.Random | None = None,
               include_learned: bool = False, today: date | None = None) -> list[dict]:
    """n слов без повторов, случайно, но с перевесом в сторону трудных и новых."""
    rng = rng or random.Random()
    today = today or date.today()
    pool = [w for w in words if include_learned or not is_learned(progress, w)]
    keyed = sorted(
        pool,
        key=lambda w: rng.random() ** (1 / priority(progress.get(key_of(w)), today)),
        reverse=True,
    )
    return keyed[:n]


# ---------- тексты вопросов ----------

def _word_pattern(word: str) -> re.Pattern | None:
    """Шаблон слова в любой форме; составное («капитан-исправник») ищется целиком, по основе каждой части."""
    parts = [p for p in re.split(r"[\s-]+", norm(word)) if p]
    if not parts:
        return None
    stems = ["".join("[её]" if ch in "её" else re.escape(ch) for ch in word_stem(p)) + r"\w*" for p in parts]
    return re.compile(r"(?<!\w)" + r"[-\s]+".join(stems), re.IGNORECASE)


def blank_quote(word: str, quote: str) -> str | None:
    """Цитата с пропуском вместо слова (в любой форме). None, если слова в цитате не нашлось."""
    pattern = _word_pattern(word)
    if not pattern or not quote:
        return None
    result, count = pattern.subn(BLANK, quote)
    return result if count else None


def mark_quote(word: str, quote: str) -> str:
    """Цитата с выделенным жирным словом (в любой форме), для markdown."""
    pattern = _word_pattern(word)
    if not pattern or not quote:
        return quote
    return pattern.sub(lambda m: f"**{m.group(0)}**", quote)


def make_quiz(words: list[dict], picked: list[dict], direction: str, rng: random.Random | None = None,
              options_count: int = 4) -> list[dict]:
    """Вопросы викторины: [{"слово": запись, "варианты": [...], "верный": индекс}].

    «Слово → значение»: варианты — значения; «Значение → слово»: варианты — слова.
    Неверные варианты берутся из других слов словаря. Нужно хотя бы два разных слова.
    """
    rng = rng or random.Random()
    questions = []
    for w in picked:
        field = "значение" if direction == DIRECTIONS[0] else "слово"
        right = w[field]
        others = [o[field] for o in words if key_of(o) != key_of(w) and o[field] != right]
        others = list(dict.fromkeys(others))
        rng.shuffle(others)
        options = [right] + others[: options_count - 1]
        if len(options) < 2:
            continue
        rng.shuffle(options)
        questions.append({"слово": w, "варианты": options, "верный": options.index(right)})
    return questions
