"""Словарь прочитанного: личный словарь незнакомых и старых слов из книг."""
from html import escape
from pathlib import Path

import streamlit as st

from utils import capitalize_first, filter_words, load_words, sort_words, unique_values, word_of_day

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


def show_image(word: dict):
    source = image_source(word["картинка"])
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


def show_word(word: dict):
    """Карточка слова: слева картинка, справа текст."""
    with st.container(border=True):
        left, right = st.columns([1, 2])
        with left:
            show_image(word)
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


# ---------- данные ----------
words, problems = get_words(WORDS_FILE.stat().st_mtime if WORDS_FILE.exists() else 0.0)

st.title("📖 Словарь прочитанного")
st.caption(f"Слов в словаре: {len(words)}")
for problem in problems:
    st.warning(problem)

if not words:
    st.info("Словарь пока пуст. Добавь слова в файл words.yaml.")
    st.stop()

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
