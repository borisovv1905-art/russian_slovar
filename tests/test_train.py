"""Проверки тренировки (без Streamlit и интернета). Запуск: python3 tests/test_train.py"""
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import store  # noqa: E402
import train  # noqa: E402
from test_store import FakeRepo, Resp, FakeHttp, _raises  # noqa: E402
from utils import load_words  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORDS, _ = load_words(ROOT / "words.yaml")
D1, D2 = date(2026, 10, 26), date(2026, 10, 30)


def test_three_correct_in_a_row_marks_learned_and_mistake_resets():
    p = {}
    w = WORDS[0]
    for i in range(2):
        train.record_answer(p, w, True, D1, f"2026-10-26T0{i}:00:00")
    assert not train.is_learned(p, w)
    train.record_answer(p, w, True, D1, "2026-10-26T03:00:00")
    assert train.is_learned(p, w) and p[train.key_of(w)]["верно"] == 3
    train.record_answer(p, w, False, D2, "2026-10-30T01:00:00")
    rec = p[train.key_of(w)]
    assert not rec["выучено"] and rec["серия"] == 0 and rec["неверно"] == 1 and rec["последний"] == "2026-10-30"


def test_manual_learned_and_back():
    p = {}
    train.set_learned(p, "Кибитка", True)
    assert train.is_learned(p, "кибитка") and train.is_learned(p, {"слово": "КИБИТКА"})
    train.set_learned(p, "кибитка", False)
    assert not train.is_learned(p, "кибитка") and p["кибитка"]["серия"] == 0
    # после возврата одного верного ответа мало
    train.record_answer(p, "кибитка", True)
    assert not train.is_learned(p, "кибитка")


def test_key_ignores_case_and_yo():
    assert train.key_of("Ёлка") == train.key_of({"слово": "елка"})


def test_merge_takes_later_record_per_word():
    local = {"а": {"верно": 5, "обновлено": "2026-10-26T10:00:00"}, "б": {"верно": 1, "обновлено": "2026-10-26T09:00:00"}}
    remote = {"а": {"верно": 2, "обновлено": "2026-10-26T08:00:00"}, "б": {"верно": 9, "обновлено": "2026-10-26T11:00:00"}, "в": {"верно": 1, "обновлено": "x"}}
    m = train.merge_progress(local, remote)
    assert m["а"]["верно"] == 5 and m["б"]["верно"] == 9 and "в" in m


def test_progress_text_roundtrip_and_garbage():
    p = {"кибитка": {"верно": 1, "выучено": False, "обновлено": "t"}}
    assert train.load_progress_text(train.dump_progress(p)) == p
    for bad in ("", "не json", "[1,2]", "null", '{"a": 5}'):
        assert train.load_progress_text(bad) == {}


def test_stats():
    p = {}
    train.set_learned(p, WORDS[0], True)
    train.record_answer(p, WORDS[1], False)
    st = train.stats(WORDS, p)
    assert st["всего"] == len(WORDS) and st["выучено"] == 1 and st["в работе"] == 1 and st["шатких"] == 1
    assert st["новых"] == len(WORDS) - 2


def test_pick_skips_learned_and_has_no_repeats():
    p = {}
    for w in WORDS[:3]:
        train.set_learned(p, w, True)
    got = train.pick_words(WORDS, p, 10, random.Random(1))
    assert {w["слово"] for w in got}.isdisjoint({w["слово"] for w in WORDS[:3]})
    assert len(got) == len(set(w["слово"] for w in got)) == len(WORDS) - 3
    assert len(train.pick_words(WORDS, p, 10, random.Random(1), include_learned=True)) == len(WORDS)
    assert len(train.pick_words(WORDS, {}, 2, random.Random(1))) == 2
    assert train.pick_words([], {}, 5) == []


def test_pick_prefers_difficult_words():
    hard, easy = WORDS[0], WORDS[1]
    p = {}
    for _ in range(5):
        train.record_answer(p, hard, False, D1)
    train.record_answer(p, easy, True, D1)
    train.record_answer(p, easy, True, D1)
    two = [hard, easy]
    wins = sum(train.pick_words(two, p, 1, random.Random(s), today=D1)[0] is hard for s in range(400))
    assert wins > 250, wins                      # ошибочное слово выпадает заметно чаще (≈ 4:1)
    fresh = sum(train.pick_words([hard, WORDS[2]], {train.key_of(hard): p[train.key_of(hard)]}, 1, random.Random(s), today=D1)[0] is WORDS[2] for s in range(400))
    assert fresh > 100                           # новые слова тоже не забыты


def test_blank_and_mark_quote():
    assert train.blank_quote("байковый", "Гаврила Гаврилович в колпаке и байковой куртке") == "Гаврила Гаврилович в колпаке и _____ куртке"
    assert train.blank_quote("капитан-исправник", "сын капитан-исправника, и ещё") == "сын _____, и ещё"
    assert train.blank_quote("ёлка", "Под Елкой") == "Под _____"
    assert train.blank_quote("кибитка", "нет такого") is None
    assert train.blank_quote("кибитка", "") is None
    assert train.mark_quote("шлафорка", "Прасковья Петровна в шлафорке на вате") == "Прасковья Петровна в **шлафорке** на вате"
    assert train.mark_quote("шлафорка", "ничего") == "ничего"
    # слово не должно «съедаться» внутри другого слова
    assert train.blank_quote("лес", "вылесить и лес") == "вылесить и _____"


def test_quiz_options_and_directions():
    rng = random.Random(3)
    for direction, field in ((train.DIRECTIONS[0], "значение"), (train.DIRECTIONS[1], "слово")):
        qs = train.make_quiz(WORDS, WORDS, direction, rng)
        assert len(qs) == len(WORDS)
        for q in qs:
            opts = q["варианты"]
            assert len(opts) == 4 and len(set(opts)) == 4
            assert opts[q["верный"]] == q["слово"][field]
    two = train.make_quiz(WORDS[:2], WORDS[:2], train.DIRECTIONS[0], rng)
    assert all(len(q["варианты"]) == 2 for q in two)
    assert train.make_quiz(WORDS[:1], WORDS[:1], train.DIRECTIONS[0], rng) == []   # одному слову не из чего выбирать
    # одинаковые значения у разных слов не дают двух «верных» вариантов
    twin = [dict(WORDS[0]), dict(WORDS[1], значение=WORDS[0]["значение"]), WORDS[2]]
    for q in train.make_quiz(twin, twin, train.DIRECTIONS[0], rng):
        assert len(set(q["варианты"])) == len(q["варианты"])


def test_save_and_load_progress_with_merge_and_conflict():
    repo = FakeRepo({})
    assert store.load_progress(repo) == {}
    a = {}
    train.record_answer(a, "кибитка", True, D1, "2026-10-26T10:00:00")
    store.save_progress(repo, a)
    # другое устройство успело записать своё слово
    b = {}
    train.record_answer(b, "землемер", False, D1, "2026-10-26T11:00:00")
    merged = store.save_progress(repo, b)
    assert set(merged) == {"кибитка", "землемер"} and set(store.load_progress(repo)) == {"кибитка", "землемер"}
    # конфликт версий при записи повторяется
    repo.conflicts = 0
    class Racy(FakeRepo):
        left = 1
        def put_file(self, path, content, message, sha=None):
            if self.left:
                self.left -= 1
                raise store.ConflictError()
            return super().put_file(path, content, message, sha)
    racy = Racy({})
    store.save_progress(racy, a)
    assert "кибитка" in store.load_progress(racy)


class BranchHttp:
    def __init__(self, existing):
        self.existing, self.calls = existing, []

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        name = url.rsplit("/", 1)[-1]
        if name in self.existing:
            return Resp(200, {"object": {"sha": "abc123"}})
        return Resp(404)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw["json"]))
        return Resp(201)


def test_ensure_branch_creates_only_when_missing():
    http = BranchHttp({"main"})
    gh = store.GitHubRepo("me/repo", "t", "main", http=http)
    gh.ensure_branch("progress")
    assert http.calls[-1] == ("POST", "https://api.github.com/repos/me/repo/git/refs", {"ref": "refs/heads/progress", "sha": "abc123"})
    http2 = BranchHttp({"main", "progress"})
    store.GitHubRepo("me/repo", "t", "main", http=http2).ensure_branch("progress")
    assert [c[0] for c in http2.calls] == ["GET"]               # ветка есть, ничего не создаём
    pr = store.progress_repo(store.GitHubRepo("me/repo", "t", "main", http=BranchHttp({"main", "progress"})))
    assert pr.branch == "progress" and pr.repo == "me/repo"
    bad = store.GitHubRepo("me/repo", "t", "main", http=BranchHttp(set()))
    assert isinstance(_raises(lambda: bad.ensure_branch("progress")), store.StoreError)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"Все проверки пройдены: {len(tests)}")
