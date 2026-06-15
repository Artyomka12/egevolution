import sqlite3
conn = sqlite3.connect('users.db')
# Присваиваем права админа первому зарегистрированному пользователю (тебе)
conn.execute("UPDATE users SET is_admin = 1 WHERE id = 1")
conn.commit()
conn.close()
print("✅ Готово! Обнови страницу профиля.")
