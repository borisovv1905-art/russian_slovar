"""Словарь прочитанного: личный словарь незнакомых и старых слов из книг."""
from __future__ import annotations

import random
from html import escape
from pathlib import Path

import streamlit as st

import card
import export
import lookup
import store
import train
import utils
from utils import (capitalize_first, filter_words, load_reviews, load_words, norm, sort_words, split_tags, unique_tags,
                   unique_values, word_of_day)

BASE = Path(__file__).resolve().parent
WORDS_FILE = BASE / "words.yaml"
REVIEWS_FILE = BASE / "reviews.yaml"

st.set_page_config(page_title="Словарь прочитанного", page_icon="📖", layout="wide")


@st.cache_data
def get_words(file_version: float):
    """Читает файл заново только тогда, когда он изменился (file_version — время правки)."""
    return load_words(WORDS_FILE)


@st.cache_data
def get_reviews(file_version: float):
    return load_reviews(REVIEWS_FILE)


def image_bytes_from_repo(path_text: str) -> bytes | None:
    """Файл картинки из папки проекта (для карточки и выгрузки) или None."""
    source = image_source(path_text)
    if source and not source.startswith("http"):
        return Path(source).read_bytes()
    return None


def image_source(path_text: str):
    """Путь к картинке для показа или None, если картинки нет."""
    if not path_text:
        return None
    if path_text.startswith(("http://", "https://")):
        return path_text
    candidate = (BASE / path_text).resolve()
    # Картинки берём только из папки проекта.
    if BASE in candidate.parents and candidate.is_file():
        return str(candidate)
    return None


def show_image(word: dict, uploaded: bytes | None = None):
    source = uploaded or image_source(word["картинка"])
    if source:
        st.image(source, use_container_width=True)
    else:
        letter = escape(word["слово"][:1].upper())
        st.markdown(
            f"""<div style="aspect-ratio: 4 / 3; display: flex; align-items: center;
            justify-content: center; border-radius: 12px; font-size: 4rem;
            background: rgba(128,128,128,0.15); color: rgba(128,128,128,0.8);">{letter}</div>""",
            unsafe_allow_html=True,
        )
    if word["картинка_источник"]:
        st.caption(word["картинка_источник"])


def show_word(word: dict, uploaded: bytes | None = None, learned: bool = False, review_url: str = ""):
    """Карточка слова: слева картинка, справа текст."""
    with st.container(border=True):
        left, right = st.columns([1, 2])
        with left:
            show_image(word, uploaded)
        with right:
            title = f"### {capitalize_first(word['слово'])}"
            if word["пометка"]:
                title += f" &nbsp; :gray[{word['пометка']}]"
            if learned:
                title += " &nbsp; :green[✅ выучено]"
            st.markdown(title)
            if word.get("теги"):
                st.caption("🏷 " + ", ".join(split_tags(word["теги"])))
            st.write(word["значение"])
            if word["цитата"]:
                source = f"\n>\n> — *{word['произведение']}*" if word["произведение"] else ""
                st.markdown(f"> «{word['цитата']}»{source}")
            elif word["произведение"]:
                st.caption(word["произведение"])
            if review_url:
                st.markdown(f"[📝 Рецензия в канале «Второе чтение»]({review_url})")


# ---------- настройки (Secrets) ----------
def secret(name: str, default: str = "") -> str:
    """Значение из Secrets приложения; если секретов нет вообще, возвращает default."""
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # файла секретов нет (локальный запуск) или он не читается
        return default


COMMON_LABELS = ["устар.", "историзм", "разг.", "книжн.", "диал."]
NO_LABEL, NO_WORK, OTHER_WORK = "— без пометки —", "— не указывать —", "➕ Другое произведение…"
MAX_PASSWORD_FAILS = 5


def login_ok(where: str) -> bool:
    """Пароль для вкладок добавления и правки. True, если вход выполнен."""
    password, token = secret("ADD_PASSWORD"), secret("GITHUB_TOKEN")
    if not password or not token:
        st.info(
            "Изменение слов из приложения ещё не настроено. "
            "В настройках приложения (Settings → Secrets) нужны `ADD_PASSWORD` и `GITHUB_TOKEN`, "
            "подробности в README."
        )
        return False
    if st.session_state.get("add_ok"):
        return True
    fails = st.session_state.get("pw_fails", 0)
    if fails >= MAX_PASSWORD_FAILS:
        st.error("Слишком много неверных попыток. Обнови страницу и попробуй снова.")
        return False
    with st.form(f"login_{where}"):
        entered = st.text_input("Пароль", type="password", key=f"pw_{where}")
        if st.form_submit_button("Войти"):
            if store.check_password(entered, password):
                st.session_state["add_ok"] = True
                st.session_state["pw_fails"] = 0
                st.rerun()
            else:
                st.session_state["pw_fails"] = fails + 1
                st.error("Неверный пароль.")
    return False


def get_repo() -> store.GitHubRepo:
    return store.GitHubRepo(
        secret("GITHUB_REPO", "borisovv1905-art/russian_slovar"), secret("GITHUB_TOKEN"), secret("GITHUB_BRANCH", "main")
    )


def run_save(action, success_text: str) -> bool:
    """Выполняет сохранение в GitHub с понятными сообщениями об ошибках."""
    try:
        with st.spinner("Сохраняю в GitHub…"):
            action()
    except store.StoreError as exc:
        st.error(str(exc))
        return False
    except Exception:  # сеть и прочее непредвиденное: подробности токена не показываем
        st.error("Не получилось связаться с GitHub. Проверь интернет и попробуй ещё раз.")
        return False
    st.session_state["flash"] = success_text
    st.session_state["form_n"] = st.session_state.get("form_n", 0) + 1
    return True


def suggest_into_form(word_key: str, meaning_key: str, label_key: str, label_options: list[str]):
    """Нажатие «Подсказать значение»: черновик значения и пометки из Викисловаря (правится руками)."""
    senses = lookup.suggest_meaning(st.session_state.get(word_key, ""))
    st.session_state["suggest_senses"] = senses
    if senses:
        st.session_state[meaning_key] = senses[0]["text"]
        for lab in senses[0]["labels"]:
            if lab in label_options:
                st.session_state[label_key] = lab
                break


def entry_form(words: list[dict], prefix: str, defaults: dict | None = None):
    """Поля слова. Возвращает (запись или None, текст проблемы, картинка-байты, убрать ли картинку)."""
    d = defaults or {}
    key = lambda name: f"{prefix}_{name}"  # noqa: E731

    word = st.text_input("Слово", key=key("w"), value=d.get("слово", ""), placeholder="например: шлафорка")
    taken = {norm(w["слово"]) for w in words if norm(w["слово"]) != norm(d.get("слово", ""))}
    if word and norm(word) in taken:
        st.warning("Такое слово уже есть в словаре.")

    label_options = [NO_LABEL] + sorted(set(unique_values(words, "пометка")) | set(COMMON_LABELS) | ({d["пометка"]} if d.get("пометка") else set()), key=norm)
    if not d:
        st.button("🔎 Подсказать значение из Викисловаря", key=key("sg"), on_click=suggest_into_form,
                  args=(key("w"), key("m"), key("l"), label_options))
        senses = st.session_state.get("suggest_senses")
        if senses:
            others = [s["text"] for s in senses[1:]]
            st.caption("Подставил первое значение, проверь и поправь." + (" Другие значения: " + "; ".join(others) if others else ""))
        elif senses is not None and word:
            st.caption("В Викисловаре ничего не нашлось (или сайт не ответил). Впиши значение сам.")
    meaning = st.text_area("Значение", key=key("m"), value=d.get("значение", ""), height=90)

    col_label, col_work = st.columns(2)
    with col_label:
        label = st.selectbox("Пометка", label_options, key=key("l"),
                             index=label_options.index(d["пометка"]) if d.get("пометка") in label_options else 0)
    with col_work:
        fresh = {w["произведение"] for w in st.session_state.get("added", []) if w["произведение"]}
        works = [NO_WORK] + sorted(set(unique_values(words, "произведение")) | fresh, key=norm) + [OTHER_WORK]
        preferred = d.get("произведение") or st.session_state.get("last_work", "")
        chosen_work = st.selectbox("Произведение", works, key=key("p"), index=works.index(preferred) if preferred in works else 0)
    work = ""
    if chosen_work == OTHER_WORK:
        c1, c2 = st.columns(2)
        title = c1.text_input("Название произведения", key=key("t"), placeholder="Станционный смотритель")
        author = c2.text_input("Автор", key=key("a"), placeholder="А. С. Пушкин")
        if title:
            work = f"«{title.strip().strip('«»')}»" + (f", {author.strip()}" if author.strip() else "")
    elif chosen_work != NO_WORK:
        work = chosen_work

    tags_text = st.text_input("Теги (через запятую)", key=key("tg"), value=d.get("теги", ""), placeholder="например: одежда, быт")
    existing_tags = unique_tags(words)
    if existing_tags:
        st.caption("Уже есть: " + ", ".join(existing_tags[:30]))

    quote = st.text_area("Цитата с этим словом (без кавычек)", key=key("q"), value=d.get("цитата", ""), height=70)
    clean_q = store.clean_quote(quote)
    if word and clean_q and not lookup.quote_has_word(word, clean_q):
        st.caption("⚠️ Слова «" + word.strip() + "» в цитате не видно. Если оно в другой форме, это нормально, но проверь, ту ли цитату вставил.")
    if st.button("📚 Проверить цитату по Викитеке", key=key("cq"), disabled=len(clean_q.split()) < 3):
        hits = lookup.search_wikisource(clean_q)
        if hits:
            st.success("Цитата нашлась: " + "; ".join(f"[{h['title']}]({h['url']})" for h in hits))
            if hits[0]["snippet"]:
                st.caption("…" + hits[0]["snippet"] + "…")
        else:
            st.info("В Викитеке такой цитаты не нашлось. Возможно, другая орфография или издание, "
                    "поэтому сверь с книгой. Это только подсказка.")

    current_image = d.get("картинка", "")
    remove_image = False
    if current_image:
        remove_image = st.checkbox("Убрать картинку", key=key("rm"))
    image_file = st.file_uploader(
        "Новая картинка (необязательно): JPG, PNG или WEBP" if current_image else "Картинка (необязательно): JPG, PNG или WEBP",
        type=["jpg", "jpeg", "png", "webp"], key=key("f"),
    )
    image_bytes = image_file.getvalue() if image_file else None
    image_source_text = ""
    if image_bytes or (current_image and not remove_image):
        image_source_text = st.text_input("Откуда картинка (автор, лицензия, ссылка)", key=key("s"), value=d.get("картинка_источник", ""))

    try:
        entry = store.build_entry(
            word=word, meaning=meaning, label="" if label == NO_LABEL else label, work=work, quote=quote, tags=tags_text,
            image_path="" if (remove_image or image_bytes) else current_image, image_source=image_source_text,
            added=None,
        )
        if d.get("добавлено"):
            entry["добавлено"] = d["добавлено"]
        problem = ""
    except store.StoreError as exc:
        entry, problem = None, str(exc)
    return entry, problem, image_bytes, remove_image


def show_flash():
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)


def add_tab(words: list[dict]):
    """Вкладка «Добавить слово»."""
    if not login_ok("add"):
        return
    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.caption("Новое слово сохранится в GitHub, а в словаре появится через минуту-две, когда приложение обновится.")
    with top_right:
        if st.button("Выйти"):
            st.session_state["add_ok"] = False
            st.rerun()
    show_flash()

    n = st.session_state.get("form_n", 0)  # меняется после сохранения: так поля очищаются
    entry, problem, image_bytes, _ = entry_form(words, f"add{n}")

    if entry:
        st.markdown("**Так слово будет выглядеть в словаре:**")
        show_word(dict(entry), uploaded=image_bytes)
    elif problem and any(st.session_state.get(f"add{n}_{f}") for f in ("w", "m")):
        st.caption(problem)

    if st.button("Сохранить слово", type="primary", disabled=entry is None):
        if run_save(lambda: store.add_word(get_repo(), entry, image_bytes),
                    f"Слово «{capitalize_first(entry['слово'])}» сохранено. Оно появится в словаре через минуту-две."):
            st.session_state.setdefault("added", []).append(entry)
            if entry["произведение"]:
                st.session_state["last_work"] = entry["произведение"]
            st.session_state["suggest_senses"] = None
            st.rerun()

    added = st.session_state.get("added", [])
    if added:
        st.divider()
        st.markdown("**Сохранено в этом сеансе** (пока приложение обновляется, в словаре этих слов может не быть):")
        st.write(", ".join(capitalize_first(w["слово"]) for w in added))


def edit_tab(words: list[dict]):
    """Вкладка «Править / удалить»."""
    if not login_ok("edit"):
        return
    show_flash()
    if not words:
        st.info("Пока нечего править: в словаре нет слов.")
        return
    names = [w["слово"] for w in sort_words(words, "az")]
    chosen = st.selectbox("Какое слово править", names, format_func=capitalize_first, key="edit_pick")
    old = next(w for w in words if w["слово"] == chosen)
    n = st.session_state.get("form_n", 0)
    st.caption("Правки сохранятся в GitHub и появятся в словаре через минуту-две.")

    entry, problem, image_bytes, remove_image = entry_form(words, f"edit{n}_{store.slugify(chosen)}", defaults=old)
    if entry:
        st.markdown("**Так слово будет выглядеть:**")
        show_word(dict(entry), uploaded=image_bytes)
    else:
        st.caption(problem)
    if st.button("Сохранить изменения", type="primary", disabled=entry is None):
        if run_save(lambda: store.update_word(get_repo(), old["слово"], entry, image_bytes, remove_image),
                    f"Изменения слова «{capitalize_first(entry['слово'])}» сохранены. В словаре они появятся через минуту-две."):
            st.rerun()

    with st.expander("📝 Ссылка на рецензию к произведению"):
        review_works = unique_values(words, "произведение")
        if not review_works:
            st.caption("Сначала нужны слова с указанным произведением.")
        else:
            rev_work = st.selectbox("Произведение", review_works, key="rev_work")
            rev_url = st.text_input("Ссылка на рецензию в канале (пусто: убрать ссылку)", key=f"rev_url_{store.slugify(rev_work)}",
                                    value=reviews.get(rev_work, ""), placeholder="https://t.me/имя_канала/12")
            if st.button("Сохранить ссылку", key="rev_save"):
                if run_save(lambda: store.set_review(get_repo(), rev_work, rev_url),
                            f"Ссылка на рецензию к «{rev_work}» сохранена. На карточках она появится через минуту-две."):
                    st.rerun()

    with st.expander("Удалить это слово"):
        st.warning(f"Слово «{capitalize_first(old['слово'])}» исчезнет из словаря. В истории GitHub его можно будет найти, но из приложения вернуть нельзя.")
        sure = st.checkbox("Да, удалить это слово", key=f"del_sure_{n}_{store.slugify(chosen)}")
        with_image = st.checkbox("Вместе с картинкой (если она больше нигде не нужна)", value=True, key=f"del_img_{n}_{store.slugify(chosen)}")
        if st.button("Удалить слово", disabled=not sure):
            if run_save(lambda: store.delete_word(get_repo(), old["слово"], with_image),
                        f"Слово «{capitalize_first(old['слово'])}» удалено. Из словаря оно пропадёт через минуту-две."):
                st.rerun()


# ---------- тренировка ----------
def ensure_progress() -> dict:
    """Прогресс тренировки: один раз за сеанс читается с GitHub (ветка progress), дальше живёт в сеансе."""
    if "progress" not in st.session_state:
        try:
            st.session_state["progress"] = store.load_progress(get_repo().with_branch(store.PROGRESS_BRANCH))
        except Exception:  # noqa: BLE001  нет сети или токен не подошёл: начинаем с пустого, при сохранении всё сольётся
            st.session_state["progress"] = {}
            st.warning("Не удалось прочитать сохранённый прогресс. Тренироваться можно, а при сохранении он объединится с тем, что лежит на GitHub.")
        st.session_state["progress_dirty"] = False
    return st.session_state["progress"]


def flush_progress() -> bool:
    """Сохраняет прогресс на GitHub (в отдельную ветку, приложение от этого не перезапускается)."""
    try:
        with st.spinner("Сохраняю прогресс…"):
            merged = store.save_progress(store.progress_repo(get_repo()), st.session_state["progress"])
        st.session_state["progress"] = merged
        st.session_state["progress_dirty"] = False
        return True
    except store.StoreError as exc:
        st.error(str(exc))
    except Exception:  # noqa: BLE001
        st.error("Не получилось связаться с GitHub, прогресс пока не сохранён. Попробуй ещё раз.")
    return False


def answer(round_: dict, word: dict, correct: bool):
    rec = train.record_answer(st.session_state["progress"], word, correct)
    st.session_state["progress_dirty"] = True
    round_["log"].append((word["слово"], correct))
    round_["just_learned"] = bool(correct and rec.get("выучено") and rec["серия"] == train.LEARNED_STREAK)


def front_side(word: dict, direction: str):
    """Лицевая сторона вопроса."""
    if direction == train.DIRECTIONS[0]:
        st.markdown(f"## {capitalize_first(word['слово'])}")
        if word["цитата"]:
            st.markdown(f"> «{train.mark_quote(word['слово'], word['цитата'])}»")
    else:
        st.markdown(f"#### {capitalize_first(word['значение'])}")
        blank = train.blank_quote(word["слово"], word["цитата"]) if word["цитата"] else None
        if blank:
            st.markdown(f"> «{blank}»")


def next_button(round_: dict, word: dict):
    left, right = st.columns(2)
    with left:
        if st.button("Дальше →", key=f"next_{round_['pos']}", type="primary"):
            round_["pos"] += 1
            round_["revealed"], round_["picked"] = False, None
            st.rerun()
    with right:
        if st.button("🎓 Выучено, больше не показывать", key=f"learn_{round_['pos']}"):
            train.set_learned(st.session_state["progress"], word, True)
            st.session_state["progress_dirty"] = True
            round_["pos"] += 1
            round_["revealed"], round_["picked"] = False, None
            st.rerun()


def play_round(round_: dict, words: list[dict]):
    total = len(round_["words"])
    if round_["pos"] >= total:
        right = sum(1 for _, ok in round_["log"] if ok)
        st.success(f"Раунд окончен: верно {right} из {total}.")
        wrong = [w for w, ok in round_["log"] if not ok]
        if wrong:
            st.write("Стоит повторить: " + ", ".join(capitalize_first(w) for w in wrong))
        if not round_.get("saved") and st.session_state.get("progress_dirty"):
            round_["saved"] = flush_progress()
        if round_.get("saved"):
            st.caption("Прогресс сохранён.")
        if st.button("Ещё раунд", type="primary"):
            st.session_state["train"] = None
            st.rerun()
        return

    pos = round_["pos"]
    word = round_["words"][pos]
    st.progress(pos / total, text=f"Слово {pos + 1} из {total}")
    with st.container(border=True):
        front_side(word, round_["direction"])

    if round_["mode"] == "Карточки":
        if not round_["revealed"]:
            if st.button("Показать ответ", key=f"show_{pos}", type="primary"):
                round_["revealed"] = True
                st.rerun()
            return
        show_word(word)
        left, right = st.columns(2)
        with left:
            if st.button("✅ Знал", key=f"yes_{pos}", type="primary"):
                answer(round_, word, True)
                round_["pos"] += 1
                round_["revealed"] = False
                st.rerun()
        with right:
            if st.button("❌ Не знал", key=f"no_{pos}"):
                answer(round_, word, False)
                round_["pos"] += 1
                round_["revealed"] = False
                st.rerun()
        return

    # викторина
    quiz = round_["quiz"][pos]
    if round_["picked"] is None:
        for i, option in enumerate(quiz["варианты"]):
            if st.button(option, key=f"opt_{pos}_{i}", use_container_width=True):
                round_["picked"] = i
                answer(round_, word, i == quiz["верный"])
                st.rerun()
        return
    ok = round_["picked"] == quiz["верный"]
    (st.success if ok else st.error)("Верно!" if ok else f"Не совсем. Правильный ответ: {quiz['варианты'][quiz['верный']]}")
    if round_.get("just_learned"):
        st.info("🎓 Три верных подряд: слово теперь считается выученным.")
    show_word(word)
    next_button(round_, word)


def train_tab(words: list[dict]):
    """Вкладка «Тренировка»: карточки и викторина с прогрессом."""
    if not login_ok("train"):
        return
    progress = ensure_progress()
    stats = train.stats(words, progress)
    if stats["всего"]:
        st.progress(stats["выучено"] / stats["всего"],
                    text=f"Выучено {stats['выучено']} из {stats['всего']} · в работе {stats['в работе']} · новых {stats['новых']}")
    if st.session_state.get("progress_dirty") and st.session_state.get("train") is None:
        st.warning("Есть несохранённый прогресс.")
        if st.button("Сохранить прогресс"):
            if flush_progress():
                st.rerun()

    round_ = st.session_state.get("train")
    if round_ is None:
        if len(words) < 1:
            st.info("В словаре пока нет слов для тренировки.")
            return
        mode = st.radio("Режим", ["Карточки", "Викторина"], horizontal=True, key="tr_mode")
        direction = st.radio("Что показывать", list(train.DIRECTIONS), horizontal=True, key="tr_dir")
        count = st.selectbox("Сколько слов в раунде", [5, 10, 15, 20], index=1, key="tr_count")
        review = st.checkbox("Включить выученные (повторение)", key="tr_review")
        quiz_blocked = mode == "Викторина" and len(words) < 2
        if quiz_blocked:
            st.info("Для викторины нужно хотя бы два слова.")
        if st.button("Начать", type="primary", disabled=quiz_blocked):
            rng = random.Random()
            picked = train.pick_words(words, progress, count, rng, include_learned=review)
            if not picked:
                st.info("Все слова выучены 🎉 Включи «повторение», чтобы пройтись по ним ещё раз.")
            else:
                quiz = train.make_quiz(words, picked, direction, rng) if mode == "Викторина" else None
                if quiz is not None:
                    picked = [q["слово"] for q in quiz]
                st.session_state["train"] = {"mode": mode, "direction": direction, "words": picked, "quiz": quiz,
                                             "pos": 0, "revealed": False, "picked": None, "log": []}
                st.rerun()
    else:
        play_round(round_, words)
        if round_["pos"] < len(round_["words"]) and st.button("Закончить раунд", key="stop_round"):
            if st.session_state.get("progress_dirty"):
                flush_progress()
            st.session_state["train"] = None
            st.rerun()

    learned = [w for w in words if train.is_learned(progress, w)]
    if learned:
        with st.expander(f"Выученные слова ({len(learned)})"):
            for w in sort_words(learned, "az"):
                c1, c2 = st.columns([3, 1])
                c1.write(capitalize_first(w["слово"]))
                if c2.button("Вернуть в изучение", key=f"unlearn_{train.key_of(w)}"):
                    train.set_learned(progress, w, False)
                    st.session_state["progress_dirty"] = True
                    st.rerun()


# ---------- оформление ----------
FONTS = {
    "serif": ("Как в теме (с засечками)", None),
    "georgia": ("Georgia (для чтения)", "Georgia, 'Times New Roman', serif"),
    "sans": ("Без засечек", "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"),
    "mono": ("Моноширинный", "'Courier New', Courier, monospace"),
}
SIZES = {"s": ("Мелкий", 90), "m": ("Обычный", 100), "l": ("Крупный", 115), "xl": ("Очень крупный", 130)}


def appearance():
    """Шрифт и размер текста. Выбор хранится в адресе страницы (?font=…&size=…), поэтому он запоминается закладкой."""
    params = st.query_params
    font_code = params.get("font", "serif")
    size_code = params.get("size", "m")
    font_code = font_code if font_code in FONTS else "serif"
    size_code = size_code if size_code in SIZES else "m"
    with st.sidebar.expander("🎨 Оформление"):
        font = st.selectbox("Шрифт", list(FONTS), index=list(FONTS).index(font_code), format_func=lambda c: FONTS[c][0], key="ui_font")
        size = st.selectbox("Размер текста", list(SIZES), index=list(SIZES).index(size_code), format_func=lambda c: SIZES[c][0], key="ui_size")
        st.caption("Тёмная тема: меню ⋮ вверху справа → Settings → Theme. Шрифт и размер запоминаются в адресе страницы, "
                   "добавь её в закладки уже с выбранными настройками.")
    if font != font_code:
        params["font"] = font
    if size != size_code:
        params["size"] = size
    css = f"html {{ font-size: {SIZES[size][1]}%; }}"
    family = FONTS[font][1]
    if family:
        css += (".stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button, "
                ".stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, "
                f".stApp [data-testid='stMarkdownContainer'] {{ font-family: {family} !important; }}")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ---------- полка и статистика ----------
def shelf_tab(words: list[dict], progress, reviews: dict):
    if not words:
        st.info("Пока пусто: добавь первые слова.")
        return
    info = utils.summary(words)
    cols = st.columns(4)
    cols[0].metric("Слов", info["всего"])
    cols[1].metric("Произведений", info["произведений"])
    cols[2].metric("За неделю", info["за неделю"])
    cols[3].metric("За месяц", info["за месяц"])

    st.subheader("Книжная полка")
    order = st.radio("Порядок", ["Больше слов выше", "По алфавиту"], horizontal=True, key="shelf_order")
    for title, items in utils.shelf(words, "count" if order == "Больше слов выше" else "az"):
        head = f"{title} · {len(items)}"
        if progress is not None:
            head += f" · выучено {sum(1 for w in items if train.is_learned(progress, w))}/{len(items)}"
        with st.expander(head):
            url = reviews.get(title)
            if url:
                st.markdown(f"[📝 Рецензия в канале «Второе чтение»]({url})")
            for w in items:
                line = f"**{capitalize_first(w['слово'])}**"
                if w["пометка"]:
                    line += f" · :gray[{w['пометка']}]"
                st.markdown(f"{line} — {w['значение']}")
                if w["теги"]:
                    st.caption("🏷 " + ", ".join(split_tags(w["теги"])))

    st.subheader("Статистика")
    import pandas as pd

    weekly = utils.words_per_week(words)
    st.markdown("**Сколько слов добавлено по неделям** (последние 12, неделя с понедельника)")
    st.bar_chart(pd.Series({d.strftime("%d.%m"): n for d, n in weekly}, name="слов"))

    def bars(title: str, counts: dict):
        if not counts:
            return
        st.markdown(f"**{title}**")
        top = max(counts.values())
        for name, n in list(counts.items())[:15]:
            st.progress(n / top, text=f"{name} · {n}")

    bars("По произведениям", utils.count_by(words, "произведение"))
    bars("По пометкам", utils.count_by(words, "пометка"))
    bars("По тегам", utils.count_tags(words))
    st.caption(f"С картинкой: {info['с картинкой']} из {info['всего']} · с цитатой: {info['с цитатой']} из {info['всего']}"
               + (f" · без даты добавления: {info['без даты']}" if info["без даты"] else ""))


# ---------- карточка для поста ----------
def post_tab(words: list[dict], reviews: dict):
    if not words:
        st.info("Пока пусто: добавь первые слова.")
        return
    names = [w["слово"] for w in sort_words(words, "az")]
    chosen = st.selectbox("Слово для поста", names, format_func=capitalize_first, key="post_pick")
    w = next(x for x in words if x["слово"] == chosen)
    try:
        png = card.render_card(w, image_bytes_from_repo(w["картинка"]))
    except FileNotFoundError as exc:
        st.error(str(exc))
        return
    st.image(png, use_container_width=True)
    st.download_button("⬇️ Скачать картинку (PNG)", png, file_name=f"{store.slugify(w['слово'])}.png", mime="image/png")
    text = card.post_text(w, reviews.get(w["произведение"], ""))
    st.markdown("**Текст поста** (справа вверху у блока есть кнопка «копировать»):")
    st.code(text, language=None)
    if len(text) > 1024:
        st.caption(f"В тексте {len(text)} знаков, а подпись под фото в Telegram ограничена 1024. Отправь картинку отдельно, а текст следом.")
    else:
        st.caption(f"{len(text)} знаков: влезает в подпись под фото (лимит Telegram 1024).")


# ---------- экспорт ----------
@st.cache_data
def build_html(words_version: float, reviews_version: float) -> str:
    ws, _ = get_words(words_version)
    return export.to_html(ws, image_loader=image_bytes_from_repo, reviews=get_reviews(reviews_version))


def export_tab(words: list[dict]):
    if not words:
        st.info("Пока пусто: добавь первые слова.")
        return
    st.download_button("📊 Таблица (CSV) для Excel и Google Таблиц", export.to_csv(words), file_name="slovar.csv", mime="text/csv")
    st.caption("Разделитель «;», кодировка UTF-8: в русском Excel открывается без «кракозябр».")
    version = WORDS_FILE.stat().st_mtime if WORDS_FILE.exists() else 0.0
    rev_version = REVIEWS_FILE.stat().st_mtime if REVIEWS_FILE.exists() else 0.0
    st.download_button("🖨 Страница для печати / PDF (HTML)", build_html(version, rev_version).encode("utf-8"),
                       file_name="slovar.html", mime="text/html")
    st.caption("Открой файл в браузере → Печать → «Сохранить как PDF». Картинки уже внутри файла.")
    if WORDS_FILE.exists():
        st.download_button("📄 Исходный файл words.yaml", WORDS_FILE.read_bytes(), file_name="words.yaml", mime="text/yaml")
        st.caption("Резервная копия всех слов в исходном виде.")


# ---------- данные ----------
words, problems = get_words(WORDS_FILE.stat().st_mtime if WORDS_FILE.exists() else 0.0)
reviews = get_reviews(REVIEWS_FILE.stat().st_mtime if REVIEWS_FILE.exists() else 0.0)

appearance()

st.title("📖 Словарь прочитанного")
st.caption(f"Слов в словаре: {len(words)}")
for problem in problems:
    st.warning(problem)

tab_dict, tab_shelf, tab_train, tab_post, tab_add, tab_edit, tab_export = st.tabs(
    ["📖 Словарь", "📚 Полка", "🎯 Тренировка", "🖼 Для поста", "➕ Добавить слово", "✏️ Править / удалить", "📤 Экспорт"]
)

with tab_add:
    add_tab(words)

with tab_edit:
    edit_tab(words)

with tab_train:
    train_tab(words)

# прогресс известен только после входа; без него словарь просто не показывает отметки «выучено»
progress = st.session_state.get("progress") if st.session_state.get("add_ok") else None

with tab_shelf:
    shelf_tab(words, progress, reviews)

with tab_post:
    post_tab(words, reviews)

with tab_export:
    export_tab(words)

with tab_dict:
    if not words:
        st.info("Словарь пока пуст. Добавь первое слово на вкладке «Добавить слово».")
    else:
        # ---------- фильтры ----------
        with st.sidebar:
            st.header("Поиск")
            query = st.text_input("Слово, значение или цитата")
            work = st.selectbox("Произведение", ["Все"] + unique_values(words, "произведение"))
            label = st.selectbox("Пометка", ["Все"] + unique_values(words, "пометка"))
            all_tags = unique_tags(words)
            chosen_tags = st.multiselect("Теги", all_tags) if all_tags else []
            order = st.radio("Порядок", ["По алфавиту", "Сначала новые"])
            hide_learned = st.checkbox("Скрыть выученные") if progress is not None else False

        # ---------- слово дня ----------
        if not query and work == "Все" and label == "Все" and not chosen_tags:
            today_word = word_of_day(words)
            if today_word:
                st.subheader("Слово дня")
                show_word(today_word, review_url=reviews.get(today_word["произведение"], ""))
                st.divider()

        # ---------- список ----------
        found = filter_words(
            words,
            query=query,
            work="" if work == "Все" else work,
            label="" if label == "Все" else label,
            tags=chosen_tags,
        )
        found = sort_words(found, "new" if order == "Сначала новые" else "az")
        if hide_learned:
            found = [w for w in found if not train.is_learned(progress, w)]

        st.subheader(f"Найдено: {len(found)}")
        if not found:
            st.info("Ничего не нашлось. Попробуй изменить запрос или сбросить фильтры.")
        for item in found:
            show_word(item, learned=progress is not None and train.is_learned(progress, item),
                      review_url=reviews.get(item["произведение"], ""))
