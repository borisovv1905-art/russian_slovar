"""Словарь прочитанного: личный словарь незнакомых и старых слов из книг."""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

import lookup
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
            word=word, meaning=meaning, label="" if label == NO_LABEL else label, work=work, quote=quote,
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

    with st.expander("Удалить это слово"):
        st.warning(f"Слово «{capitalize_first(old['слово'])}» исчезнет из словаря. В истории GitHub его можно будет найти, но из приложения вернуть нельзя.")
        sure = st.checkbox("Да, удалить это слово", key=f"del_sure_{n}_{store.slugify(chosen)}")
        with_image = st.checkbox("Вместе с картинкой (если она больше нигде не нужна)", value=True, key=f"del_img_{n}_{store.slugify(chosen)}")
        if st.button("Удалить слово", disabled=not sure):
            if run_save(lambda: store.delete_word(get_repo(), old["слово"], with_image),
                        f"Слово «{capitalize_first(old['слово'])}» удалено. Из словаря оно пропадёт через минуту-две."):
                st.rerun()


# ---------- данные ----------
words, problems = get_words(WORDS_FILE.stat().st_mtime if WORDS_FILE.exists() else 0.0)

st.title("📖 Словарь прочитанного")
st.caption(f"Слов в словаре: {len(words)}")
for problem in problems:
    st.warning(problem)

tab_dict, tab_add, tab_edit = st.tabs(["📖 Словарь", "➕ Добавить слово", "✏️ Править / удалить"])

with tab_add:
    add_tab(words)

with tab_edit:
    edit_tab(words)

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
