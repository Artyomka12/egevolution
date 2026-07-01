# CLAUDE.md — Руководство по проекту для Claude Code

## Описание и назначение

EGEvolution — учебная платформа для подготовки к ЕГЭ по информатике.
Сайт: egevolution.ru

Пользователи проходят варианты ЕГЭ, изучают теорию по заданиям 1–27,
решают практические задачи в уроках. Администратор управляет контентом
через встроенную панель.

**Текущая версия: v1.7.2** — Block Scheme визуализатора научился строить
отдельные диаграммы для пользовательских функций (`def`), с анимацией
перелёта аргументов/возврата между диаграммами (в т.ч. рекурсия), плюс
блок-витрина визуализатора на главной странице и точечные исправления
(наложение диаграмм, источник шарика Memory/Output после `return`, отступы).

v1.7.1 — визуальная унификация визуализатора Python-кода с остальным сайтом:
собственный navbar визуализатора заменён на общий `components/navbar.html`,
светлая тема визуализатора перекрашена под палитру сайта (`--primary: #2563EB`,
общий градиентный фон), тёмная тема визуализатора сохранена, но при её
включении navbar инвертируется в светлый вариант.

v1.7.0 — интеграция визуализатора Python-кода (отдельный проект
[visual-code](https://github.com/Artyomka12/visual-code)), встроен как модуль:
`validator.py` + `tracer.py` рядом с `app.py`, маршруты `GET /visualizer` и
`POST /api/visualizer/trace`, доступ только для авторизованных пользователей.

Редизайн пользовательских страниц (v1.6.5): 15 страниц, светло-голубая тема,
`base.html` + компоненты + 8 page-CSS файлов. Финальный аудит: 246/246 ✅

---

## Стек технологий

| Компонент | Версия |
|---|---|
| Python | 3.x |
| Flask | 3.0.0 |
| Werkzeug | 3.0.1 |
| Flask-WTF | 1.2.1 |
| python-dotenv | 1.0.0 |
| SQLite | встроен |
| Jinja2 | встроен в Flask |
| JavaScript | vanilla, без фреймворков |

---

## Структура проекта

```
webpl with base/
├── app.py                  # Весь backend (~2629 строк) и все Flask-маршруты
├── validator.py            # AST-валидатор кода визуализатора (whitelist-подход, из visual-code)
├── tracer.py               # Трейсер выполнения кода визуализатора (sys.settrace, из visual-code)
├── requirements.txt
├── users.db                # SQLite база данных
├── .env                    # Секреты (НЕ в git)
├── .env.example            # Шаблон переменных окружения
├── make_admin.py           # Утилита назначения прав администратора
├── Procfile                # Для деплоя (gunicorn)
│
├── variants/               # Варианты ЕГЭ (JSON + медиафайлы)
│   ├── variant_01/
│   │   ├── variant.json
│   │   └── images/
│   └── ...
│
├── tasks/                  # База задач по номерам заданий
│   ├── task_01/
│   │   ├── tasks.json
│   │   └── images/
│   └── ... (task_01 — task_27)
│
├── theory/                 # Теоретические материалы
│   ├── task_01/
│   │   ├── theory.json
│   │   ├── images/
│   │   └── videos/
│   └── ...
│
├── uroki/                  # Подготовительные уроки
│   ├── urok_01/
│   │   ├── lesson.json
│   │   └── images/
│   └── ...
│
├── templates/              # 31 HTML-файл (Jinja2)
│   ├── base.html           # Базовый шаблон: блоки title, extra_head, content, scripts
│   ├── components/
│   │   ├── navbar.html     # Sticky тёмный navbar, dropdown, logout POST+CSRF
│   │   ├── footer.html     # Футер со ссылкой на Telegram
│   │   └── flash.html      # Flash-сообщения (success/error/warning)
│   ├── start.html          # Главная страница — автономная, не наследует base.html
│   ├── exam.html           # Экзаменационный режим — автономный, вне scope редизайна
│   ├── reshenie.html       # Решение варианта — автономный, вне scope редизайна
│   ├── visualizer.html     # Визуализатор Python-кода — автономный (visual-code), только для авторизованных
│   ├── [9 admin/constructor-шаблонов] — автономные, вне scope редизайна
│   │   # admin_panel, admin_task_form, admin_tasks_list, admin_tasks_view,
│   │   # admin_user_stats, constructor_gate, constructor_from_base,
│   │   # constructor_theory, constructor_editor
│   └── [15 пользовательских страниц — {% extends "base.html" %}]
│       # login, register, csrf_error, variant_list, teoria, preparation,
│       # tasks_list, profile, stats, attempt_detail, choose_mode,
│       # tasks_view, teoria_zadanie, preparation_lesson, results
│
├── static/
│   ├── favicon.png
│   ├── css/
│   │   ├── design-system.css           # Дизайн-токены: цвета, отступы, .card, .btn, .form-input
│   │   └── pages/                      # Page-specific CSS (8 файлов)
│   │       ├── auth.css                # login, register, csrf_error
│   │       ├── catalogs.css            # variant_list, teoria, preparation, tasks_list
│   │       ├── profile.css             # profile
│   │       ├── stats.css               # stats, attempt_detail
│   │       ├── variants.css            # choose_mode
│   │       ├── tasks.css               # tasks_view
│   │       ├── teoria.css              # teoria_zadanie
│   │       └── preparation_lesson.css  # preparation_lesson
│   ├── js/
│   │   └── scroll-reveal.js            # IntersectionObserver-анимация .reveal → .reveal.visible
│   ├── visualizer/                     # Статика визуализатора Python-кода (из visual-code, без изменений)
│   │   ├── style.css
│   │   └── js/                         # api.js (адаптирован под относительный путь + CSRF), editor.js, animator.js, block-scheme.js
│   ├── images/                         # video-preview-left.jpg, video-preview-right.jpg
│   ├── videos/                         # platform-overview.mp4
│   ├── uploads/avatars/                # Аватары пользователей
│   └── tutors/                         # Файлы преподавателей
```

---

## Дизайн-система и архитектура шаблонов (v1.6.5)

### Светлая тема (пользовательские страницы)

Все 15 пользовательских страниц переведены на единую светло-голубую тему:
градиент фона `#eaf6ff → #f5fbff → #eef8ff`, белые карточки, синий акцент `#2563eb`,
тёмный текст `#0f172a`, sticky тёмный navbar.

### Файлы дизайн-системы

| Файл | Назначение |
|---|---|
| `static/css/design-system.css` | CSS-токены: `--color-bg-page`, `--color-accent-blue`, `--radius-md`, `--transition-base`; классы `.card`, `.btn`, `.form-input`, `.section-heading`, `.page-wrap` |
| `static/css/pages/auth.css` | `login.html`, `register.html`, `csrf_error.html` |
| `static/css/pages/catalogs.css` | `variant_list.html`, `teoria.html`, `preparation.html`, `tasks_list.html` |
| `static/css/pages/profile.css` | `profile.html` |
| `static/css/pages/stats.css` | `stats.html`, `attempt_detail.html` |
| `static/css/pages/variants.css` | `choose_mode.html` |
| `static/css/pages/tasks.css` | `tasks_view.html` (collapse/expand через `max-height: 5000px`) |
| `static/css/pages/teoria.css` | `teoria_zadanie.html` |
| `static/css/pages/preparation_lesson.css` | `preparation_lesson.html` |
| `static/js/scroll-reveal.js` | IntersectionObserver: `.reveal → .reveal.visible`, threshold 0.12 |

### Компоненты (templates/components/)

| Компонент | Особенности |
|---|---|
| `navbar.html` | Sticky тёмный navbar; dropdown раздела; logout через `POST` + CSRF hidden input |
| `footer.html` | Футер со ссылкой на Telegram |
| `flash.html` | Flash-сообщения трёх категорий: `success`, `error`, `warning` |

Примечание: `.card` в `design-system.css` не имеет собственного `padding` — каждый page-CSS добавляет его.
При hover `.card:hover { transform }` переопределяется в page-CSS для интерактивных карточек,
где transform нежелателен (`.task-progress-panel`, `.lesson-practice-card` и др.).

### Автономные шаблоны (не наследуют base.html)

| Шаблон | Причина автономности |
|---|---|
| `start.html` | Собственная дизайн-система v1.6.0–1.6.4; navbar встроен напрямую |
| `exam.html` | Специально вне scope редизайна v1.6.5; встроенный CSS |
| `reshenie.html` | Специально вне scope редизайна v1.6.5; встроенный CSS |
| Admin/constructor-шаблоны (9 шт.) | Вне scope редизайна v1.6.5 |

### CSRF в шаблонах

- HTML-формы: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`
- JSON fetch: заголовок `'X-CSRFToken': '{{ csrf_token() }}'`
- `preparation_lesson.html` не имеет `<form>` — ответы только через `onclick` → `checkTask()` → fetch.
  Любые `<input>` внутри `.task-block` попадают в `querySelectorAll('input')` — скрытые поля недопустимы.

---

## Визуализатор Python-кода (v1.7.0–v1.7.2)

Интегрирован отдельный проект [visual-code](https://github.com/Artyomka12/visual-code) —
интерактивный визуализатор выполнения Python-кода (Classic View: scope-блоки и «шарики»
данных; Block Scheme: анимированная блок-схема/AST). Перенесён как модуль внутрь
существующего Flask-приложения, без отдельного процесса/порта.

**Backend:**

| Файл | Назначение |
|---|---|
| `validator.py` | Whitelist-валидация AST (перенесён из visual-code без изменений). Разрешены: переменные, `if/elif/else`, `for`/`while`, функции, списки/словари/comprehension, ~20 builtin-функций. Запрещены: `import`, `class`, `lambda`, `try/except`, `global/nonlocal`, `async/await` |
| `tracer.py` | Трассировка выполнения через `sys.settrace` (перенесён без изменений). Лимит 600 line-событий (`MAX_STEPS`). Wall-clock timeout не реализован — при необходимости решать отдельно |
| `app.py` | Роуты `GET /visualizer` и `POST /api/visualizer/trace`, импортирующие `validate()`/`trace_code()`. Оба защищены проверкой `"user_id" not in session` |

**Frontend:**

- `templates/visualizer.html` — автономный шаблон, не наследует `base.html` (как `start.html`/`exam.html`), но с v1.7.1 использует общий `{% include 'components/navbar.html' %}` вместо собственного header
- `static/visualizer/style.css` — с v1.7.1 содержит собственную копию CSS navbar (не подключает `design-system.css` целиком — во избежание конфликта одноимённых классов `.card`/`.btn` с классами самого визуализатора); светлая тема (`:root`) перекрашена под палитру сайта (`--primary: #2563EB`, фон — общий градиент `#eaf6ff→#f5fbff→#eef8ff`); тёмная тема (`.dark`) сохранена как есть, но `.dark .navbar` и дочерние элементы инвертированы в светлый вариант — единственный на сайте пример navbar с двумя цветовыми состояниями
- `static/visualizer/js/{editor,animator}.js` — перенесены без изменений; кнопка переключения темы (🌙, `editor.js`) с v1.7.1 расположена в `.page-title` рядом с заголовком страницы, а не в header
- `static/visualizer/js/block-scheme.js` — с v1.7.2 существенно доработан (см. ниже); `editor.js`/`animator.js` (Classic View) не затронуты
- `static/visualizer/js/api.js` — единственная адаптированная часть самого визуализатора (не считая `block-scheme.js` с v1.7.2): `API_BASE` переведён на относительный путь `/api/visualizer`, добавлен заголовок `X-CSRFToken` (токен читается из `<meta name="csrf-token">` в `visualizer.html`)

**Точки входа в навигации:**

- `templates/components/navbar.html` — кнопка «⚡ Визуализатор кода» рядом с выпадающим списком «Разделы платформы» (десктоп); на `≤768px` уходит внутрь выпадающего списка
- `templates/start.html` — идентичная кнопка продублирована во встроенном navbar главной страницы (свой `<style>`, не наследует `components/navbar.html`); с v1.7.2 на главной странице также есть блок-витрина `.visualizer-preview-section` (между «Что есть на платформе» и «Ваш прогресс») — по образцу `.video-preview-section`, видео + два скриншота, CTA на `/visualizer`

**Block Scheme — диаграммы функций (v1.7.2):**

Изначально `block-scheme.js` строил только одну диаграмму и полностью игнорировал тела `def` (пропускались парсером). Теперь:

- Парсер (`parseBlock`/`parseFunctionDef`) распознаёт `def` отдельно от обычной последовательности — тело рекурсивно разбирается и «всплывает» через `functions[]`, а не остаётся в основном потоке; новый тип узла `return` (форма — перевёрнутая трапеция, свой цвет `--bs-return-*` в `style.css`, тупиковый блок без исходящей стрелки)
- `layoutProgram()` (заменил `layoutTree()`) строит главную диаграмму + отдельную диаграмму на каждую функцию, колонкой справа, друг под другом в порядке определения; диаграммы функций не имеют овала «Конец» — обрываются на последнем блоке
- Позиционирование колонки функций — не фиксированным отступом, а измерением: пробный проход `layoutSeq` при `cx=0` для каждой функции (`leftExtent()`), чтобы узнать её реальную левую границу с учётом вложенности циклов/условий, и только потом разместить с гарантированным зазором (`BS.FUNC_GAP_X`). Фиксированный отступ раньше приводил к наложению диаграмм при глубокой вложенности (обнаружено и исправлено в v1.7.2)
- Анимация вызова/возврата: карта `scope_id → строка вызова` (`bsCallSiteLine`, строится один раз из полной трассировки) — при `call`-шаге аргументы летят по невидимой прямой от блока-вызова к «Начало (имя)» нужной диаграммы; при `return`-шаге значение летит обратно именно к тому блоку, откуда был сделан этот конкретный вызов. Работает одинаково для рекурсии (вызов из той же диаграммы) и вызова одной функции из другой
- Источник шарика Memory/Output (`srcEl` в `bsStepNext()`) переопределяется на call-site по той же карте, когда текущий шаг — `return`: иначе шарик летел от строки самого `return`, а не от блока, где функция была вызвана (баг, найденный после того, как диаграммы функций стали реально рисоваться — раньше просто молчаливо не анимировался)
- `#bs-svg` — адаптивный (`max-width:100%; height:auto; min-width:650px`), сжимается под контейнер через свой `viewBox`; ниже `min-width` включается скролл (`#bs-canvas { overflow:auto }`) вместо дальнейшего сжатия

**Известные ограничения (сознательно отложены):**

- Нет wall-clock timeout на трассировку — тяжёлая одна строка (`2**10**8` и т.п.) может надолго занять воркер. Риск снижен закрытым доступом (только авторизованные), но не устранён
- Нет rate limiting на `/api/visualizer/trace`
- Block Scheme: возврат из функции с полностью «мёртвым» if/else внутри цикла (обе ветки — return) может оставить висящую стрелку от несуществующего входа — редкий случай, не входил в текущий scope

---

## Архитектура контента

### Варианты (variants/)

Поддерживаются два формата JSON:

**Старый формат** — список полных объектов задач:
```json
[
  {
    "id": 1,
    "title": "Задание 1",
    "description": ["..."],
    "correct_answer": "42",
    "images": [{"path": "img.png", "after_paragraph": 0}]
  }
]
```

**Новый формат** — словарь ссылок на базу задач:
```json
{
  "1": {"task_id": 5},
  "2": {"task_id": 12}
}
```

Функция `load_variant_tasks(variant_num)` обрабатывает оба формата.
- Старый формат: задачи берутся из JSON варианта напрямую.
- Новый формат: задачи подтягиваются из `tasks/task_XX/tasks.json`.
  При загрузке устанавливается `task["id"] = task_num` и
  `task["_source_task_num"] = task_num` для корректной маршрутизации изображений.

### Маршрутизация изображений

- Новый формат: `url_for('task_images', task_num=task._source_task_num, filename=...)`
- Старый формат: `url_for('variant_images', variant_num=variant_num, filename=...)`

Проверка в шаблонах: `{% if task._source_task_num is defined %}`.

### База задач (tasks/)

`tasks/task_XX/tasks.json` — список объектов задач для задания №XX.
Используется конструктором вариантов и просмотром базы администратором.

### Теория (theory/)

`theory/task_XX/theory.json` — материал по заданию №XX:
- `theory.theory.description` — список абзацев
- `theory.theory.images` — изображения с привязкой к абзацам
- `theory.videos` — массив видео (новый формат)
- `theory.video` — одно видео (старый формат, обратная совместимость)
- `theory.practice.tasks` — практические задания

### Уроки (uroki/)

`uroki/urok_XX/lesson.json` — подготовительный урок.
Доступ управляется через таблицу `user_lesson_access` (админ открывает/закрывает).

### Система сложности задач (DIFFICULTY_INFO)

Каждая задача в `tasks.json` может иметь поле `"difficulty"` с одним из четырёх значений:

| Ключ | Метка | Цвет |
|---|---|---|
| `easy` | Лёгкое | зелёный `#4ade80` |
| `medium` | Среднее | жёлтый `#facc15` |
| `hard` | Сложное | красный `#ef4444` |
| `grave` | Гроб | фиолетовый `#a855f7` |

Словарь `DIFFICULTY_INFO` в `app.py` содержит эти значения и используется
при отображении задач в базе и статистике. Если поле отсутствует — задача
считается `medium` по умолчанию.

---

## База данных (users.db)

### Таблицы

| Таблица | Назначение |
|---|---|
| `users` | Пользователи: id, username, password_hash, name, avatar, is_admin, created_at |
| `user_results` | История попыток решения вариантов: variant_num, score, secondary_score, time_spent, date, total_tasks |
| `user_task_answers` | Ответы на задания в вариантах: variant_num, task_id, user_answer, is_correct, points |
| `user_lesson_progress` | Прогресс в уроках: lesson_id, task_id, attempts, is_correct |
| `user_theory_progress` | Прогресс по теории: task_num, practice_task_id, attempts, is_correct |
| `user_lesson_access` | Доступ к урокам: user_id, lesson_id, is_unlocked |
| `user_theory_access` | Доступ к теории: user_id, task_num, is_unlocked |
| `task_usage` | Статистика использования задач в вариантах |

### Подключение

`get_db()` — открывает новое соединение при каждом запросе.
`db.row_factory = sqlite3.Row` — доступ к полям по имени.
Соединения закрываются вручную в конце каждого обработчика.

---

## Основные маршруты

### Публичные
| Маршрут | Описание |
|---|---|
| `GET /` | Главная страница |
| `GET /login`, `POST /login` | Вход |
| `GET /register`, `POST /register` | Регистрация |
| `POST /logout` | Выход (защищён CSRF; GET → 405) |

### Пользовательские (требуют авторизации)
| Маршрут | Описание |
|---|---|
| `GET /variants` | Список вариантов |
| `GET /solve/<variant_num>` | Решение варианта (обычный режим) |
| `POST /check/<variant_num>/<task_id>` | Проверка ответа на задание |
| `POST /save_results/<variant_num>` | Сохранение результатов варианта |
| `GET /results/<variant_num>` | Страница результатов |
| `GET /exam/<variant_num>` | Экзаменационный режим |
| `POST /finish_exam/<variant_num>` | Завершение экзамена |
| `GET /choose-mode/<variant_num>` | Выбор режима (обычный/экзамен) |
| `GET /theory` | Список заданий теории |
| `GET /theory/<task_num>` | Теория по заданию |
| `POST /check_theory_answer` | Проверка ответа теории |
| `GET /preparation` | Список уроков |
| `GET /preparation/<lesson_id>` | Урок |
| `POST /check_lesson_task` | Проверка ответа урока |
| `GET /tasks` | Публичный список 27 номеров заданий с базы |
| `GET /tasks/<task_num>` | Просмотр задач из базы по номеру задания |
| `GET /stats` | Личная статистика |
| `GET /stats/attempt/<attempt_id>` | Детальная статистика конкретной попытки |
| `GET /profile` | Профиль |
| `POST /profile/upload_avatar` | Загрузка аватара |
| `GET /visualizer` | Визуализатор выполнения Python-кода (только для авторизованных) |
| `POST /api/visualizer/trace` | Трассировка выполнения Python-кода для визуализатора (JSON) |

### Административные (требуют is_admin=1)
| Маршрут | Описание |
|---|---|
| `GET /admin` | Панель администратора |
| `POST /admin/delete_user/<user_id>` | Удаление пользователя |
| `GET /admin/tasks` | Список всех номеров заданий в базе |
| `GET /admin/tasks/<task_num>` | Список задач конкретного номера |
| `GET/POST /admin/tasks/<task_num>/add` | Добавление задачи |
| `GET/POST /admin/tasks/<task_num>/edit/<task_id>` | Редактирование задачи |
| `POST /admin/tasks/<task_num>/delete/<task_id>` | Удаление задачи |
| `GET /admin/user/<user_id>` | Статистика пользователя |
| `GET /admin/user/<user_id>/attempt/<attempt_id>` | Просмотр попытки пользователя |
| `POST /admin/user/<user_id>/toggle_lesson/<lesson_id>` | Доступ к уроку |
| `POST /admin/user/<user_id>/toggle_theory/<task_num>` | Доступ к теории |

### API и конструктор
| Маршрут | Описание |
|---|---|
| `GET /api/tasks/<task_num>` | Список задач из базы (JSON) |
| `GET /api/theory/<task_num>` | Данные теории (JSON) |
| `POST /api/theory/save` | Сохранение теории (JSON) |
| `POST /api/variants/save` | Сохранение нового варианта (JSON) |
| `POST /api/variant/preview` | Предпросмотр варианта (JSON; не используется в шаблонах) |
| `GET /constructor_gate` | Выбор типа конструктора |
| `GET /constructor_from_base` | Конструктор из базы задач |
| `GET /constructor_theory` | Редактор теории |
| `GET /constructor_editor` | Редактор варианта |

### Файловые маршруты (раздача статики контента)
| Маршрут | Источник |
|---|---|
| `GET /task_images/<task_num>/<filename>` | `tasks/task_XX/images/` |
| `GET /task_files/<task_num>/<filename>` | `tasks/task_XX/` |
| `GET /variant_images/<variant_num>/<filename>` | `variants/variant_XX/images/` |
| `GET /variant_files/<variant_num>/<filename>` | `variants/variant_XX/` |
| `GET /theory_images/<task_num>/<filename>` | `theory/task_XX/images/` |
| `GET /theory_videos/<task_num>/<filename>` | `theory/task_XX/videos/` |
| `GET /theory_files/<task_num>/<filename>` | `theory/task_XX/` |
| `GET /preparation_images/<lesson_id>/<filename>` | `uroki/urok_XX/images/` |
| `GET /preparation_videos/<lesson_id>/<filename>` | `uroki/urok_XX/` |

---

## Переменные окружения

Файл `.env` (не в git). Шаблон: `.env.example`.

| Переменная | Обязательна | Описание |
|---|---|---|
| `SECRET_KEY` | ДА | Секретный ключ Flask для подписи сессий |
| `SITE_PASSWORD` | ДА | Пароль для регистрации новых пользователей |
| `ADMIN_USERNAME` | ДА | Логин администратора (при первом запуске) |
| `ADMIN_PASSWORD` | ДА | Пароль администратора (при первом запуске) |
| `WTF_CSRF_SECRET_KEY` | НЕТ | Ключ CSRF (по умолчанию = SECRET_KEY) |
| `FLASK_DEBUG` | НЕТ | Режим отладки: `1` = включён, `0` = выключен |

Приложение **не запустится** без первых четырёх переменных.

---

## Правила запуска

```bash
# 1. Создать .env из шаблона
cp .env.example .env
# Заполнить значения в .env

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Запустить
python app.py
# или для продакшена:
gunicorn app:app
```

База данных `users.db` и администратор создаются автоматически при первом запуске.

---

## Правила работы Claude Code

### Обязательно перед изменениями
1. Прочитать файл полностью, найти все затронутые места.
2. Показать план изменений перед внесением.
3. Дождаться подтверждения пользователя.

### Запрещено без явного подтверждения
- Менять схему базы данных (`CREATE TABLE`, `ALTER TABLE`).
- Менять логику авторизации и проверки паролей.
- Менять формат хранения вариантов в JSON.
- Создавать новые таблицы в `users.db`.
- Менять `load_variant_tasks()` — критическая функция совместимости.
- Переименовывать маршруты (сломает закладки и внешние ссылки).
- Менять структуру директорий `variants/`, `tasks/`, `theory/`, `uroki/`.
- Добавлять зависимости в `requirements.txt` без согласования.
- Делать git push без явной просьбы пользователя.
- Изменять `.env` (содержит реальные секреты).

### Стиль кода
- Шаблоны: 15 пользовательских страниц наследуют `base.html`; `start.html`, `exam.html`,
  `reshenie.html` и все admin-шаблоны — автономные HTML-файлы со встроенным CSS.
- JS — только vanilla, встроен в шаблоны.
- Все секреты — через `os.environ`, не хардкодить.
- Паттерн чтения переменных: `os.environ.get(key) or default` (не `get(key, default)`).
- CSRF: HTML-формы — hidden input, JSON fetch — заголовок `X-CSRFToken`.

---

## Что нельзя менять без подтверждения пользователя

1. **Схема БД** — любые изменения таблиц затрагивают существующих пользователей.
2. **`load_variant_tasks()`** — обеспечивает совместимость старых и новых вариантов.
3. **Маршруты** — изменение URL сломает существующие ссылки и закладки.
4. **Пароль сайта** — механизм закрытой регистрации.
5. **Форматы JSON контента** — variants, tasks, theory, uroki.
6. **Логика подсчёта баллов** — `secondary_score`, `score` в `user_results`.
7. **Права доступа** (`is_admin`) — механизм безопасности.
8. **CSRF-инфраструктура** — не добавлять `csrf.exempt` без аудита.
9. **`exam.html`** — автономный шаблон, специально не переведён на `base.html`;
   содержит встроенный CSS и JS для экзаменационного режима. Требует отдельного решения.
10. **`reshenie.html`** — автономный шаблон, специально не переведён на `base.html`;
    содержит встроенный CSS и JS для режима решения. Требует отдельного решения.
11. **`start.html`** — автономная главная страница со своей дизайн-системой (v1.6.0–1.6.4);
    navbar встроен напрямую. Любые изменения — только отдельным согласованием.
12. **Admin-шаблоны** (9 файлов: `admin_panel`, `admin_task_form`, `admin_tasks_list`,
    `admin_tasks_view`, `admin_user_stats`, `constructor_gate`, `constructor_from_base`,
    `constructor_theory`, `constructor_editor`) — автономные, вне scope редизайна v1.6.5.
13. **`design-system.css`** — изменение токенов затронет все 15 пользовательских страниц одновременно.
14. **`base.html` и `components/`** — изменение затронет все 15 пользовательских страниц.

---

## Работа между несколькими ПК

### Принцип

Код и документация хранятся в git-репозитории на GitHub.
Секреты (`.env`) хранятся локально на каждом ПК — не синхронизируются.
Контекст для Claude Code восстанавливается через `CLAUDE.md`, `DEVELOPMENT_LOG.md`, `TODO.md`.

### Структура файлов контекста

| Файл | Назначение | Обновлять |
|---|---|---|
| `CLAUDE.md` | Статичное описание проекта и правила | При изменении архитектуры |
| `DEVELOPMENT_LOG.md` | История изменений, статус безопасности | После каждой рабочей сессии |
| `TODO.md` | Текущие задачи и известные проблемы | После каждой рабочей сессии |

### Порядок работы через GitHub

**Первичная настройка (один раз):**
```bash
git remote add origin https://github.com/<логин>/<репо>.git
git push -u origin main
```

**Начало работы на любом ПК:**
```bash
git pull origin main
# Убедиться, что .env существует и заполнен
# Если .env нет — скопировать из .env.example и заполнить
```

**Завершение работы на любом ПК:**
```bash
# 1. Обновить DEVELOPMENT_LOG.md и TODO.md (см. промпты ниже)
# 2. Закоммитить изменения
git add .
git commit -m "описание изменений"
git push origin main
```

### Регламент обновления документации

**После каждого крупного изменения кода:**
- Обновить соответствующий раздел в `DEVELOPMENT_LOG.md` (что изменено, почему)
- Закрыть выполненные пункты в `TODO.md`

**Перед переключением на другой компьютер:**
- Обновить `DEVELOPMENT_LOG.md` — текущее состояние, что сделано
- Обновить `TODO.md` — что осталось, что в процессе
- Сделать коммит и `git push`

**Перед коммитом:**
- Проверить, что `.env` не попал в `git add`
- Обновить `DEVELOPMENT_LOG.md` если были значимые изменения

**Перед новым релизом:**
- Добавить новую версию в `DEVELOPMENT_LOG.md` с полным списком изменений
- Обновить статус безопасности
- Закрыть все выполненные задачи в `TODO.md`
- Обновить версию в заголовке `DEVELOPMENT_LOG.md`

### Как восстановить контекст на новом компьютере

1. `git pull origin main`
2. Убедиться, что `.env` заполнен
3. Открыть Claude Code и использовать промпт начала сессии (ниже)
4. Claude прочитает `CLAUDE.md`, `DEVELOPMENT_LOG.md`, `TODO.md` и восстановит контекст

### Промпт начала новой сессии

Использовать после `git pull` на новом компьютере или после долгого перерыва:

```
Привет. Продолжаем работу над проектом EGEvolution.

Прочитай эти файлы по порядку и восстанови контекст:
1. CLAUDE.md — архитектура и правила проекта
2. DEVELOPMENT_LOG.md — что уже сделано и текущий статус
3. TODO.md — что нужно сделать

После прочтения:
- кратко подтверди текущее состояние проекта;
- напомни, что было сделано последним;
- укажи, какая задача следующая по приоритету из TODO.md.

Не вноси никаких изменений до моей команды.
```

### Промпт завершения рабочей сессии

Использовать перед `git commit` и переключением на другой ПК:

```
Рабочая сессия завершается. Обнови документацию.

Задача 1 — обнови DEVELOPMENT_LOG.md:
- добавь запись о сегодняшних изменениях (дата: сегодня);
- опиши что было сделано в этой сессии;
- обнови статус проверок если проводились;
- не удаляй историю предыдущих версий.

Задача 2 — обнови TODO.md:
- закрой [x] выполненные задачи;
- добавь новые задачи если они появились в ходе работы;
- обнови приоритеты если изменились.

После обновления файлов — покажи краткий список изменений,
чтобы я мог написать сообщение для git commit.

Код проекта не трогай.
```
