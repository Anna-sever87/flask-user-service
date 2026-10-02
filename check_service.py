import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
failed = 0


def call(method: str, path: str, body=None, raw: bytes = None):
    """Отправляет запрос и возвращает (код ответа, разобранный JSON или текст)."""
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, text = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8")
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def check(title: str, condition: bool, details: str = "") -> None:
    global failed
    if not condition:
        failed += 1
    print(f"[{'OK' if condition else 'FAIL'}]  {title}" + (f" - {details}" if details else ""))


def main() -> int:
    try:
        status, body = call("GET", "/health")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        print(f"Не удалось связаться с сервисом {BASE_URL}: {e}")
        print("Проверьте, что сервис запущен (python api.py или docker run).")
        return 1
    check("GET /health", status == 200 and body == {"status": "ok"}, f"{status} {body}")

    status, body = call("POST", "/adduser", {"name": "Анна"})
    user_id = body.get("id") if isinstance(body, dict) else None
    check("POST /adduser: создание пользователя", status == 201 and isinstance(user_id, int), f"{status} {body}")

    status, body = call("POST", "/adduser", {"name": "O'Neil"})
    check("POST /adduser: апостроф в имени (защита от SQL-инъекции)", status == 201, f"{status}")

    status, body = call("POST", "/adduser", {"name": ""})
    check("POST /adduser: пустое имя даёт 400", status == 400, f"{status} {body}")

    status, body = call("POST", "/adduser", raw=b"\xd1\x82\xd0\xb5\xd0\xba\xd1\x81\xd1\x82")
    check("POST /adduser: не JSON даёт 400", status == 400, f"{status}")

    status, body = call("GET", f"/user/{user_id}")
    check("GET /user/<id>: найденный пользователь", status == 200 and body.get("name") == "Анна", f"{status} {body}")

    status, body = call("GET", "/user/999999")
    check("GET /user/<id>: нет пользователя даёт 404", status == 404 and body.get("error") == "not_found", f"{status} {body}")

    status, body = call("GET", "/user/0%20OR%201=1")
    check("GET /user/0 OR 1=1: инъекция не работает", status == 404, f"{status}")

    status, body = call("POST", f"/activate/{user_id}")
    check("POST /activate/<id>: пользователь в списке активных",
          status == 200 and user_id in body.get("active", []), f"{status} {body}")

    status, body = call("GET", "/activate/999999")
    check("GET /activate/<id>: нет пользователя даёт 404", status == 404, f"{status}")

    started = time.time()
    status, body = call("GET", "/slow")
    check("GET /slow: задача принята (202) и ответ быстрый",
          status == 202 and time.time() - started < 1.5, f"{status}, {time.time() - started:.2f} с")

    status, body = call("GET", "/wrong")
    check("GET /wrong: ожидаемая ошибка 500", status == 500 and body.get("error") == "internal_error", f"{status} {body}")

    status, body = call("GET", "/nope")
    check("GET /nope: неизвестный адрес даёт 404 в JSON", status == 404 and isinstance(body, dict), f"{status}")

    status, body = call("GET", "/adduser")
    check("GET /adduser: неверный метод даёт 405 в JSON", status == 405 and isinstance(body, dict), f"{status}")

    print("\nВсе проверки пройдены." if failed == 0 else f"\nПровалено проверок: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())