"""Проверки тегов, полки, статистики, рецензий, экспорта и карточки. Запуск: python3 tests/test_features.py"""
import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

import card  # noqa: E402
import export  # noqa: E402
import store  # noqa: E402
import utils  # noqa: E402
from test_store import FakeRepo, _raises  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORDS, _ = utils.load_words(ROOT / "words.yaml")
BY = {w["слово"]: w for w in WORDS}


def w(word, **kw):
    base = {k: "" for k in utils.FIELDS}
    base.update({"слово": word, "значение": "м"})
    base.update(kw)
    return base


# ---------- теги ----------
def test_split_tags_normalises():
    assert utils.split_tags("Одежда,  быт; #Одежда, ,") == ["одежда", "быт"]
    assert utils.split_tags("") == [] and utils.split_tags(None) == []
    assert utils.split_tags("Карточная игра") == ["карточная игра"]


def test_tags_as_yaml_list_and_string():
    words, errors = utils.parse_words('- слово: а\n  значение: б\n  теги: [Одежда, быт]\n- слово: в\n  значение: г\n  теги: "x, y"\n')
    assert errors == [] and words[0]["теги"] == "Одежда, быт" and words[1]["теги"] == "x, y"


def test_filter_by_tags_needs_all_selected_and_search_sees_tags():
    assert [x["слово"] for x in utils.filter_words(WORDS, tags=["одежда"])] == ["байковый", "шлафорка"]
    assert [x["слово"] for x in utils.filter_words(WORDS, tags=["Одежда", "быт"])] == ["шлафорка"]
    assert utils.filter_words(WORDS, tags=["одежда", "карты"]) == []
    assert [x["слово"] for x in utils.filter_words(WORDS, query="ткани")] == ["байковый"]
    assert "одежда" in utils.unique_tags(WORDS) and utils.unique_tags([]) == []


def test_build_entry_tags_and_roundtrip():
    e = store.build_entry(word="а", meaning="б", tags="Одежда, быт,  одежда")
    assert e["теги"] == "одежда, быт"
    words, _ = utils.parse_words(store.format_entry(e))
    assert words[0]["теги"] == "одежда, быт"
    assert "теги" not in store.format_entry(store.build_entry(word="а", meaning="б"))
    assert _raises(lambda: store.build_entry(word="а", meaning="б", tags="я" * 130)).args[0].startswith("Поле «теги»")


# ---------- полка и статистика ----------
def test_shelf_groups_and_orders():
    shelf = utils.shelf(WORDS)
    assert [(k, len(v)) for k, v in shelf] == [("«Метель», А. С. Пушкин", 5), ("«Выстрел», А. С. Пушкин", 1), ("«Пиковая дама», А. С. Пушкин", 1)]
    assert [x["слово"] for x in shelf[0][1]] == ["байковый", "землемер", "исправник", "кибитка", "шлафорка"]
    az = [k for k, _ in utils.shelf(WORDS, "az")]
    assert az == sorted(az, key=utils.norm)
    mixed = utils.shelf([w("а", произведение="Б"), w("б"), w("в", произведение="А")], "count")
    assert [k for k, _ in mixed] == ["А", "Б", utils.NO_WORK_TITLE]          # «без произведения» всегда в конце


def test_counts_and_summary():
    assert utils.count_by(WORDS, "произведение")["«Метель», А. С. Пушкин"] == 5
    assert "" not in utils.count_by([w("а"), w("б", пометка="устар.")], "пометка")
    assert utils.count_tags(WORDS)["одежда"] == 2
    today = date(2026, 10, 26)
    ws = [w("а", добавлено="2026-10-26"), w("б", добавлено="2026-10-01"), w("в", добавлено="2026-08-01"), w("г", добавлено="мусор"),
          w("д", картинка="x", цитата="y", добавлено="2026-10-20")]
    s = utils.summary(ws, today)
    assert (s["всего"], s["за неделю"], s["за месяц"], s["без даты"], s["с картинкой"], s["с цитатой"]) == (5, 2, 3, 1, 1, 1)


def test_words_per_week_includes_empty_weeks():
    today = date(2026, 10, 26)                                              # понедельник
    ws = [w("а", добавлено="2026-10-26"), w("б", добавлено="2026-10-25"), w("в", добавлено="2026-10-19"), w("г", добавлено="2020-01-01")]
    weeks = utils.words_per_week(ws, today, weeks=4)
    assert [d.isoformat() for d, _ in weeks] == ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]
    assert [n for _, n in weeks] == [0, 0, 2, 1]                            # воскресенье 25-го относится к неделе с 19-го


# ---------- рецензии ----------
def test_reviews_parse_and_format_roundtrip():
    data = {"«Метель», А. С. Пушкин": "https://t.me/x/12", 'С "кавычками": двоеточие': "https://t.me/x/1"}
    text = store.format_reviews(data)
    assert text.startswith("#") and utils.parse_reviews(text) == data
    assert utils.parse_reviews("") == {} and utils.parse_reviews(": : :") == {} and utils.parse_reviews("- a\n- b") == {}
    assert utils.parse_reviews('# только комментарии\n') == {}
    assert utils.load_reviews(ROOT / "reviews.yaml") == {} and utils.load_reviews(ROOT / "нет.yaml") == {}


def test_set_review_creates_updates_removes_and_validates():
    repo = FakeRepo({"words.yaml": b"- {}"})
    out = store.set_review(repo, " «Метель», А. С. Пушкин ", "https://t.me/x/12")
    assert out == {"«Метель», А. С. Пушкин": "https://t.me/x/12"} and "reviews.yaml" in repo.files
    store.set_review(repo, "«Выстрел», А. С. Пушкин", "https://t.me/x/7")
    store.set_review(repo, "«Метель», А. С. Пушкин", "https://t.me/x/13")
    assert utils.parse_reviews(repo.files["reviews.yaml"][0].decode()) == {"«Метель», А. С. Пушкин": "https://t.me/x/13", "«Выстрел», А. С. Пушкин": "https://t.me/x/7"}
    assert store.set_review(repo, "«Метель», А. С. Пушкин", "") == {"«Выстрел», А. С. Пушкин": "https://t.me/x/7"}
    for bad in ("t.me/x", "javascript:alert(1)", "https://a b", "ftp://x", "https://" + "a" * 300):
        assert isinstance(_raises(lambda: store.set_review(repo, "«Метель»", bad)), store.StoreError), bad
    assert isinstance(_raises(lambda: store.set_review(repo, " ", "https://t.me/x")), store.StoreError)


# ---------- экспорт ----------
def test_csv_export_opens_in_excel():
    data = export.to_csv(WORDS)
    assert data.startswith(b"\xef\xbb\xbf")                                  # метка UTF-8 для Excel
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0] == "Слово;Значение;Пометка;Теги;Произведение;Цитата;Картинка;Источник картинки;Добавлено" and len(lines) == len(WORDS) + 1
    assert lines[1].startswith("байковый;")                                  # по алфавиту
    tricky = export.to_csv([w("а;б", значение='с "кавычками"\nи переносом')]).decode("utf-8-sig")
    import csv
    rows = list(csv.reader(io.StringIO(tricky), delimiter=";"))
    assert rows[1][0] == "а;б" and rows[1][1] == 'с "кавычками"\nи переносом'


def test_html_export_escapes_and_embeds_images():
    nasty = w("<b>х</b>", значение='<script>alert(1)</script>', цитата='"q" & <i>', произведение="«П» <x>", картинка="images/kibitka.jpg", теги="а, б")
    page = export.to_html([nasty, BY["кибитка"]], image_loader=lambda p: (ROOT / p).read_bytes() if (ROOT / p).exists() else None,
                          reviews={"«П» <x>": 'https://t.me/x/1"onclick="x'}, today=date(2026, 10, 26))
    assert "<script>" not in page and "&lt;script&gt;" in page and "&lt;b&gt;х&lt;/b&gt;" in page
    assert 'href="https://t.me/x/1&quot;onclick=&quot;x"' in page and 'onclick="x' not in page      # кавычка в ссылке экранирована
    assert page.count("data:image/jpeg;base64,") == 2                                                      # у обоих слов есть картинка
    assert "Слов: 2" in page and "26.10.2026" in page
    assert '<h2 class="letter">К</h2>' in page and '<h2 class="letter">&lt;</h2>' in page          # буквы-разделители, тоже с экранированием
    plain = export.to_html([BY["кибитка"]], image_loader=lambda p: b"not an image")
    assert "data:image" not in plain and "Кибитка" in plain                                              # битая картинка не ломает выгрузку


# ---------- карточка для поста ----------
def test_card_png_size_and_content_variants():
    img = (ROOT / BY["кибитка"]["картинка"]).read_bytes()
    for word, image in ((BY["кибитка"], img), (BY["исправник"], None), (BY["шлафорка"], b"broken")):
        out = card.render_card(word, image)
        im = Image.open(io.BytesIO(out))
        assert im.format == "PNG" and im.size == card.SIZE
    huge = dict(BY["кибитка"], значение="слово " * 120, цитата="цитата " * 100, слово="неправдоподобнодлинноеслововрядлиприменяется" * 2)
    assert Image.open(io.BytesIO(card.render_card(huge, img))).size == card.SIZE        # очень длинное не ломает вёрстку
    bare = w("слово")
    assert Image.open(io.BytesIO(card.render_card(bare, None))).size == card.SIZE        # только слово и значение


def test_card_missing_font_message():
    err = _raises(lambda: card.render_card(BY["кибитка"], None, fonts_dir=ROOT / "нет_шрифтов"))
    assert isinstance(err, FileNotFoundError) and "fonts" in str(err)


def test_post_text_and_hashtags():
    t = card.post_text(BY["шлафорка"], "https://t.me/x/12")
    assert t.splitlines()[0] == "📖 Слово из прочитанного: ШЛАФОРКА (устар.)"
    assert "«Прасковья Петровна в шлафорке на вате»" in t and "— «Метель», А. С. Пушкин" in t and "https://t.me/x/12" in t
    assert t.splitlines()[-1] == "#второечтение #словоизпрочитанного #Метель #одежда #быт"
    assert card.hashtag("Пиковая дама") == "#Пиковая_дама" and card.hashtag("«Что-то»!") == "#Что_то" and card.hashtag("!!!") == ""
    bare = card.post_text(w("слово", значение="Что-то значит"))
    assert "Что-то значит." in bare and "http" not in bare and bare.endswith("#второечтение #словоизпрочитанного")
    assert "..." not in card.post_text(w("слово", значение="Вопрос?"))


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"Все проверки пройдены: {len(tests)}")
