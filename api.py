"""Учебный REST API для работы с пользователями (Flask + SQLite).

Эндпоинты:
    GET      /health          проверка работоспособности
    POST     /adduser         добавить пользователя: {"name": "..."}
    GET      /user/<id>       получить пользователя
    GET|POST /activate/<id>   отметить пользователя активным
    GET      /slow            запустить тяжёлую задачу в фоне
    GET      /wrong           пример обработки ошибки
"""
import logging
import os
import sqlite3
import threading
from collections import deque
from typing import Deque, List, Optional

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

DEFAULT_DB_PATH = os.environ.get("DB_PATH", "users.db")
MAX_ACTIVE_USERS = 5
MAX_NAME_LENGTH = 100
SLOW_TASK_ITERATIONS = 1_000_000
MAX_USER_ID = 2**63 - 1  # больше SQLite хранить не умеет

ERROR_MESSAGES = {
    404: "Ресурс не найден",
    405: "Метод не поддерживается для этого адреса",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("user_service")


class ActiveUsers:
    """Потокобезопасный список последних активных пользователей."""

    def __init__(self, limit: int) -> None:
        self._items: Deque[int] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def add(self, user_id: int) -> None:
        with self._lock:
            self._items.append(user_id)

    def snapshot(self) -> List[int]:
        with self._lock:
            return list(self._items)


def init_db(db_path: str) -> None:
    """Создаёт папку и таблицу пользователей, если их ещё нет."""
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        connection.commit()
    finally:
        connection.close()


def error_response(error: str, detail: str, status: int):
    """Единый формат ошибок: {"error": код, "detail": пояснение}."""
    return jsonify({"error": error, "detail": detail}), status


def run_slow_task(iterations: int) -> None:
    """Тяжёлое вычисление, которое выполняется в фоновом потоке."""
    total = 0
    for number in range(iterations):
        total += number * number
    logger.info("Фоновая задача завершена, результат: %s", total)


def create_app(db_path: Optional[str] = None) -> Flask:
    """Создаёт приложение. Путь к базе можно передать явно (например, для тестов)."""
    app = Flask(__name__)
    app.json.ensure_ascii = False  # русские буквы в JSON не превращаются в \uXXXX
    app.config["DB_PATH"] = db_path or DEFAULT_DB_PATH
    active_users = ActiveUsers(MAX_ACTIVE_USERS)
    init_db(app.config["DB_PATH"])

    def get_db() -> sqlite3.Connection:
        """Соединение с базой: одно на запрос, закрывается автоматически."""
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error: Optional[BaseException]) -> None:
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/adduser")
    def add_user():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error_response("invalid_json", 'Ожидается JSON вида {"name": "..."}', 400)
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            return error_response("invalid_name", "Поле name обязательно и не может быть пустым", 400)
        name = name.strip()
        if len(name) > MAX_NAME_LENGTH:
            return error_response("invalid_name", f"Имя длиннее {MAX_NAME_LENGTH} символов", 400)

        db = get_db()
        cursor = db.execute("INSERT INTO users (name) VALUES (?)", (name,))
        db.commit()
        logger.info("Добавлен пользователь id=%s", cursor.lastrowid)
        return jsonify({"status": "ok", "id": cursor.lastrowid, "name": name}), 201

    def find_user(uid: int) -> Optional[sqlite3.Row]:
        """Ищет пользователя по номеру. Слишком большие номера считаются ненайденными."""
        if uid > MAX_USER_ID:
            return None
        return get_db().execute("SELECT id, name FROM users WHERE id = ?", (uid,)).fetchone()

    @app.get("/user/<int:uid>")
    def get_user(uid: int):
        row = find_user(uid)
        if row is None:
            return error_response("not_found", f"Пользователь {uid} не найден", 404)
        return jsonify({"id": row["id"], "name": row["name"]})

    @app.route("/activate/<int:uid>", methods=["GET", "POST"])
    def activate(uid: int):
        if find_user(uid) is None:
            return error_response("not_found", f"Пользователь {uid} не найден", 404)
        active_users.add(uid)
        return jsonify({"status": "ok", "active": active_users.snapshot()})

    @app.get("/slow")
    def slow():
        threading.Thread(target=run_slow_task, args=(SLOW_TASK_ITERATIONS,), daemon=True).start()
        return jsonify({"status": "scheduled"}), 202

    @app.get("/wrong")
    def wrong():
        try:
            result = 1 / 0
        except ZeroDivisionError:
            logger.warning("Демонстрационная ошибка: деление на ноль")
            return error_response("internal_error", "division by zero", 500)
        return jsonify({"result": result})

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        code = error.code or 500
        detail = ERROR_MESSAGES.get(code, error.description or "Ошибка запроса")
        return error_response((error.name or "error").lower().replace(" ", "_"), detail, code)

    @app.errorhandler(Exception)
    def handle_unexpected_error(_error: Exception):
        logger.exception("Необработанная ошибка")
        return error_response("internal_error", "Внутренняя ошибка сервера", 500)

    return app


app = create_app()


def main() -> None:
    """Локальный запуск. Для доступа извне (например, в Docker) задайте HOST=0.0.0.0."""
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "8080"))
    except ValueError:
        port = 8080
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()