from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    redirect,
    url_for,
    session,
    flash,
)
import json
import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "13524867Artyom"

basedir = os.path.abspath(os.path.dirname(__file__))

SITE_PASSWORD = "0123456789"  # <-- Установите свой пароль

VARIANTS_FOLDER = os.path.join(basedir, "variants")
PREPARATION_FOLDER = os.path.join(basedir, "uroki")
UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads", "avatars")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# === БАЗА ДАННЫХ ===
def get_db():
    db = sqlite3.connect(os.path.join(os.path.dirname(__file__), "users.db"))
    db.row_factory = sqlite3.Row
    return db


def init_db():
    """Создает таблицы и дефолтного админа, если их нет"""
    db = get_db()

    # 1. Создаем таблицы
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        avatar TEXT DEFAULT 'default.png',
        is_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS user_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        variant_num INTEGER,
        score INTEGER,
        secondary_score INTEGER,
        time_spent TEXT,
        date TEXT,
        total_tasks INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )""")
    
    db.execute("""CREATE TABLE IF NOT EXISTS user_task_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        variant_num INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        user_answer TEXT,
        is_correct INTEGER DEFAULT 0,
        points INTEGER DEFAULT 0,
        attempt_date TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS user_lesson_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        attempts INTEGER DEFAULT 0,
        is_correct INTEGER DEFAULT 0,
        last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, lesson_id, task_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS user_theory_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_num INTEGER NOT NULL,
        practice_task_id INTEGER NOT NULL,
        attempts INTEGER DEFAULT 0,
        is_correct INTEGER DEFAULT 0,
        last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, task_num, practice_task_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )""")

    # Таблица доступа к урокам
    db.execute("""CREATE TABLE IF NOT EXISTS user_lesson_access (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        is_unlocked INTEGER DEFAULT 0,
        UNIQUE(user_id, lesson_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )""")

    # Таблица доступа к теории
    db.execute("""CREATE TABLE IF NOT EXISTS user_theory_access (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_num INTEGER NOT NULL,
        is_unlocked INTEGER DEFAULT 0,
        UNIQUE(user_id, task_num),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )""")

    # 2. Проверяем, есть ли уже админ
    admin_exists = db.execute("SELECT id FROM users WHERE is_admin = 1").fetchone()

    if not admin_exists:
        # Если админа нет, создаем его
        admin_username = "Artemiy"
        admin_password = "Artyom_12"

        hashed_pw = generate_password_hash(admin_password)

        try:
            db.execute(
                """
                INSERT INTO users (username, password_hash, name, is_admin, avatar)
                VALUES (?, ?, ?, 1, 'default.png')
            """,
                (admin_username, hashed_pw, "Администратор"),
            )
            db.commit()
            print(
                f"✅ Администратор создан! Логин: {admin_username}, Пароль: {admin_password}"
            )
        except sqlite3.IntegrityError:
            pass  # Если вдруг ошибка уникальности, игнорируем

    db.close()


init_db()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# === ЗАЩИТА МАРШРУТОВ ===
@app.before_request
def check_auth():
    allowed = ["start", "login", "register", "static"]
    endpoint = request.endpoint
    if endpoint not in allowed and "user_id" not in session:
        flash("️ Пожалуйста, войдите в систему", "warning")
        return redirect(url_for("login"))


# === АВТОРИЗАЦИЯ ===
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("start"))
        else:
            flash("❌ Неверный логин или пароль", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        name = request.form.get("name", "")
        site_password = request.form.get("site_password", "")

        # 1. Проверяем пароль сайта
        if site_password != SITE_PASSWORD:
            flash("❌ Неверный пароль сайта", "error")
            return render_template("register.html")

        # 2. Проверяем логин
        db = get_db()
        if db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone():
            flash("⚠️ Такой логин уже занят", "error")
        else:
            # 3. Создаем пользователя
            hashed_pw = generate_password_hash(password)
            db.execute(
                "INSERT INTO users (username, password_hash, name, avatar) VALUES (?, ?, ?, 'default.png')",
                (username, hashed_pw, name),
            )
            db.commit()
            flash("✅ Регистрация успешна! Теперь войдите.", "success")
            return redirect(url_for("login"))
        db.close()

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# === СТАТИСТИКА ===
def load_user_stats(user_id):
    """Загрузка статистики из базы данных для конкретного пользователя"""
    db = get_db()
    results = db.execute(
        "SELECT * FROM user_results WHERE user_id = ? ORDER BY date DESC", (user_id,)
    ).fetchall()

    stats = {
        "total_variants": len(results),
        "best_score": 0,
        "average_score": 0,
        "variants_history": [],
    }

    if results:
        scores = [r["secondary_score"] for r in results]
        stats["best_score"] = max(scores)
        stats["average_score"] = round(sum(scores) / len(scores))

        for r in results:
            stats["variants_history"].append(
                {
                    "id": r["id"],
                    "date": r["date"],
                    "variant_num": r["variant_num"],
                    "score": r["score"],
                    "percentage": r["secondary_score"],
                    "time_spent": r["time_spent"],
                    "total_tasks": r["total_tasks"],  # ← ДОБАВЛЕНО
                }
            )

    db.close()
    return stats


# Замени старую функцию save_user_result на эту
def save_user_result(user_id, variant_num, score, secondary_score, time_spent, total_tasks=27, answers_dict=None):
    """Сохранение результата в БД (включая детальные ответы на каждое задание)"""
    db = get_db()
    
    # 1. Сохраняем общую строку в user_results
    db.execute(
        """
        INSERT INTO user_results (user_id, variant_num, score, secondary_score, time_spent, date, total_tasks)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            variant_num,
            score,
            secondary_score,
            time_spent,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            total_tasks,
        ),
    )
    
    # 2. Если переданы ответы - сохраняем их в таблицу user_task_answers
    if answers_dict:
        tasks = load_tasks(variant_num)
        attempt_date = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        for task in tasks:
            task_id = task.get("id")
            # Ключ в словаре ответов должен быть строкой (например "1", "2")
            user_answer = answers_dict.get(str(task_id))
            
            # Считаем баллы для этого задания
            points = get_points_for_task(task, user_answer)
            is_correct = 1 if points > 0 else 0
            
            # Превращаем ответ в строку JSON для хранения
            answer_json = json.dumps(user_answer) if user_answer else None
            
            db.execute(
                """
                INSERT INTO user_task_answers
                (user_id, variant_num, task_id, user_answer, is_correct, points, attempt_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, variant_num, task_id, answer_json, is_correct, points, attempt_date)
            )
    
    db.commit()
    db.close()

def get_attempt_details(user_id, attempt_id):
    """Получает детальную информацию о конкретной попытке решения варианта"""
    db = get_db()
    
    # 1. Получаем общую информацию о попытке
    attempt = db.execute(
        """
        SELECT * FROM user_results WHERE id = ? AND user_id = ?
        """,
        (attempt_id, user_id)
    ).fetchone()
    
    if not attempt:
        db.close()
        return None
    
    # 2. Получаем ответы пользователя по каждому заданию
    user_answers = db.execute(
        """
        SELECT * FROM user_task_answers 
        WHERE user_id = ? AND variant_num = ? AND attempt_date = ?
        ORDER BY task_id
        """,
        (user_id, attempt["variant_num"], attempt["date"])
    ).fetchall()
    
    db.close()
    
    # 3. Загружаем правильные задания из JSON файла
    tasks = load_tasks(attempt["variant_num"])
    
    # 4. Объединяем данные
    detailed_tasks = []
    for task in tasks:
        task_id = task.get("id")
        # Ищем ответ пользователя для этого задания
        user_record = next((ua for ua in user_answers if ua["task_id"] == task_id), None)
        
        detailed_tasks.append({
            "task_data": task,                  # Данные задания (условие, правильный ответ)
            "user_answer": json.loads(user_record["user_answer"]) if user_record and user_record["user_answer"] else None, # Что ввел пользователь
            "is_correct": user_record["is_correct"] if user_record else 0,
            "points": user_record["points"] if user_record else 0
        })
    
    return {
        "info": attempt,
        "tasks": detailed_tasks
    }

# === ТАБЛИЦА БАЛЛОВ ===
PRIMARY_TO_SECONDARY = {
    0: 0,
    1: 7,
    2: 14,
    3: 20,
    4: 27,
    5: 34,
    6: 40,
    7: 43,
    8: 46,
    9: 48,
    10: 51,
    11: 54,
    12: 56,
    13: 59,
    14: 62,
    15: 64,
    16: 67,
    17: 70,
    18: 72,
    19: 75,
    20: 78,
    21: 80,
    22: 83,
    23: 85,
    24: 88,
    25: 90,
    26: 93,
    27: 95,
    28: 98,
    29: 100,
}


def convert_to_secondary_score(primary_points):
    if primary_points < 0:
        return 0
    if primary_points >= 29:
        return 100
    return PRIMARY_TO_SECONDARY.get(primary_points, 100)


def get_points_for_task(task, user_answer):
    task_id = task.get("id")
    if not user_answer:
        return 0
    if task_id in [26, 27]:
        if "answer_grid" not in task:
            return 0
        correct_grid = task["answer_grid"]["answers"]
        correct_vals = [
            val.strip() for row in correct_grid for val in row if val.strip()
        ]
        user_vals = []
        if isinstance(user_answer, list):
            for row in user_answer:
                if isinstance(row, list):
                    user_vals.extend([val.strip() for val in row if val.strip()])
                else:
                    if row.strip():
                        user_vals.append(row.strip())
        if not user_vals:
            return 0
        if user_vals == correct_vals:
            return 2
        matches = sum(
            1
            for i in range(len(correct_vals))
            if i < len(user_vals) and user_vals[i] == correct_vals[i]
        )
        if matches > 0:
            return 1
        if len(user_vals) == len(correct_vals) and sorted(user_vals) == sorted(
            correct_vals
        ):
            return 1
        return 0
    else:
        is_correct = False
        if "answer_grid" in task:
            correct_grid = task["answer_grid"]["answers"]
            flat_correct = [a for row in correct_grid for a in row if a.strip()]
            flat_user = (
                [a for row in user_answer for a in row if a.strip()]
                if isinstance(user_answer, list)
                else []
            )
            is_correct = flat_user == flat_correct
        elif "answers" in task and len(task["answers"]) == 2:
            if isinstance(user_answer, list) and len(user_answer) == 2:
                is_correct = all(
                    u.lower().strip() == c.lower().strip()
                    for u, c in zip(user_answer, task["answers"])
                )
        else:
            if isinstance(user_answer, str):
                is_correct = (
                    user_answer.lower().strip()
                    == task.get("correct_answer", "").lower().strip()
                )
        return 1 if is_correct else 0


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_available_variants():
    variants = []
    if os.path.exists(VARIANTS_FOLDER):
        for folder in os.listdir(VARIANTS_FOLDER):
            if folder.startswith("variant_"):
                variant_num = int(folder.replace("variant_", ""))
                json_path = os.path.join(VARIANTS_FOLDER, folder, f"{folder}.json")
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            tasks = data.get("tasks", [])
                            variants.append(
                                {
                                    "num": variant_num,
                                    "title": data.get(
                                        "title", f"Вариант {variant_num}"
                                    ),
                                    "task_count": len(tasks),
                                }
                            )
                    except:
                        pass
    return sorted(variants, key=lambda x: x["num"])


def load_tasks(variant_num=1):
    variant_folder = f"variant_{variant_num:02d}"
    json_file = f"{variant_folder}.json"
    filepath = os.path.join(VARIANTS_FOLDER, variant_folder, json_file)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("tasks", [])
    except FileNotFoundError:
        return []


def load_lesson(lesson_id):
    lesson_folder = f"urok_{lesson_id:02d}"
    json_file = f"urok_{lesson_id:02d}.json"
    filepath = os.path.join(PREPARATION_FOLDER, lesson_folder, json_file)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


# === ФУНКЦИИ ДЛЯ УРОКОВ ===
def check_lesson_answer(task, user_answer):
    """Проверяет ответ пользователя на задание урока"""
    if not user_answer:
        return False

    if "answer_grid" in task:
        correct_grid = task["answer_grid"]["answers"]
        correct_vals = [
            val.strip() for row in correct_grid for val in row if val.strip()
        ]
        if isinstance(user_answer, list):
            user_vals = []
            for row in user_answer:
                if isinstance(row, list):
                    user_vals.extend([val.strip() for val in row if val.strip()])
                else:
                    if row.strip():
                        user_vals.append(row.strip())
            return user_vals == correct_vals
        return False
    elif "answers" in task and len(task["answers"]) == 2:
        if isinstance(user_answer, list) and len(user_answer) == 2:
            return (
                user_answer[0].lower().strip() == task["answers"][0].lower().strip()
                and user_answer[1].lower().strip() == task["answers"][1].lower().strip()
            )
        return False
    else:
        if isinstance(user_answer, str):
            return (
                user_answer.lower().strip()
                == task.get("correct_answer", "").lower().strip()
            )
        return False


def get_lesson_task_progress(user_id, lesson_id, task_id):
    """Получает прогресс конкретного задания урока"""
    db = get_db()
    result = db.execute(
        """SELECT attempts, is_correct FROM user_lesson_progress
                           WHERE user_id=? AND lesson_id=? AND task_id=?""",
        (user_id, lesson_id, task_id),
    ).fetchone()
    db.close()
    if result:
        return {"attempts": result["attempts"], "is_correct": result["is_correct"]}
    return {"attempts": 0, "is_correct": 0}


# === ЛОГИКА ТЕОРИИ ===


def check_theory_answer_logic(task, user_answer):
    """Проверяет ответ на практическое задание в теории"""
    if not user_answer:
        return False

    # Если ответ - строка
    if isinstance(user_answer, str):
        return (
            user_answer.lower().strip()
            == task.get("correct_answer", "").lower().strip()
        )

    # Если ответ - список (2 ответа)
    if isinstance(user_answer, list) and "answers" in task:
        if len(user_answer) == len(task["answers"]):
            return all(
                u.lower().strip() == c.lower().strip()
                for u, c in zip(user_answer, task["answers"])
            )

    # Если таблица
    if "answer_grid" in task:
        correct_grid = task["answer_grid"]["answers"]
        # Преобразуем ответы пользователя в плоский список
        user_vals = []
        if isinstance(user_answer, list):
            for row in user_answer:
                if isinstance(row, list):
                    user_vals.extend([v.strip() for v in row if v.strip()])
                elif row.strip():
                    user_vals.append(row.strip())

        correct_vals = [
            val.strip() for row in correct_grid for val in row if val.strip()
        ]
        return user_vals == correct_vals

    return False


@app.route("/check_theory_answer", methods=["POST"])
def check_theory_answer():
    """Проверка ответа в теории и сохранение прогресса"""
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    task_num = data.get("task_num")
    practice_task_id = data.get("practice_task_id")  # Индекс задания (1, 2...)
    user_answer = data.get("answer")

    # Загружаем JSON теории
    theory_path = os.path.join("theory", f"task_{task_num:02d}", "theory.json")
    if not os.path.exists(theory_path):
        return jsonify({"error": "Theory not found"}), 404

    with open(theory_path, "r", encoding="utf-8") as f:
        theory_data = json.load(f)

    if not theory_data.get("practice") or not theory_data["practice"].get("tasks"):
        return jsonify({"error": "No tasks"}), 404

    tasks = theory_data["practice"]["tasks"]
    # Индекс в списке (0-based), но practice_task_id приходит 1-based
    if practice_task_id < 1 or practice_task_id > len(tasks):
        return jsonify({"error": "Invalid task ID"}), 400

    task = tasks[practice_task_id - 1]
    is_correct = check_theory_answer_logic(task, user_answer)

    # Обновляем БД
    db = get_db()
    user_id = session["user_id"]
    existing = db.execute(
        "SELECT attempts, is_correct FROM user_theory_progress WHERE user_id=? AND task_num=? AND practice_task_id=?",
        (user_id, task_num, practice_task_id),
    ).fetchone()

    if existing:
        new_attempts = existing["attempts"] + 1
        # Если уже было решено верно, статус остается верным
        new_is_correct = 1 if (existing["is_correct"] == 1 or is_correct) else 0
        db.execute(
            "UPDATE user_theory_progress SET attempts=?, is_correct=?, last_attempt=CURRENT_TIMESTAMP WHERE user_id=? AND task_num=? AND practice_task_id=?",
            (new_attempts, new_is_correct, user_id, task_num, practice_task_id),
        )
        result = {"attempts": new_attempts, "is_correct": new_is_correct}
    else:
        db.execute(
            "INSERT INTO user_theory_progress (user_id, task_num, practice_task_id, attempts, is_correct) VALUES (?, ?, ?, 1, ?)",
            (user_id, task_num, practice_task_id, 1 if is_correct else 0),
        )
        result = {"attempts": 1, "is_correct": 1 if is_correct else 0}

    db.commit()
    db.close()

    return jsonify(
        {
            "correct": is_correct,
            "attempts": result["attempts"],
            "is_correct": result["is_correct"],
        }
    )


# === МАРШРУТЫ ===
@app.route("/")
def start():
    return render_template("start.html")


@app.route("/variants")
def variant_list():
    variants = get_available_variants()
    return render_template("variant_list.html", variants=variants)


@app.route("/tasks")
@app.route("/tasks/<int:variant_num>")
def reshenie(variant_num=1):
    tasks = load_tasks(variant_num)
    return render_template("reshenie.html", tasks=tasks, variant_num=variant_num)


# === МАРШРУТ ТЕОРИИ (СПИСОК) ===
@app.route("/theory")
def theory():
    """Главная страница теории с прогрессом"""
    theory_tasks = []
    # Собираем список доступных тем (1-27)
    for i in range(1, 28):
        folder = f"task_{i:02d}"
        path = os.path.join(basedir, "theory", folder, "theory.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    task_info = {
                        "num": i,
                        "title": data.get("title", f"Задание {i}"),
                        "total_tasks": len(data.get("practice", {}).get("tasks", [])),
                    }
                    theory_tasks.append(task_info)
            except:
                pass

    # Если авторизован - грузим прогресс И ДОСТУП
    if "user_id" in session:
        user_id = session["user_id"]
        db = get_db()
        for task in theory_tasks:
            task_num = task["num"]

            # ✅ ИСПРАВЛЕНО: Ищем в таблице user_theory_progress
            # Кол-во решенных верно
            correct = db.execute(
                "SELECT COUNT(*) FROM user_theory_progress WHERE user_id=? AND task_num=? AND is_correct=1",
                (user_id, task_num),
            ).fetchone()[0]
            # Кол-во попыток вообще
            attempts = db.execute(
                "SELECT COUNT(*) FROM user_theory_progress WHERE user_id=? AND task_num=?",
                (user_id, task_num),
            ).fetchone()[0]

            task["correct_tasks"] = correct
            task["attempts"] = attempts

            if attempts == 0:
                task["status"] = "not_started"  # Белый
            elif correct == task["total_tasks"]:
                task["status"] = "completed"  # Зеленый
            else:
                task["status"] = "in_progress"  # Желтый

            # ✅ ДОБАВЛЕНО: Получаем статус доступа
            access = db.execute(
                "SELECT is_unlocked FROM user_theory_access WHERE user_id=? AND task_num=?",
                (user_id, task_num),
            ).fetchone()
            task["is_unlocked"] = access["is_unlocked"] if access else 0

        db.close()

    return render_template("teoria.html", tasks=theory_tasks)


@app.route("/theory/<int:task_num>")
def theory_task(task_num):
    """Страница конкретной теории с панелью прогресса"""
    theory_path = os.path.join(basedir, "theory", f"task_{task_num:02d}", "theory.json")
    theory_data = None
    task_progress = {}

    if os.path.exists(theory_path):
        try:
            with open(theory_path, "r", encoding="utf-8") as f:
                theory_data = json.load(f)

            # Проверяем доступ (если не админ)
            if "user_id" in session:
                db = get_db()
                current_user = db.execute(
                    "SELECT * FROM users WHERE id = ?", (session["user_id"],)
                ).fetchone()
                db.close()

                # Если не админ - проверяем доступ
                if current_user and current_user["is_admin"] != 1:
                    if not check_theory_access(session["user_id"], task_num):
                        flash(
                            "🔒 Этот материал заблокирован. Обратитесь к администратору.",
                            "warning",
                        )
                        return redirect(url_for("theory"))

            # Грузим прогресс по каждому заданию внутри этой теории
            if (
                "user_id" in session
                and theory_data.get("practice")
                and theory_data["practice"].get("tasks")
            ):
                user_id = session["user_id"]
                db = get_db()
                tasks_list = theory_data["practice"]["tasks"]

                for idx, task in enumerate(tasks_list):
                    task_id = idx + 1
                    # ✅ ИСПРАВЛЕНО: Ищем в таблице user_theory_progress
                    res = db.execute(
                        "SELECT attempts, is_correct FROM user_theory_progress WHERE user_id=? AND task_num=? AND practice_task_id=?",
                        (user_id, task_num, task_id),
                    ).fetchone()
                    if res:
                        task_progress[task_id] = {
                            "attempts": res["attempts"],
                            "is_correct": res["is_correct"],
                        }
                    else:
                        task_progress[task_id] = {"attempts": 0, "is_correct": 0}
                db.close()
        except:
            pass

    return render_template(
        "teoria_zadanie.html",
        task_num=task_num,
        theory=theory_data,
        task_progress=task_progress,
    )


@app.route("/variant_images/<int:variant_num>/<path:filename>")
def variant_images(variant_num, filename):
    folder = os.path.join(VARIANTS_FOLDER, f"variant_{variant_num:02d}", "images")
    return send_from_directory(folder, filename)


@app.route("/variant_files/<int:variant_num>/<path:filename>")
def variant_files(variant_num, filename):
    folder = os.path.join(VARIANTS_FOLDER, f"variant_{variant_num:02d}", "files")
    return send_from_directory(folder, filename, as_attachment=True)


@app.route("/theory_images/<int:task_num>/<path:filename>")
def theory_images(task_num, filename):
    folder = os.path.join(basedir, "theory", f"task_{task_num:02d}", "images")
    return send_from_directory(folder, filename)


@app.route("/theory_videos/<int:task_num>/<path:filename>")
def theory_videos(task_num, filename):
    folder = os.path.join(basedir, "theory", f"task_{task_num:02d}", "videos")
    return send_from_directory(folder, filename)


@app.route("/theory_files/<int:task_num>/<path:filename>")
def theory_files(task_num, filename):
    folder = os.path.join(basedir, "theory", f"task_{task_num:02d}", "practice_files")
    return send_from_directory(folder, filename, as_attachment=True)


# === МАРШРУТ НАЧАЛЬНОЙ ПОДГОТОВКИ (СПИСОК) ===
@app.route("/preparation")
def preparation():
    lessons = []
    if os.path.exists(PREPARATION_FOLDER):
        for folder in os.listdir(PREPARATION_FOLDER):
            if folder.startswith("urok_"):
                lesson_num = int(folder.replace("urok_", ""))
                json_path = os.path.join(
                    PREPARATION_FOLDER, folder, f"urok_{lesson_num:02d}.json"
                )
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            lesson_info = {
                                "id": lesson_num,
                                "title": data.get("title", f"Урок {lesson_num}"),
                                "description": data.get(
                                    "description", "Описание урока"
                                ),
                                "total_tasks": len(
                                    data.get("practice", {}).get("tasks", [])
                                ),
                            }
                            lessons.append(lesson_info)
                    except:
                        pass

    # Если пользователь авторизован, получаем прогресс и доступ
    if "user_id" in session:
        user_id = session["user_id"]
        db = get_db()
        for lesson in lessons:
            lesson_id = lesson["id"]

            # Прогресс
            correct_tasks = db.execute(
                """SELECT COUNT(*) FROM user_lesson_progress WHERE user_id=? AND lesson_id=? AND is_correct=1""",
                (user_id, lesson_id),
            ).fetchone()[0]
            attempts = db.execute(
                """SELECT COUNT(*) FROM user_lesson_progress WHERE user_id=? AND lesson_id=?""",
                (user_id, lesson_id),
            ).fetchone()[0]
            lesson["correct_tasks"] = correct_tasks
            lesson["attempts"] = attempts
            lesson["status"] = (
                "completed"
                if correct_tasks == lesson["total_tasks"]
                else ("in_progress" if attempts > 0 else "not_started")
            )

            # ✅ ДОБАВЛЯЕМ СТАТУС ДОСТУПА
            lesson["is_unlocked"] = check_lesson_access(user_id, lesson_id)
        db.close()

    return render_template(
        "preparation.html", lessons=sorted(lessons, key=lambda x: x["id"])
    )


@app.route("/preparation/<int:lesson_id>")
def preparation_lesson(lesson_id):
    lesson = load_lesson(lesson_id)
    if not lesson:
        return "Урок не найден", 404

    # Проверяем доступ (если не админ)
    if "user_id" in session:
        db = get_db()
        current_user = db.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        db.close()

        # Если не админ - проверяем доступ
        if current_user and current_user["is_admin"] != 1:
            if not check_lesson_access(session["user_id"], lesson_id):
                flash(
                    "🔒 Этот урок заблокирован. Обратитесь к администратору.", "warning"
                )
                # ✅ ИСПРАВЛЕНО: Возвращаем в список уроков, а не в профиль
                return redirect(url_for("preparation"))

    # ... (остальной код функции без изменений) ...
    task_progress = {}
    if (
        "user_id" in session
        and lesson.get("practice")
        and lesson["practice"].get("tasks")
    ):
        user_id = session["user_id"]
        tasks = lesson["practice"]["tasks"]
        for i in range(len(tasks)):
            task_id = i + 1
            task_progress[task_id] = get_lesson_task_progress(
                user_id, lesson_id, task_id
            )

    return render_template(
        "preparation_lesson.html",
        lesson=lesson,
        lesson_id=lesson_id,
        task_progress=task_progress,
    )


@app.route("/preparation_images/<int:lesson_id>/<path:filename>")
def preparation_images(lesson_id, filename):
    folder = os.path.join(PREPARATION_FOLDER, f"urok_{lesson_id:02d}", "images")
    return send_from_directory(folder, filename)


@app.route("/preparation_videos/<int:lesson_id>/<path:filename>")
def preparation_videos(lesson_id, filename):
    folder = os.path.join(PREPARATION_FOLDER, f"urok_{lesson_id:02d}", "videos")
    return send_from_directory(folder, filename)


@app.route("/check_lesson_task", methods=["POST"])
def check_lesson_task():
    """Проверка задания урока и обновление прогресса"""
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    lesson_id = data.get("lesson_id")
    task_id = data.get("task_id")
    user_answer = data.get("answer")

    if not lesson_id or not task_id:
        return jsonify({"error": "Missing lesson_id or task_id"}), 400

    lesson = load_lesson(lesson_id)
    if not lesson or not lesson.get("practice") or not lesson["practice"].get("tasks"):
        return jsonify({"error": "Lesson not found or no tasks"}), 404

    tasks = lesson["practice"]["tasks"]
    if task_id < 1 or task_id > len(tasks):
        return jsonify({"error": "Invalid task_id"}), 400

    task = tasks[task_id - 1]
    is_correct = check_lesson_answer(task, user_answer)

    db = get_db()
    user_id = session["user_id"]

    existing = db.execute(
        "SELECT attempts, is_correct FROM user_lesson_progress WHERE user_id=? AND lesson_id=? AND task_id=?",
        (user_id, lesson_id, task_id),
    ).fetchone()

    if existing:
        new_attempts = existing["attempts"] + 1
        # Сохраняем статус "решено правильно", если когда-либо было правильно
        new_is_correct = 1 if (existing["is_correct"] == 1 or is_correct) else 0
        db.execute(
            """UPDATE user_lesson_progress
                      SET attempts = ?, is_correct = ?, last_attempt = CURRENT_TIMESTAMP
                      WHERE user_id=? AND lesson_id=? AND task_id=?""",
            (new_attempts, new_is_correct, user_id, lesson_id, task_id),
        )
        result = {"attempts": new_attempts, "is_correct": new_is_correct}
    else:
        db.execute(
            """INSERT INTO user_lesson_progress (user_id, lesson_id, task_id, attempts, is_correct)
                      VALUES (?, ?, ?, 1, ?)""",
            (user_id, lesson_id, task_id, 1 if is_correct else 0),
        )
        result = {"attempts": 1, "is_correct": 1 if is_correct else 0}

    db.commit()
    db.close()

    return jsonify(
        {
            "correct": is_correct,
            "attempts": result["attempts"],
            "is_correct": result["is_correct"],
        }
    )


@app.route("/check/<int:variant_num>/<int:task_id>", methods=["POST"])
def check(variant_num, task_id):
    tasks = load_tasks(variant_num)
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return jsonify({"correct": False, "message": "Задание не найдено"}), 404
    if "answer_grid" in task:
        rows = task["answer_grid"]["rows"]
        cols = task["answer_grid"]["cols"]
        correct_answers = task["answer_grid"]["answers"]
        all_correct = True
        user_answers = []
        for i in range(rows):
            row_answers = []
            for j in range(cols):
                user_val = request.form.get(f"answer_{i}_{j}", "").strip()
                correct_val = (
                    correct_answers[i][j].strip() if j < len(correct_answers[i]) else ""
                )
                is_match = user_val.lower() == correct_val.lower()
                if not is_match:
                    all_correct = False
                row_answers.append(is_match)
            user_answers.append(row_answers)
        return jsonify(
            {
                "correct": all_correct,
                "message": ("✅ Верно!" if all_correct else "❌ Неверно."),
                "grid_results": user_answers,
            }
        )
    elif "answers" in task and len(task["answers"]) == 2:
        user_answer1 = request.form.get("answer1", "").strip()
        user_answer2 = request.form.get("answer2", "").strip()
        correct_answer1 = task["answers"][0].strip()
        correct_answer2 = task["answers"][1].strip()
        is_correct = (
            user_answer1.lower() == correct_answer1.lower()
            and user_answer2.lower() == correct_answer2.lower()
        )
        return jsonify(
            {
                "correct": is_correct,
                "message": ("✅ Верно!" if is_correct else " Неверно."),
                "answer1_correct": user_answer1.lower() == correct_answer1.lower(),
                "answer2_correct": user_answer2.lower() == correct_answer2.lower(),
            }
        )
    else:
        user_answer = request.form.get("answer", "").strip()
        correct_answer = task.get("correct_answer", "").strip()
        is_correct = user_answer.lower() == correct_answer.lower()
        return jsonify(
            {
                "correct": is_correct,
                "message": "✅ Верно!" if is_correct else " Неверно",
            }
        )


@app.route("/stats")
def stats():
    user_id = session["user_id"]
    statistics = load_user_stats(user_id)
    return render_template("stats.html", stats=statistics)

@app.route("/stats/attempt/<int:attempt_id>")
def view_attempt(attempt_id):
    """Просмотр детальной статистики по конкретной попытке"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    attempt_data = get_attempt_details(user_id, attempt_id)
    
    if not attempt_data:
        flash(" Попытка не найдена", "error")
        return redirect(url_for("stats"))
    
    return render_template(
        "attempt_detail.html",  # Этот файл мы создадим позже
        info=attempt_data["info"],
        tasks=attempt_data["tasks"],
        variant_num=attempt_data["info"]["variant_num"]
    )

@app.route("/admin/user/<int:user_id>/attempt/<int:attempt_id>")
def admin_view_attempt(user_id, attempt_id):
    """Просмотр детальной статистики попытки админом"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    db = get_db()
    current_user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    
    # Проверка на админа
    if not current_user or current_user["is_admin"] != 1:
        flash("🚫 У вас нет прав администратора", "error")
        db.close()
        return redirect(url_for("profile"))
    
    # Получаем детальную информацию о попытке
    attempt_data = get_attempt_details(user_id, attempt_id)
    
    if not attempt_data:
        flash("⚠️ Попытка не найдена", "error")
        db.close()
        return redirect(url_for("admin_view_user", user_id=user_id))
    
    db.close()
    
    return render_template(
        "attempt_detail.html",
        info=attempt_data["info"],
        tasks=attempt_data["tasks"],
        variant_num=attempt_data["info"]["variant_num"],
        target_user_id=user_id  # Передаем ID пользователя для кнопки "Назад"
    )

# ✅ ИСПРАВЛЕНО: Передается len(tasks)
@app.route("/save_results/<int:variant_num>", methods=["POST"])
def save_results(variant_num):
    user_id = session["user_id"]
    data = request.json
    
    # Получаем ответы и время
    raw_answers = data.get("answers", {})
    time_spent = data.get("time_spent", "00:00:00")
    
    # Приводим ключи ответов к строкам ("1": "...", "2": "..."), так как из JS они могут прийти как числа
    answers_dict = {str(k): v for k, v in raw_answers.items()}
    
    tasks = load_tasks(variant_num)
    total_points = 0
    
    # Считаем общий балл
    for task in tasks:
        points = get_points_for_task(task, answers_dict.get(str(task["id"])))
        total_points += points
    
    secondary_score = convert_to_secondary_score(total_points)
    
    # Сохраняем всё в БД (включая детальные ответы)
    save_user_result(
        user_id, 
        variant_num, 
        total_points, 
        secondary_score, 
        time_spent, 
        len(tasks), 
        answers_dict=answers_dict  # <--- ПЕРЕДАЕМ ОТВЕТЫ
    )
    
    return jsonify({"success": True, "message": "Результаты сохранены!"})


@app.route("/results/<int:variant_num>")
def results(variant_num):
    tasks = load_tasks(variant_num)
    return render_template("results.html", tasks=tasks, variant_num=variant_num)


# ✅ ИСПРАВЛЕНО: Передается len(tasks)
@app.route("/finish_exam/<int:variant_num>", methods=["POST"])
def finish_exam(variant_num):
    data = request.json
    
    # Получаем ответы и время
    raw_answers = data.get("answers", {})
    time_spent = data.get("time_spent", "00:00:00")
    
    # Приводим ключи ответов к строкам
    answers_dict = {str(k): v for k, v in raw_answers.items()}
    
    tasks = load_tasks(variant_num)
    total_points = 0
    
    # Считаем общий балл
    for task in tasks:
        points = get_points_for_task(task, answers_dict.get(str(task["id"])))
        total_points += points
    
    secondary_score = convert_to_secondary_score(total_points)
    
    # Сохраняем всё в БД
    save_user_result(
        session["user_id"],
        variant_num,
        total_points,
        secondary_score,
        time_spent,
        len(tasks),
        answers_dict=answers_dict  # <--- ПЕРЕДАЕМ ОТВЕТЫ
    )
    
    return jsonify({"success": True, "redirect": f"/results/{variant_num}"})


@app.route("/exam/<int:variant_num>")
def exam_interface(variant_num):
    tasks = load_tasks(variant_num)
    return render_template("exam.html", tasks=tasks, variant_num=variant_num)


@app.route("/choose-mode/<int:variant_num>")
def choose_mode(variant_num):
    return render_template("choose_mode.html", variant_num=variant_num)


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    db.close()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    stats = load_user_stats(session["user_id"])
    return render_template("profile.html", user=user, stats=stats)


@app.route("/profile/upload_avatar", methods=["POST"])
def upload_avatar():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if "avatar" not in request.files:
        flash("❌ Файл не выбран", "error")
        return redirect(url_for("profile"))
    file = request.files["avatar"]
    if file.filename == "":
        flash("❌ Файл не выбран", "error")
        return redirect(url_for("profile"))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_name = f"user_{session['user_id']}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(filepath)
        db = get_db()
        db.execute(
            "UPDATE users SET avatar = ? WHERE id = ?",
            (unique_name, session["user_id"]),
        )
        db.commit()
        db.close()
        flash("✅ Аватар обновлён!", "success")
    else:
        flash("❌ Разрешены только изображения", "error")
    return redirect(url_for("profile"))


@app.route("/constructor_gate")
def constructor_gate():
    # Проверка на админа
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    db.close()

    if not user or user["is_admin"] != 1:
        flash("🚫 Доступ только для администраторов", "error")
        return redirect(url_for("profile"))

    return render_template("constructor_gate.html")


@app.route("/constructor_editor")
def constructor_editor():
    # Проверка на админа
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    db.close()

    if not user or user["is_admin"] != 1:
        flash("🚫 Доступ только для администраторов", "error")
        return redirect(url_for("profile"))

    return render_template("constructor_editor.html")


@app.route("/clear_stats", methods=["POST"])
def clear_stats():
    try:
        user_id = session["user_id"]
        db = get_db()
        db.execute("DELETE FROM user_results WHERE user_id = ?", (user_id,))
        db.commit()
        db.close()
        return jsonify({"success": True, "message": "Ваша статистика очищена"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# === АДМИН ПАНЕЛЬ ===


@app.route("/admin")
def admin_panel():
    """Страница администратора (Доступ только для is_admin=1)"""
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    current_user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()

    # Если нет прав администратора - выкидываем
    if not current_user or current_user["is_admin"] != 1:
        flash("🚫 У вас нет прав администратора", "error")
        db.close()
        return redirect(url_for("profile"))

    # Получаем список всех пользователей
    all_users = db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    db.close()

    return render_template(
        "admin_panel.html", users=all_users, current_user=current_user
    )


@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    """Удаление пользователя (только для админа)"""
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    current_user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["is_admin"] != 1:
        return "Access Denied", 403

    # Не даем админу удалить самого себя
    if user_id == session["user_id"]:
        flash("❌ Нельзя удалить самого себя", "error")
    else:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        # Удаляем также статистику этого пользователя
        db.execute("DELETE FROM user_results WHERE user_id = ?", (user_id,))
        flash("✅ Пользователь удален", "success")

    db.commit()
    db.close()
    return redirect(url_for("admin_panel"))


def get_user_lesson_stats(user_id):
    """Получает статистику по урокам для пользователя"""
    db = get_db()
    # Получаем список всех уроков из папки
    lessons = []
    if os.path.exists(PREPARATION_FOLDER):
        for folder in os.listdir(PREPARATION_FOLDER):
            if folder.startswith("urok_"):
                lesson_num = int(folder.replace("urok_", ""))
                json_path = os.path.join(
                    PREPARATION_FOLDER, folder, f"urok_{lesson_num:02d}.json"
                )
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            total_tasks = len(data.get("practice", {}).get("tasks", []))
                            lessons.append(
                                {
                                    "id": lesson_num,
                                    "title": data.get("title", f"Урок {lesson_num}"),
                                    "total": total_tasks,
                                }
                            )
                    except:
                        pass

    # Получаем прогресс пользователя
    progress = {}
    rows = db.execute(
        "SELECT lesson_id, task_id, is_correct FROM user_lesson_progress WHERE user_id=?",
        (user_id,),
    ).fetchall()
    for row in rows:
        key = (row["lesson_id"], row["task_id"])
        progress[key] = row["is_correct"]

    db.close()

    # Собираем итоговую статистику
    stats = []
    for lesson in lessons:
        lid = lesson["id"]
        correct_count = sum(
            1 for (l, t), status in progress.items() if l == lid and status == 1
        )
        attempted = any(l == lid for (l, t) in progress.keys())

        status = (
            "completed"
            if correct_count == lesson["total"]
            else ("in_progress" if attempted else "not_started")
        )
        stats.append(
            {
                "id": lid,
                "title": lesson["title"],
                "correct": correct_count,
                "total": lesson["total"],
                "status": status,
            }
        )

    return stats


def get_user_theory_stats(user_id):
    """Получает статистику по теории для пользователя"""
    db = get_db()
    theory_stats = []

    # Проходим по всем заданиям теории (1-27)
    for i in range(1, 28):
        folder = f"task_{i:02d}"
        path = os.path.join(basedir, "theory", folder, "theory.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    total_tasks = len(data.get("practice", {}).get("tasks", []))

                    # Считаем решенные
                    correct_count = db.execute(
                        "SELECT COUNT(*) FROM user_theory_progress WHERE user_id=? AND task_num=? AND is_correct=1",
                        (user_id, i),
                    ).fetchone()[0]

                    attempted = (
                        db.execute(
                            "SELECT COUNT(*) FROM user_theory_progress WHERE user_id=? AND task_num=?",
                            (user_id, i),
                        ).fetchone()[0]
                        > 0
                    )

                    status = (
                        "completed"
                        if correct_count == total_tasks
                        else ("in_progress" if attempted else "not_started")
                    )

                    theory_stats.append(
                        {
                            "num": i,
                            "title": data.get("title", f"Задание {i}"),
                            "correct": correct_count,
                            "total": total_tasks,
                            "status": status,
                        }
                    )
            except:
                pass

    db.close()
    return theory_stats


@app.route("/admin/user/<int:user_id>")
def admin_view_user(user_id):
    """Просмотр статистики конкретного пользователя админом"""
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    current_user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["is_admin"] != 1:
        flash("🚫 У вас нет прав администратора", "error")
        db.close()
        return redirect(url_for("profile"))

    target_user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if not target_user:
        flash("❌ Пользователь не найден", "error")
        db.close()
        return redirect(url_for("admin_panel"))

    # Загружаем всю статистику
    user_stats = load_user_stats(user_id)
    lesson_stats = get_user_lesson_stats(user_id)
    theory_stats = get_user_theory_stats(user_id)

    # Получаем информацию о доступе к урокам
    for lesson in lesson_stats:
        access = db.execute(
            "SELECT is_unlocked FROM user_lesson_access WHERE user_id=? AND lesson_id=?",
            (user_id, lesson["id"]),
        ).fetchone()
        lesson["is_unlocked"] = access["is_unlocked"] if access else 0

    # Получаем информацию о доступе к теории
    for task in theory_stats:
        access = db.execute(
            "SELECT is_unlocked FROM user_theory_access WHERE user_id=? AND task_num=?",
            (user_id, task["num"]),
        ).fetchone()
        task["is_unlocked"] = access["is_unlocked"] if access else 0

    db.close()
    return render_template(
        "admin_user_stats.html",
        target_user=target_user,
        stats=user_stats,
        lesson_stats=lesson_stats,
        theory_stats=theory_stats,
    )


# === УПРАВЛЕНИЕ ДОСТУПОМ ===


@app.route("/admin/user/<int:user_id>/toggle_lesson/<int:lesson_id>", methods=["POST"])
def toggle_lesson_access(user_id, lesson_id):
    """Переключение доступа к уроку (только для админа)"""
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    current_user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["is_admin"] != 1:
        return "Access Denied", 403

    # Проверяем, есть ли запись
    existing = db.execute(
        "SELECT id FROM user_lesson_access WHERE user_id=? AND lesson_id=?",
        (user_id, lesson_id),
    ).fetchone()

    if existing:
        # Переключаем статус
        db.execute(
            "UPDATE user_lesson_access SET is_unlocked = NOT is_unlocked WHERE user_id=? AND lesson_id=?",
            (user_id, lesson_id),
        )
    else:
        # Создаем новую запись с доступом
        db.execute(
            "INSERT INTO user_lesson_access (user_id, lesson_id, is_unlocked) VALUES (?, ?, 1)",
            (user_id, lesson_id),
        )

    db.commit()
    db.close()

    return redirect(url_for("admin_view_user", user_id=user_id))


@app.route("/admin/user/<int:user_id>/toggle_theory/<int:task_num>", methods=["POST"])
def toggle_theory_access(user_id, task_num):
    """Переключение доступа к теории (только для админа)"""
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    current_user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["is_admin"] != 1:
        return "Access Denied", 403

    # Проверяем, есть ли запись
    existing = db.execute(
        "SELECT id FROM user_theory_access WHERE user_id=? AND task_num=?",
        (user_id, task_num),
    ).fetchone()

    if existing:
        # Переключаем статус
        db.execute(
            "UPDATE user_theory_access SET is_unlocked = NOT is_unlocked WHERE user_id=? AND task_num=?",
            (user_id, task_num),
        )
    else:
        # Создаем новую запись с доступом
        db.execute(
            "INSERT INTO user_theory_access (user_id, task_num, is_unlocked) VALUES (?, ?, 1)",
            (user_id, task_num),
        )

    db.commit()
    db.close()

    return redirect(url_for("admin_view_user", user_id=user_id))


def check_theory_access(user_id, task_num):
    """Проверяет, открыта ли теория для пользователя"""
    db = get_db()
    result = db.execute(
        "SELECT is_unlocked FROM user_theory_access WHERE user_id=? AND task_num=?",
        (user_id, task_num),
    ).fetchone()
    db.close()

    # Если записи нет - теория закрыта по умолчанию
    if not result:
        return False
    return result["is_unlocked"] == 1


def check_lesson_access(user_id, lesson_id):
    """Проверяет, открыт ли урок для пользователя"""
    db = get_db()
    result = db.execute(
        "SELECT is_unlocked FROM user_lesson_access WHERE user_id=? AND lesson_id=?",
        (user_id, lesson_id),
    ).fetchone()
    db.close()

    # Если записи нет - урок закрыт по умолчанию
    if not result:
        return False
    return result["is_unlocked"] == 1


if __name__ == "__main__":
    app.run(debug=True)