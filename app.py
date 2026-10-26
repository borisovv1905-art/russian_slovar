"""Словарь прочитанного: личный словарь незнакомых и старых слов из книг."""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

import store
from utils import capitalize_first, filter_words, load_words, norm, sort_words, unique_values, word_of_day

BASE = Path(__file__).resolve().parent
WORDS_FILE = BASE / "words.yaml"

st.set_page_config(page_title="Словарь прочитанного", page_icon="📖", layout="wide")


@st.cache_data
def get_words(file_version: float):
    """Читает файл заново только тогда, когда он изменился (file_version — время правки)."""
    return load_words(WORDS_FILE)


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


def show_word(word: dict, uploaded: bytes | None = None):
    """Карточка слова: слева картинка, справа текст."""
    with st.container(border=True):
        left, right = st.columns([1, 2])
        with left:
            show_image(word, uploaded)
        with right:
            title = f"### {capitalize_first(word['слово'])}"
            if word["пометка"]:
                title += f" &nbsp; :gray[{word['пометка']}]"
            st.markdown(title)
            st.write(word["значение"])
            if word["цитата"]:
                source = f"\n>\n> — *{word['произведение']}*" if word["произведение"] else ""
                st.markdown(f"> «{word['цитата']}»{source}")
            elif word["произведение"]:
                st.caption(word["произведение"])


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


def add_tab(words: list[dict]):
    """Вкладка «Добавить слово»: пароль, форма, коммит в GitHub."""
    password, token = secret("ADD_PASSWORD"), secret("GITHUB_TOKEN")
    if not password or not token:
        st.info(
            "Добавление слов из приложения ещё не настроено. "
            "В настройках приложения (Settings → Secrets) нужны `ADD_PASSWORD` и `GITHUB_TOKEN`, "
            "подробности в README."
        )
        return

    # --- вход по паролю ---
    fails = st.session_state.get("pw_fails", 0)
    if not st.session_state.get("add_ok"):
        if fails >= MAX_PASSWORD_FAILS:
            st.error("Слишком много неверных попыток. Обнови страницу и попробуй снова.")
            return
        with st.form("login"):
            entered = st.text_input("Пароль", type="password")
            if st.form_submit_button("Войти"):
                if store.check_password(entered, password):
                    st.session_state["add_ok"] = True
                    st.session_state["pw_fails"] = 0
                    st.rerun()
                else:
                    st.session_state["pw_fails"] = fails + 1
                    st.error("Неверный пароль.")
        return

    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.caption("Новое слово сохранится в GitHub, а в словаре появится через минуту-две, когда приложение обновится.")
    with top_right:
        if st.button("Выйти"):
            st.session_state["add_ok"] = False
            st.rerun()

    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)

    n = st.session_state.get("form_n", 0)  # меняется после сохранения: так поля очищаются
    k = lambda name: f"{name}_{n}"  # noqa: E731

    word = st.text_input("Слово", key=k("w"), placeholder="например: шлафорка")
    if word and norm(word) in {norm(w["слово"]) for w in words}:
        st.warning("Такое слово уже есть в словаре.")
    meaning = st.text_area("Значение", key=k("m"), height=90)

    col_label, col_work = st.columns(2)
    with col_label:
        labels = [NO_LABEL] + sorted(set(unique_values(words, "пометка")) | set(COMMON_LABELS), key=norm)
        label = st.selectbox("Пометка", labels, key=k("l"))
    with col_work:
        works = [NO_WORK] + unique_values(words, "произведение") + [OTHER_WORK]
        chosen_work = st.selectbox("Произведение", works, key=k("p"))
    work = ""
    if chosen_work == OTHER_WORK:
        c1, c2 = st.columns(2)
        title = c1.text_input("Название произведения", key=k("t"), placeholder="Станционный смотритель")
        author = c2.text_input("Автор", key=k("a"), placeholder="А. С. Пушкин")
        if title:
            work = f"«{title.strip().strip('«»')}»" + (f", {author.strip()}" if author.strip() else "")
    elif chosen_work != NO_WORK:
        work = chosen_work

    quote = st.text_area("Цитата с этим словом (без кавычек)", key=k("q"), height=70)

    image_file = st.file_uploader("Картинка (необязательно): JPG, PNG или WEBP", type=["jpg", "jpeg", "png", "webp"], key=k("f"))
    image_bytes = image_file.getvalue() if image_file else None
    image_source_text = ""
    if image_bytes:
        image_source_text = st.text_input("Откуда картинка (автор, лицензия, ссылка)", key=k("s"))

    try:
        preview = store.build_entry(word=word, meaning=meaning, label="" if label == NO_LABEL else label,
                                    work=work, quote=quote, image_source=image_source_text)
        problem = ""
    except store.StoreError as exc:
        preview, problem = None, str(exc)

    if preview:
        st.markdown("**Так слово будет выглядеть в словаре:**")
        shown = {k_: preview[k_] for k_ in preview}
        show_word(shown, uploaded=image_bytes)
    elif word or meaning:
        st.caption(problem)

    if st.button("Сохранить слово", type="primary", disabled=preview is None):
        try:
            with st.spinner("Сохраняю в GitHub…"):
                repo = store.GitHubRepo(
                    secret("GITHUB_REPO", "borisovv1905-art/russian_slovar"), token, secret("GITHUB_BRANCH", "main")
                )
                saved = store.add_word(repo, preview, image_bytes)
        except store.StoreError as exc:
            st.error(str(exc))
        except Exception:  # сеть и прочее непредвиденное: подробности токена не показываем
            st.error("Не получилось связаться с GitHub. Проверь интернет и попробуй ещё раз.")
        else:
            st.session_state.setdefault("added", []).append(saved)
            st.session_state["flash"] = (
                f"Слово «{capitalize_first(saved['слово'])}» сохранено. Оно появится в словаре через минуту-две."
            )
            st.session_state["form_n"] = n + 1
            st.rerun()

    added = st.session_state.get("added", [])
    if added:
        st.divider()
        st.markdown("**Сохранено в этом сеансе** (пока приложение обновляется, в словаре этих слов может не быть):")
        st.write(", ".join(capitalize_first(w["слово"]) for w in added))


# ---------- данные ----------
words, problems = get_words(WORDS_FILE.stat().st_mtime if WORDS_FILE.exists() else 0.0)

st.title("📖 Словарь прочитанного")
st.caption(f"Слов в словаре: {len(words)}")
for problem in problems:
    st.warning(problem)

tab_dict, tab_add = st.tabs(["📖 Словарь", "➕ Добавить слово"])

with tab_add:
    add_tab(words)

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
            order = st.radio("Порядок", ["По алфавиту", "Сначала новые"])

        # ---------- слово дня ----------
        if not query and work == "Все" and label == "Все":
            today_word = word_of_day(words)
            if today_word:
                st.subheader("Слово дня")
                show_word(today_word)
                st.divider()

        # ---------- список ----------
        found = filter_words(
            words,
            query=query,
            work="" if work == "Все" else work,
            label="" if label == "Все" else label,
        )
        found = sort_words(found, "new" if order == "Сначала новые" else "az")

        st.subheader(f"Найдено: {len(found)}")
        if not found:
            st.info("Ничего не нашлось. Попробуй изменить запрос или сбросить фильтры.")
        for item in found:
            show_word(item)
