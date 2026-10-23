"""Проверки логики словаря. Запуск из корня проекта: python3 tests/test_utils.py"""
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import capitalize_first, filter_words, load_words, norm, sort_words, unique_values, word_of_day  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def write(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "words.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_real_file_loads_without_errors():
    words, errors = load_words(ROOT / "words.yaml")
    assert errors == [], errors
    assert len(words) >= 4
    assert all(w["слово"] and w["значение"] for w in words)


def test_norm_treats_yo_as_ye():
    assert norm("  ЁЖ ") == "еж"


def test_capitalize_first_changes_only_first_letter():
    assert capitalize_first("жеребий") == "Жеребий"
    assert capitalize_first("ёлка-Палка") == "Ёлка-Палка"
    assert capitalize_first("Кибитка") == "Кибитка"
    assert capitalize_first("") == ""


def test_missing_required_fields_reported():
    words, errors = load_words(write("- слово: тест\n- значение: без слова\n- слово: ок\n  значение: есть\n"))
    assert [w["слово"] for w in words] == ["ок"]
    assert len(errors) == 2


def test_duplicates_skipped_ignoring_case_and_yo():
    words, errors = load_words(write("- {слово: Ёлка, значение: а}\n- {слово: елка, значение: б}\n"))
    assert len(words) == 1 and len(errors) == 1


def test_broken_and_missing_files_do_not_crash():
    assert load_words(write("- слово: [\n"))[0] == []
    assert load_words(ROOT / "нет_такого.yaml")[0] == []
    assert load_words(write("просто текст"))[0] == []
    assert load_words(write(""))[0] == []


def test_date_field_becomes_text():
    words, _ = load_words(write("- {слово: а, значение: б, добавлено: 2026-10-23}\n"))
    assert words[0]["добавлено"] == "2026-10-23"


def test_search_filters():
    words, _ = load_words(ROOT / "words.yaml")
    assert [w["слово"] for w in filter_words(words, query="ЖЕРЕБИЙ")] == ["жеребий"]
    assert len(filter_words(words, query="полиции")) == 1  # по значению
    assert len(filter_words(words, query="шмит")) == 1  # по цитате
    assert len(filter_words(words, work="«Метель», А. С. Пушкин")) == 3
    assert len(filter_words(words, label="историзм")) == 1
    assert filter_words(words, query="несуществующее") == []


def test_sorting():
    words, _ = load_words(ROOT / "words.yaml")
    az = [w["слово"] for w in sort_words(words, "az")]
    assert az == sorted(az, key=norm)
    newer = {"слово": "новое", "значение": "х", "добавлено": "2027-01-01"}
    older = {"слово": "старое", "значение": "х", "добавлено": "2026-01-01"}
    base = {k: "" for k in words[0]}
    pair = [{**base, **older}, {**base, **newer}]
    assert [w["слово"] for w in sort_words(pair, "new")] == ["новое", "старое"]


def test_unique_values_and_word_of_day():
    words, _ = load_words(ROOT / "words.yaml")
    assert "«Выстрел», А. С. Пушкин" in unique_values(words, "произведение")
    day = date(2026, 10, 23)
    assert word_of_day(words, day) == word_of_day(words, day)
    assert word_of_day([], day) is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"Все проверки пройдены: {len(tests)}")
