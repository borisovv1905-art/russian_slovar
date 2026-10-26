"""Проверки сохранения слов (без интернета: GitHub подменён). Запуск: python3 tests/test_store.py"""
import base64
import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

import store  # noqa: E402
from store import ConflictError, StoreError, add_word, append_entry, build_entry, format_entry  # noqa: E402
from utils import parse_words  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_YAML = (ROOT / "words.yaml").read_text(encoding="utf-8")


class FakeRepo:
    """Хранит файлы в памяти, умеет имитировать конфликт версий."""

    def __init__(self, files=None, conflicts=0):
        self.files = {k: (v, "sha0") for k, v in (files or {"words.yaml": REAL_YAML.encode()}).items()}
        self.conflicts = conflicts
        self.puts = []

    def get_file(self, path):
        return self.files.get(path)

    def put_file(self, path, content, message, sha=None):
        if path == "words.yaml" and self.conflicts > 0:
            self.conflicts -= 1
            # кто-то другой успел изменить файл
            self.files[path] = (self.files[path][0] + "\n# чужая правка\n".encode(), "sha-other")
            raise ConflictError()
        self.puts.append((path, message))
        self.files[path] = (content, f"sha{len(self.puts)}")


def png_bytes(size=(1600, 1200), mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 120) if mode == "RGBA" else "red").save(buf, "PNG")
    return buf.getvalue()


def entry(**kw):
    base = dict(word="Мундштук", meaning="часть уздечки", label="устар.", work="«Выстрел», А. С. Пушкин",
                quote="«ехал: шагом»", added=date(2026, 10, 26))
    base.update(kw)
    return build_entry(**base)


def test_format_roundtrip_with_tricky_text():
    e = entry(meaning='слово "в кавычках": с двоеточием # и решёткой', quote="a: b\\c")
    words, errors = parse_words(append_entry(REAL_YAML, e))
    assert errors == []
    new = words[-1]
    assert new["значение"] == 'слово "в кавычках": с двоеточием # и решёткой'
    assert new["цитата"] == "a: b\\c"          # внешние «» сняты, обратная косая цела
    assert new["добавлено"] == "2026-10-26"


def test_comments_and_old_entries_untouched():
    result = append_entry(REAL_YAML, entry())
    assert result.startswith(REAL_YAML.rstrip("\n"))
    assert len(parse_words(result)[0]) == len(parse_words(REAL_YAML)[0]) + 1


def test_file_without_final_newline():
    text = REAL_YAML.rstrip("\n")
    assert len(parse_words(append_entry(text, entry()))[0]) == len(parse_words(REAL_YAML)[0]) + 1


def test_duplicate_is_refused_even_with_yo_and_case():
    for w in ("Кибитка", "КИБИТКА", " кибитка "):
        try:
            append_entry(REAL_YAML, entry(word=w))
        except StoreError as exc:
            assert "уже есть" in str(exc)
        else:
            raise AssertionError("дубль не отклонён")


def test_required_and_limits():
    for kw, text in (({"word": " "}, "слово"), ({"meaning": ""}, "значение"), ({"quote": "я" * 701}, "слишком длинное")):
        try:
            entry(**kw)
        except StoreError as exc:
            assert text in str(exc)
        else:
            raise AssertionError(kw)


def test_empty_optional_fields_are_skipped():
    text = format_entry(build_entry(word="а", meaning="б", added=date(2026, 1, 2)))
    assert text == '- слово: "а"\n  значение: "б"\n  добавлено: 2026-01-02\n'


def test_slugify_and_password():
    assert store.slugify("Кибитка") == "kibitka"
    assert store.slugify("Шлафорка!") == "shlaforka"
    assert store.slugify("???") == "word"
    assert store.check_password("секрет", "секрет")
    assert not store.check_password("Секрет", "секрет")
    assert not store.check_password("", "")
    assert not store.check_password("x", "")


def test_image_prepared_as_small_jpeg():
    data = store.prepare_image(png_bytes())
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG" and img.width == 900 and img.height == 675
    for bad in (b"not an image", b"\x89PNG garbage"):
        try:
            store.prepare_image(bad)
        except StoreError:
            pass
        else:
            raise AssertionError("битый файл принят")


def test_add_word_commits_image_then_words():
    repo = FakeRepo()
    saved = add_word(repo, entry(), image_bytes=png_bytes())
    assert saved["картинка"] == "images/mundshtuk.jpg"
    assert [p for p, _ in repo.puts] == ["images/mundshtuk.jpg", "words.yaml"]
    words, errors = parse_words(repo.files["words.yaml"][0].decode())
    assert errors == [] and words[-1]["картинка"] == "images/mundshtuk.jpg"


def test_image_name_does_not_overwrite_existing():
    repo = FakeRepo({"words.yaml": REAL_YAML.encode(), "images/mundshtuk.jpg": b"old"})
    saved = add_word(repo, entry(), image_bytes=png_bytes())
    assert saved["картинка"] == "images/mundshtuk-2.jpg"
    assert repo.files["images/mundshtuk.jpg"][0] == b"old"


def test_conflict_is_retried_and_other_edit_preserved():
    repo = FakeRepo(conflicts=2)
    add_word(repo, entry())
    final = repo.files["words.yaml"][0].decode()
    assert "# чужая правка" in final and '"Мундштук"' in final


def test_conflict_gives_up_politely():
    try:
        add_word(FakeRepo(conflicts=5), entry())
    except StoreError as exc:
        assert "ещё раз" in str(exc)
    else:
        raise AssertionError


def test_duplicate_found_on_github_side_even_if_page_is_stale():
    # на экране слова ещё нет, а в репозитории уже есть
    repo = FakeRepo({"words.yaml": (REAL_YAML + '\n- слово: "мундштук"\n  значение: "x"\n').encode()})
    try:
        add_word(repo, entry())
    except StoreError as exc:
        assert "уже есть" in str(exc)
    else:
        raise AssertionError
    assert repo.puts == []


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self, get=None, put=None):
        self.calls, self._get, self._put = [], get, put

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._get

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw))
        return self._put


def test_github_client_requests():
    content = base64.b64encode("привет".encode()).decode()
    http = FakeHttp(Resp(200, {"content": content, "sha": "abc"}), Resp(200))
    gh = store.GitHubRepo("me/repo", "TOKEN123", "main", http=http)
    assert gh.get_file("words.yaml") == ("привет".encode(), "abc")
    gh.put_file("words.yaml", "новое".encode(), "msg", "abc")
    (_, url, kw), (_, _, kw2) = http.calls
    assert url == "https://api.github.com/repos/me/repo/contents/words.yaml"
    assert kw["params"] == {"ref": "main"} and kw["headers"]["Authorization"] == "Bearer TOKEN123"
    assert kw2["json"]["sha"] == "abc" and kw2["json"]["branch"] == "main"
    assert base64.b64decode(kw2["json"]["content"]).decode() == "новое"


def test_github_errors_are_friendly_and_hide_token():
    for code, part in ((401, "токен"), (403, "токен"), (404, "не нашёл"), (500, "500")):
        gh = store.GitHubRepo("me/repo", "SECRET-TOKEN", http=FakeHttp(put=Resp(code)))
        try:
            gh.put_file("x", b"1", "m")
        except StoreError as exc:
            assert part in str(exc) and "SECRET-TOKEN" not in str(exc)
        else:
            raise AssertionError(code)
    assert store.GitHubRepo("me/repo", "t", http=FakeHttp(get=Resp(404))).get_file("nope") is None
    assert isinstance(_raises(lambda: store.GitHubRepo("bad", "t")), StoreError)
    assert isinstance(_raises(lambda: store.GitHubRepo("a/b", "")), StoreError)
    gh = store.GitHubRepo("a/b", "t", http=FakeHttp(put=Resp(409)))
    assert isinstance(_raises(lambda: gh.put_file("x", b"1", "m")), ConflictError)


def _raises(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"Все проверки пройдены: {len(tests)}")
