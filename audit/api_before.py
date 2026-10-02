from flask import Flask,request,jsonify
import sqlite3,time,random,threading

app=Flask(__name__)

# глобальное соединение (плохая практика)
conn = sqlite3.connect("test.db", check_same_thread=False)
cur=conn.cursor()
try:
    cur.execute("CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT)")
except:
    pass

# НЕ ПЕП8, плохие имена, нет валидации, SQL-инъекции
@app.route("/adduser", methods=["POST"])
def addUser():
    name = request.json.get("name","")
    q = f"INSERT INTO users(name) VALUES('{name}')"
    cur.execute(q) # инъекция
    conn.commit()
    return "ok"

# Эндпоинт с неверной логикой и неправильными статусами
@app.route("/user/<uid>")
def GETUSER(uid):
    cur.execute("select id,name from users where id="+uid) # тоже инъекция
    r = cur.fetchone()
    if not r:
        return jsonify({"error":"notfound"}) # статус не возвращён (будет 200)
    return jsonify({"id":r[0],"name":r[1]}), 201 # неверный код 201 вместо 200

# Поток создаётся, но логика сломана: общий список без блокировок
active = []

def worker(uid):
    time.sleep(0.1)
    active.append(uid)
    if len(active) > 5:
        active.pop(0)

@app.route("/activate/<uid>", methods=["GET","POST"])
def activate(uid):
    t = threading.Thread(target=worker, args=(uid,))
    t.start()
    return jsonify({"status":"ok","active":active}) # ответ уходит раньше, чем поток закончит

# Тяжёлая работа прямо в обработчике: сервер занят и не отвечает другим
@app.route("/slow")
def slow():
    time.sleep(2)
    s = 0
    for i in range(10**6):
        s += i*i
    return jsonify({"result":s})

# Ошибка проглатывается: клиент получает 200
@app.route("/wrong")
def wrong():
    try:
        x = 1/0
    except:
        return jsonify({"msg":"error"})
    return jsonify({"msg":"ok"})

if __name__=="__main__":
    app.run(debug=True, host="0.0.0.0")