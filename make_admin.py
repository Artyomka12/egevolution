import sqlite3
from database_config import local_check_enabled, resolve_database_path

database = resolve_database_path()
conn = (sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)
        if local_check_enabled() else sqlite3.connect(str(database)))
# Присваиваем права админа первому зарегистрированному пользователю (тебе)
conn.execute("UPDATE users SET is_admin = 1 WHERE id = 1")
conn.commit()
conn.close()
print("✅ Готово! Обнови страницу профиля.")
