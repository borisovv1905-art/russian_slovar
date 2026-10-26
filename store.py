"""Сохранение нового слова в GitHub-репозиторий (без Streamlit, чтобы проверять тестами).

Приложение на Streamlit Cloud не может надёжно писать в свои файлы: диск там временный.
Поэтому новое слово и картинка отправляются коммитом в репозиторий через GitHub API,
а Streamlit сам подхватывает изменение и перезапускает приложение.
"""
from __future__ import annotations

import base64
import hmac
import io
import json
import re
from datetime import date, datetime, timedelta, timezone

from PIL import Image

from utils import FIELDS, norm, parse_words

API = "https://api.github.com"
WORDS_PATH = "words.yaml"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_WIDTH = 900
LIMITS = {"слово": 60, "значение": 700, "пометка": 40, "произведение": 150, "цитата": 700, "картинка_источник": 200}

_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
     "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))


class StoreError(Exception):
    """Ошибка, текст которой можно показать пользователю."""


def today_local() -> date:
    """Сегодняшняя дата по самарскому времени (UTC+4)."""
    return datetime.now(timezone(timedelta(hours=4))).date()


def check_password(entered: str, expected: str) -> bool:
    """Сравнение пароля без утечки по времени. Пустой пароль не принимается никогда."""
    if not expected or not entered:
        return False
    return hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def slugify(text: str) -> str:
    """«Кибитка» → «kibitka»: имя файла картинки латиницей."""
    out = "".join(_TRANSLIT.get(ch, ch) for ch in norm(text))
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out[:40] or "word"


def clean_text(text: str) -> str:
    """Убирает лишние пробелы и переводы строк (запись остаётся в одну строку)."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_quote(text: str) -> str:
    """Цитату храним без внешних кавычек: приложение ставит «ёлочки» само."""
    t = clean_text(text)
    while len(t) >= 2 and ((t[0], t[-1]) in {("«", "»"), ('"', '"'), ("“", "”")}):
        t = t[1:-1].strip()
    return t


def build_entry(*, word, meaning, label="", work="", quote="", image_path="", image_source="", added=None) -> dict:
    """Собирает запись, проверяет обязательные поля и длины."""
    entry = {
        "слово": clean_text(word),
        "значение": clean_text(meaning),
        "пометка": clean_text(label),
        "произведение": clean_text(work),
        "цитата": clean_quote(quote),
        "картинка": image_path,
        "картинка_источник": clean_text(image_source),
        "добавлено": (added or today_local()).isoformat(),
    }
    if not entry["слово"]:
        raise StoreError("Впиши слово.")
    if not entry["значение"]:
        raise StoreError("Впиши значение слова.")
    for key, limit in LIMITS.items():
        if len(entry[key]) > limit:
            raise StoreError(f"Поле «{key}» слишком длинное: {len(entry[key])} знаков, можно не больше {limit}.")
    return entry


def format_entry(entry: dict) -> str:
    """Запись в формате words.yaml. Строки в двойных кавычках (json даёт верное экранирование)."""
    lines = []
    for i, key in enumerate(FIELDS):
        value = entry.get(key, "")
        if value in ("", None):
            continue
        prefix = "- " if not lines else "  "
        if key == "добавлено":
            text = str(value)
        else:
            text = json.dumps(str(value), ensure_ascii=False)
        lines.append(f"{prefix}{key}: {text}")
    return "\n".join(lines) + "\n"


def append_entry(yaml_text: str, entry: dict) -> str:
    """Добавляет запись в конец файла, комментарии и остальное не трогает. Проверяет результат."""
    existing, _ = parse_words(yaml_text)
    if norm(entry["слово"]) in {norm(w["слово"]) for w in existing}:
        raise StoreError(f"Слово «{entry['слово']}» уже есть в словаре.")
    base = yaml_text if yaml_text.endswith("\n") else yaml_text + "\n"
    result = base + "\n" + format_entry(entry)
    words, errors = parse_words(result)
    if errors or len(words) != len(existing) + 1 or words[-1]["слово"] != entry["слово"]:
        raise StoreError("Не получилось безопасно добавить слово: файл после правки не прошёл проверку.")
    return result


def prepare_image(data: bytes) -> bytes:
    """Проверяет, что это картинка, уменьшает до разумного размера, отдаёт JPEG."""
    if len(data) > MAX_IMAGE_BYTES:
        raise StoreError("Картинка больше 8 МБ. Уменьши её и попробуй снова.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # PIL бросает разные исключения на битые файлы
        raise StoreError("Не удалось открыть файл как картинку (нужны JPG, PNG или WEBP).") from exc
    if img.format not in {"JPEG", "PNG", "WEBP"}:
        raise StoreError("Подходят только JPG, PNG и WEBP.")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if img.width > MAX_IMAGE_WIDTH:
        img = img.resize((MAX_IMAGE_WIDTH, round(img.height * MAX_IMAGE_WIDTH / img.width)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=86, optimize=True)
    return out.getvalue()


class GitHubRepo:
    """Минимум GitHub API: прочитать файл и записать файл коммитом."""

    def __init__(self, repo: str, token: str, branch: str = "main", http=None):
        if not repo or "/" not in repo:
            raise StoreError("В настройках приложения не указан репозиторий (GITHUB_REPO, вида «владелец/репозиторий»).")
        if not token:
            raise StoreError("В настройках приложения нет GITHUB_TOKEN.")
        self.repo, self.branch = repo, branch
        self._token = token
        if http is None:
            import requests

            http = requests
        self.http = http

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _fail(self, resp, what: str):
        code = resp.status_code
        if code in (401, 403):
            raise StoreError(f"GitHub не принял токен ({what}). Проверь, что токен не истёк и у него есть доступ Contents: Read and write к этому репозиторию.")
        if code == 404:
            raise StoreError(f"GitHub не нашёл репозиторий или файл ({what}). Проверь GITHUB_REPO, ветку и права токена.")
        raise StoreError(f"GitHub ответил ошибкой {code} ({what}).")

    def get_file(self, path: str):
        """(содержимое в байтах, sha) или None, если файла нет."""
        resp = self.http.get(
            f"{API}/repos/{self.repo}/contents/{path}",
            headers=self._headers(), params={"ref": self.branch}, timeout=20,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            self._fail(resp, f"чтение {path}")
        data = resp.json()
        return base64.b64decode(data["content"]), data["sha"]

    def put_file(self, path: str, content: bytes, message: str, sha: str | None = None) -> None:
        body = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        resp = self.http.put(f"{API}/repos/{self.repo}/contents/{path}", headers=self._headers(), json=body, timeout=30)
        if resp.status_code in (200, 201):
            return
        if resp.status_code in (409, 422):
            raise ConflictError()
        self._fail(resp, f"запись {path}")

    def delete_file(self, path: str, message: str, sha: str) -> None:
        body = {"message": message, "sha": sha, "branch": self.branch}
        resp = self.http.request(
            "DELETE", f"{API}/repos/{self.repo}/contents/{path}", headers=self._headers(), json=body, timeout=30
        )
        if resp.status_code == 200:
            return
        if resp.status_code in (409, 422):
            raise ConflictError()
        self._fail(resp, f"удаление {path}")


class ConflictError(Exception):
    """Файл на GitHub успел измениться между чтением и записью."""


def _upload_image(repo, word: str, image_bytes: bytes) -> str:
    """Кладёт картинку в images/, не затирая чужие файлы. Возвращает путь в репозитории."""
    jpeg = prepare_image(image_bytes)
    base = f"images/{slugify(word)}"
    path, n = f"{base}.jpg", 2
    while repo.get_file(path) is not None:
        path, n = f"{base}-{n}.jpg", n + 1
    repo.put_file(path, jpeg, f"Картинка к слову «{word}»")
    return path


def _commit_words(repo, transform, message: str, attempts: int = 3):
    """Читает свежий words.yaml, применяет transform(text) → (новый_текст, результат), коммитит.

    При конфликте версий (файл изменился между чтением и записью) повторяет с новым текстом.
    """
    for _ in range(attempts):
        current = repo.get_file(WORDS_PATH)
        if current is None:
            raise StoreError("В репозитории не найден words.yaml. Проверь GITHUB_REPO, ветку и права токена.")
        text, sha = current[0].decode("utf-8"), current[1]
        new_text, result = transform(text)
        try:
            repo.put_file(WORDS_PATH, new_text.encode("utf-8"), message, sha)
            return result
        except ConflictError:
            continue
    raise StoreError("Файл со словами всё время менялся, сохранить не получилось. Попробуй ещё раз.")


def add_word(repo, entry: dict, image_bytes: bytes | None = None, attempts: int = 3) -> dict:
    """Сохраняет слово (и картинку) в репозиторий. Возвращает записанную запись.

    repo — объект с методами get_file / put_file (GitHubRepo или подставной в тестах).
    """
    entry = dict(entry)
    if image_bytes:
        entry["картинка"] = _upload_image(repo, entry["слово"], image_bytes)
    return _commit_words(repo, lambda text: (append_entry(text, entry), entry), f"Добавлено слово: {entry['слово']}", attempts)


# ---------- правка и удаление ----------

_ENTRY_LINE = re.compile(r"^- ", re.M)


def _blocks(text: str):
    """Делит файл на (начало, [(тело записи, хвост из пустых строк и комментариев)])."""
    starts = [m.start() for m in _ENTRY_LINE.finditer(text)]
    if not starts:
        return text, []
    head, blocks = text[: starts[0]], []
    for a, b in zip(starts, starts[1:] + [len(text)]):
        lines = text[a:b].splitlines(keepends=True)
        end = 0
        for idx, line in enumerate(lines):
            if idx == 0 or line.startswith("  "):
                end = idx + 1
        blocks.append(("".join(lines[:end]), "".join(lines[end:])))
    return head, blocks


def _locate(text: str, word: str):
    """(начало, [блоки], номер блока, запись-словарь) для слова или StoreError."""
    import yaml

    head, blocks = _blocks(text)
    for idx, (body, _tail) in enumerate(blocks):
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        if norm(item.get("слово", "")) == norm(word):
            return head, blocks, idx, {k: ("" if item.get(k) is None else str(item[k]).strip()) for k in FIELDS}
    raise StoreError(f"Слова «{word}» уже нет в файле на GitHub. Обнови страницу: возможно, его уже изменили или удалили.")


def _assemble(head, blocks) -> str:
    out = head + "".join(body + tail for body, tail in blocks)
    return out if out.endswith("\n") or not out else out + "\n"


def replace_entry(text: str, old_word: str, entry: dict):
    """Заменяет запись old_word новой. Возвращает (новый текст, старая запись)."""
    head, blocks, idx, old = _locate(text, old_word)
    others = {norm(w["слово"]) for w in parse_words(text)[0] if norm(w["слово"]) != norm(old_word)}
    if norm(entry["слово"]) in others:
        raise StoreError(f"Слово «{entry['слово']}» уже есть в словаре.")
    blocks[idx] = (format_entry(entry), blocks[idx][1])
    return _check_result(_assemble(head, blocks), len(blocks), entry["слово"]), old


def remove_entry(text: str, word: str):
    """Удаляет запись. Возвращает (новый текст, удалённая запись). Комментарии рядом остаются."""
    head, blocks, idx, old = _locate(text, word)
    _body, tail = blocks.pop(idx)
    if idx > 0:
        blocks[idx - 1] = (blocks[idx - 1][0], blocks[idx - 1][1] + tail)
    else:
        head += tail
    return _check_result(_assemble(head, blocks), len(blocks), None), old


def _check_result(new_text: str, expected_count: int, word):
    words, errors = parse_words(new_text)
    if errors or len(words) != expected_count or (word and norm(word) not in {norm(w["слово"]) for w in words}):
        raise StoreError("Не получилось безопасно изменить файл: после правки он не прошёл проверку. Ничего не записано.")
    return new_text


def _image_unused(text: str, path: str) -> bool:
    words, _ = parse_words(text)
    return all(w["картинка"] != path for w in words)


def _deletable_image(path: str) -> bool:
    return bool(path) and path.startswith("images/") and not path.startswith("images/src/") and ".." not in path


def _drop_image(repo, path: str, word: str) -> None:
    """Удаляет файл картинки (с запасом на ошибки: слово уже сохранено, лишний файл не страшен)."""
    try:
        current = repo.get_file(path)
        if current is not None:
            repo.delete_file(path, f"Удалена картинка слова «{word}»", current[1])
    except Exception:  # noqa: BLE001
        pass


def update_word(repo, old_word: str, entry: dict, image_bytes: bytes | None = None, remove_image: bool = False) -> dict:
    """Меняет слово. entry — новые поля (картинка: прежний путь или пусто). Возвращает записанную запись."""
    entry = dict(entry)
    new_path = _upload_image(repo, entry["слово"], image_bytes) if image_bytes else None
    if new_path:
        entry["картинка"] = new_path
    elif remove_image:
        entry["картинка"] = ""
        entry["картинка_источник"] = ""

    def transform(text):
        new_text, old = replace_entry(text, old_word, entry)
        return new_text, (new_text, old)

    new_text, old = _commit_words(repo, transform, f"Изменено слово: {entry['слово']}")
    if old["картинка"] != entry["картинка"] and _deletable_image(old["картинка"]) and _image_unused(new_text, old["картинка"]):
        _drop_image(repo, old["картинка"], entry["слово"])
    return entry


def delete_word(repo, word: str, delete_image: bool = True) -> dict:
    """Удаляет слово (и его картинку, если она больше нигде не нужна). Возвращает удалённую запись."""

    def transform(text):
        new_text, old = remove_entry(text, word)
        return new_text, (new_text, old)

    new_text, old = _commit_words(repo, transform, f"Удалено слово: {word}")
    if delete_image and _deletable_image(old["картинка"]) and _image_unused(new_text, old["картинка"]):
        _drop_image(repo, old["картинка"], word)
    return old
