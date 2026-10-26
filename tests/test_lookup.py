"""Проверки подсказок (без интернета: ответы сайтов подставлены). Запуск: python3 tests/test_lookup.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lookup  # noqa: E402

WIKITEXT = """{{wikipedia}}
= {{-en-}} =
==== Значение ====
# wrong language
= {{-ru-}} =
{{слоги|ки|би́т|ка}}
=== Морфологические и синтаксические свойства ===
{{сущ ru f ina 3*a}}
=== Семантические свойства ===

==== Значение ====
# {{помета.|устар.}} [[крытый|крытая]] [[повозка]] на [[колесо|колёсах]] или [[полоз]]ьях{{пример|Бросился в кибитку|автор=А. С. Пушкин}}
#* {{пример|Бросился в кибитку и закричал: пошёл!|автор=А. С. Пушкин}}
# {{разг.}} ''жилище'' кочевников <ref>сноска</ref>
## вложенное значение
# {{форма-сущ|кибитка}}
# четвёртое
# пятое
==== Синонимы ====
# не значение
"""


class Resp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d


class Http:
    def __init__(self, resp=None, boom=False):
        self.resp, self.boom, self.calls = resp, boom, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if self.boom:
            raise OSError("нет сети")
        return self.resp


def test_parse_wiktionary_senses_and_labels():
    senses = lookup.parse_wiktionary(WIKITEXT)
    assert [s["text"] for s in senses] == [
        "крытая повозка на колёсах или полозьях",
        "жилище кочевников",
        "четвёртое",
    ]
    assert senses[0]["labels"] == ["устар."] and senses[1]["labels"] == ["разг."] and senses[2]["labels"] == []


def test_parse_wiktionary_without_language_marker_or_senses():
    assert lookup.parse_wiktionary("==== Значение ====\n# просто текст\n")[0]["text"] == "просто текст"
    assert lookup.parse_wiktionary("ничего нет") == []


def test_suggest_meaning_requests_and_failures():
    page = {"query": {"pages": [{"title": "кибитка", "revisions": [{"slots": {"main": {"content": WIKITEXT}}}]}]}}
    http = Http(Resp(page))
    got = lookup.suggest_meaning("  Кибитка ", http=http)
    url, kw = http.calls[0]
    assert got and kw["params"]["titles"] == "кибитка" and "User-Agent" in kw["headers"]
    assert lookup.suggest_meaning("", http=http) == []
    assert lookup.suggest_meaning("x", http=Http(Resp({"query": {"pages": [{"title": "x", "missing": True}]}}))) == []
    assert lookup.suggest_meaning("x", http=Http(Resp({}, 500))) == []
    assert lookup.suggest_meaning("x", http=Http(boom=True)) == []
    assert lookup.suggest_meaning("x", http=Http(Resp({"странный": "ответ"}))) == []


def test_search_wikisource():
    data = {"query": {"search": [{"title": "Метель (Пушкин)", "snippet": 'Гаврила Гаврилович <span class="searchmatch">в колпаке и байковой куртке</span> &amp; ещё'}]}}
    http = Http(Resp(data))
    hits = lookup.search_wikisource("«Гаврила Гаврилович в колпаке и байковой куртке»", http=http)
    assert hits[0]["title"] == "Метель (Пушкин)"
    assert hits[0]["url"].startswith("https://ru.wikisource.org/wiki/%D0%9C%D0%B5%D1%82%D0%B5%D0%BB%D1%8C_")
    assert hits[0]["snippet"] == "Гаврила Гаврилович в колпаке и байковой куртке & ещё"
    sent = http.calls[0][1]["params"]["srsearch"]
    assert sent == '"Гаврила Гаврилович в колпаке и байковой куртке"'      # без «» и знаков препинания
    assert lookup.search_wikisource("два слова", http=http) == []          # слишком коротко
    assert lookup.search_wikisource("раз два три четыре", http=Http(boom=True)) == []
    assert lookup.search_wikisource("раз два три четыре", http=Http(Resp({"query": {"search": []}}))) == []


def test_search_phrase_truncates_and_cleans():
    p = lookup._search_phrase("«Не могу постигнуть, — продолжал Томский, — каким образом бабушка моя не понтирует!» ещё слова тут и там")
    assert p.startswith("Не могу постигнуть продолжал Томский") and len(p.split()) == 14 and "—" not in p


def test_quote_has_word_in_other_forms():
    assert lookup.quote_has_word("байковый", "Гаврила Гаврилович в колпаке и байковой куртке")
    assert lookup.quote_has_word("шлафорка", "Прасковья Петровна в шлафорке на вате")
    assert lookup.quote_has_word("Землемер", "землемер Шмит в усах и шпорах")
    assert lookup.quote_has_word("капитан-исправник", "сын капитан-исправника")
    assert lookup.quote_has_word("жеребий", "кинем жеребий, кому стрелять первому")
    assert not lookup.quote_has_word("кибитка", "Гаврила Гаврилович в колпаке")
    assert not lookup.quote_has_word("капитан-исправник", "сын капитана")   # второй части нет


def test_labels_normalised():
    assert lookup._normalize_label("Устар.") == "устар." and lookup._normalize_label("истор.") == "историзм"
    assert lookup._normalize_label("что-то") == ""


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"Все проверки пройдены: {len(tests)}")
