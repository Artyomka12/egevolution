# DEVELOPMENT_LOG.md — История разработки EGEvolution

## Текущее состояние проекта

**Дата последнего обновления:** 2026-06-18
**Ветка:** main
**Версия:** v1.6.4
**Статус:** выполнен — доработка видеосекции (HTML5 video + боковые постеры + fix clipping), CTA-секция записи на занятие, плавающая карточка связи, система цветных полосок .card-stripe

Аудит безопасности завершён в v1.3.0. D-1, D-2, D-3 закрыты.
v1.4.0 — расширенный редактор задач в админке: все три этапа завершены.
v1.5.0 — редизайн главной страницы (`start.html`): dropdown navbar + мобильная версия. Backend не менялся.
v1.5.3 — визуальная иерархия `start.html`: Hero двухколоночный, stats-row полоса, start-flow маршрут, акценты секций, панель преимуществ, feature grid 2×2, повышение контраста вторичного текста (WCAG AA), interactive-zone. Backend не менялся.
v1.5.4 — UX-доработка главной страницы: последовательная интерактивная зона (Этап 1: убран блок «Новые варианты», усилена кнопка navbar; Этап 2: пошаговый сценарий мини-задача → калькулятор → roadmap → CTA; Этап 3: roadmap в карточку результата, split-card с CTA; убран декоративный фон и рамки .interactive-zone). Backend не менялся.
v1.5.5 — улучшение структуры и конверсии главной страницы: устранение дублирования статистики, переписан блок преимуществ, улучшен индикатор интерактивной зоны. Backend не менялся.
v1.5.6 — персонализация воронки главной страницы: перенос `progress-section` и `guest-cta-section` после блока «Что есть на платформе». Backend не менялся.
v1.6.0 — визуальный редизайн главной страницы под светло-голубую тему: светлый фон, белые карточки, мягкие голубые рамки и тени, тёмный текст. Изменения только в CSS `start.html`. HTML, JS, backend, navbar, маршруты — не тронуты.
v1.6.1 — живой интерфейс главной страницы: hover-анимации карточек, scroll reveal с stagger, count-up анимации чисел, уплотнение интерактивной зоны. Изменения только в CSS и JS `start.html`. HTML-структура, backend, маршруты, бизнес-логика — не тронуты.
v1.6.2 — горизонтальная динамика интерактивной зоны: единые slide+fade переходы для обоих шагов (Задача→Готовность и Готовность→Маршрут), заполнение коннекторов stepper, overflow:hidden и minHeight-фикс. Изменения только в CSS и JS `start.html`. HTML, backend, маршруты, бизнес-логика — не тронуты.
v1.6.3 — усиление ценностного предложения главной страницы: счётчик видеоразборов в Hero, новый блок видео-превью, удаление блока новостей, рефрейминг блока обновлений с фокусом на студенте, ease → ease-out в reveal-анимациях. Изменения только в CSS и HTML `start.html`. JS, backend, маршруты, бизнес-логика — не тронуты.
v1.6.4 — визуальные и конверсионные улучшения главной страницы: HTML5-видеоплеер + боковые постеры в видеосекции, CTA-секция записи на занятие, плавающая карточка связи, система цветных полосок .card-stripe для update-card. Изменения только в `templates/start.html`. JS, backend, маршруты — не тронуты.

---

## Версии

### v1.6.4 — Визуальные и конверсионные улучшения главной страницы

**Дата:** 2026-06-18

**Описание:** Четыре независимых улучшения главной страницы. Центральные изменения: настоящий HTML5-видеоплеер в блоке видеоразборов, CTA-секция для записи на занятие и плавающая карточка связи — улучшают конверсию. Система `.card-stripe` добавляет семантическую цветовую маркировку карточек. Изменения только в `templates/start.html` (CSS + HTML). JS-бизнес-логика, backend, маршруты, navbar/logout/CSRF — не тронуты.

**Этап 1 — Доработка секции «Видеоразборы и уроки»:**
- Центральный элемент заменён: CSS-заглушка → настоящий `<video controls preload="metadata">`
- Источник: `/static/videos/platform-overview.mp4`; создана директория `static/videos/`
- Боковые карточки `.video-side`: CSS-градиенты → реальные `<img>` с `loading="lazy"`
  - `/static/images/video-preview-left.jpg` и `/static/images/video-preview-right.jpg`
  - Директория `static/images/` создана; файлы добавляются вручную
- Боковые постеры некликабельны (`pointer-events: none`); play-кружки и overlay удалены
- Фотографии в естественном цвете: убраны `filter: blur` и засветление
- Эффект наложения: центральное видео `z-index:2` визуально поверх боковых `z-index:1`
- Боковые постеры выглядывают слева, справа и 34px сверху над центральным видео
  (`padding-top: 34px` на `.video-stage`; боковые карточки с `top: 0` начинаются раньше)
- Исправлено обрезание постеров: удалён `overflow-x: clip` с секции;
  защита от горизонтального скролла — через `body { overflow-x: hidden }` (line 27)
- Адаптив ≤768px: боковые постеры скрываются (`display: none`)

**Этап 2 — CTA-секция «Готов начать подготовку?»:**
- Новая секция `.contact-cta-section` добавлена внутри `.main-wrap`
- Расположение: после блока «Что нового на платформе», перед `</div><!-- /.main-wrap -->`
- Карточка `.contact-cta-card`: декоративная цветная полоска сверху (`::before` gradient)
- Кнопки `<a target="_blank">`: Telegram (`https://t.me/Tyomkinss`) и MAX — совпадают с footer
- Reveal-анимация: `.reveal` на карточке; hover-переходы на кнопках
- Адаптив: 768px → уменьшенный padding и font-size; 480px → кнопки в столбик `flex-direction: column`

**Этап 3 — Плавающая карточка связи:**
- Элемент `.floating-contact`: `position: fixed; bottom: 28px; right: 24px; z-index: 50`
- Содержит Telegram и MAX ссылки, одинаковые с footer
- `z-index: 50` — ниже navbar (`z-index: 100`) и dropdown (`z-index: 200`)
- Нет JS — только CSS-анимации (`transform: translateY(-3px)` при hover)
- Расположен в DOM после `</footer>`, перед `<script>`
- Адаптив ≤768px: скрывается (`display: none`)

**Этап 4 — Система цветных полосок `.card-stripe`:**
- Базовый класс `.card-stripe`: `border-left: 3.5px solid var(--stripe, ...)`
- Модификаторы: `.card-stripe--blue`, `.card-stripe--purple`, `.card-stripe--green`
- Цвета: синий `rgba(37,99,235,0.85)`, фиолетовый `rgba(168,85,247,0.85)`, зелёный `rgba(34,197,94,0.85)`
- Применено только к трём `.update-card` в блоке «Что нового»:
  - «Уроки с видеоразборами» → `--blue` (контент/обучение)
  - «Статистика прогресса» → `--purple` (трекинг/прогресс)
  - «Начни с нуля» → `--green` (старт/достижение)
- Hover-фикс: `.update-card.card-stripe:hover { border-left-color: var(--stripe) }` —
  специфичность `(0,3,0)` перекрывает `(0,2,0)` у `.update-card:hover`, восстанавливает цвет полоски
- Другие блоки (feature-card, start-card, advantage-item, contact-cta-card и др.) — не тронуты

**Новые CSS-классы:**

| Класс | Описание |
|---|---|
| `.contact-cta-section` | Контейнер CTA-секции записи |
| `.contact-cta-card` | Карточка CTA с декоративной полоской сверху |
| `.contact-cta-badge` | Бейдж «Индивидуальные занятия» |
| `.contact-cta-title` | Заголовок CTA |
| `.contact-cta-text` | Описание |
| `.contact-cta-note` | Строка «Первое вводное занятие — бесплатно» |
| `.contact-cta-actions` | Flex-контейнер кнопок |
| `.contact-cta-btn` | Базовый стиль кнопки |
| `.contact-cta-btn-tg` | Кнопка Telegram |
| `.contact-cta-btn-max` | Кнопка MAX |
| `.floating-contact` | Плавающая карточка (`position: fixed`) |
| `.floating-contact-icon` | Иконка чата |
| `.floating-contact-title` | Заголовок карточки |
| `.floating-contact-text` | Описание |
| `.floating-contact-links` | Flex-контейнер ссылок |
| `.floating-contact-link` | Базовый стиль ссылки |
| `.floating-contact-link-tg` | Telegram-ссылка |
| `.floating-contact-link-max` | MAX-ссылка |
| `.card-stripe` | Базовый класс: `border-left` через CSS custom property |
| `.card-stripe--blue` | `--stripe: rgba(37,99,235,0.85)` |
| `.card-stripe--purple` | `--stripe: rgba(168,85,247,0.85)` |
| `.card-stripe--green` | `--stripe: rgba(34,197,94,0.85)` |

**Изменённые файлы:**

| Файл | Изменения |
|---|---|
| `templates/start.html` | CSS + HTML: все четыре этапа |
| `static/videos/` | Новая директория; `platform-overview.mp4` добавляется вручную |
| `static/images/` | Новая директория; `video-preview-left.jpg` и `video-preview-right.jpg` добавляются вручную |

**Результаты финального аудита:**

| Проверка | Статус |
|---|---|
| HTML5 `<video controls preload="metadata">` | ✅ |
| Источник `/static/videos/platform-overview.mp4` | ✅ |
| Боковые постеры: реальные `<img>`, естественные цвета | ✅ |
| Нет play-кружков и overlay на постерах | ✅ |
| Постеры некликабельны (`pointer-events: none`) | ✅ |
| Центральное видео поверх постеров (z-index 2 > 1) | ✅ |
| Постеры видны слева, справа и сверху (padding-top: 34px) | ✅ |
| Нет горизонтального скролла (`body overflow-x:hidden`) | ✅ |
| Адаптив ≤768px: боковые постеры скрыты | ✅ |
| CTA-секция после «Что нового», перед footer | ✅ |
| CTA Telegram = `t.me/Tyomkinss` (совпадает с footer) | ✅ |
| CTA MAX = полная ссылка (совпадает с footer) | ✅ |
| CTA reveal-анимация работает | ✅ |
| CTA адаптив 480px: кнопки в столбик | ✅ |
| Floating card: `position: fixed`, bottom-right | ✅ |
| Floating card: `z-index 50` < navbar `100` < dropdown `200` | ✅ |
| Floating card скрыта ≤768px | ✅ |
| `.card-stripe` архитектура через CSS custom property | ✅ |
| 3 update-card с полосками, остальные блоки не тронуты | ✅ |
| Hover-фикс сохраняет цвет полоски при наведении | ✅ |
| Backend не изменён | ✅ |
| JS не изменён | ✅ |

**Итого: 22/22 ✅**

**Не изменялось:** navbar, logout/CSRF, JS-функции `checkMiniTask`, `checkReadiness`, `updateIzProgress`, `goToStep2`, `goToStep3`, scroll reveal IIFE, count-up IIFE, backend `app.py`, маршруты, база данных.

---

### v1.6.3 — Усиление ценностного предложения главной страницы

**Дата:** 2026-06-18

**Описание:** Пять UX-изменений, направленных на повышение доверия и конверсии. Центральное изменение — новый блок видеоразборов, отвечающий на вопрос студента «как выглядит обучение?». Удалён устаревающий хардкодный блок новостей. Блок обновлений переписан с позиции ценности для ученика. Изменения только в `templates/start.html` (CSS + HTML). JS бизнес-логика, backend, маршруты, navbar/logout/CSRF — не тронуты.

**Этап 1 — Видеоразборы в Hero:**
- 4-я метрика: `100+ видеоразборов` добавлена в `.hero-mini-stats`
- CSS: `grid-template-columns: repeat(3, 1fr)` → `repeat(4, 1fr)`
- Адаптив 480px: `repeat(2, 1fr)` — сетка 2×2 на мобиле
- Count-up автоматически срабатывает (JS уже отслеживает `.hero-mini-stat-num`)

**Этап 2 — Удаление блока новостей:**
- Полностью удалена секция `<!-- НОВОСТИ -->` (HTML)
- Удалены CSS-правила: `.news-item`, `.news-item:last-child`, `.news-item.important`, `.news-date`, `.news-title-text`, `.news-description`
- Ни одного упоминания `news` не осталось в файле

**Этап 3 — Рефрейминг блока «Что нового»:**
- Карточка 1: «Новый редактор задач» → «Уроки с видеоразборами» — ценность для ученика
- Карточка 2: «Подготовка с нуля» → «Статистика твоего прогресса» — ценность для ученика
- Карточка 3: «Безопасность платформы» → «Начни с нуля — без пробелов» — ценность для ученика
- CSS, структура карточек, количество — не изменены

**Этап 4 — Новый блок видео-превью:**
- Новая секция `.video-preview-section` после `</div><!-- /.interactive-zone -->`
- 3 карточки `.video-card.reveal`: Задание 8, Задание 12, Задание 5
- Каждая карточка: gradient thumbnail + play-кнопка + badge + заголовок + длительность
- Hover: `translateY(-5px)` + усиление тени + scale(1.12) на play-кнопке
- Адаптив: 3 колонки → 2 колонки (≤900px) → 1 колонка (≤480px)
- Нет iframe, video, YouTube

**Этап 5 — Полировка reveal:**
- `.reveal`: `ease` → `ease-out` в `transition`
- Скорость (0.45s), translateY(22px), stagger — не изменены

**Новые CSS-классы:**

| Класс | Описание |
|---|---|
| `.video-preview-section` | Контейнер блока видео-превью |
| `.video-preview-grid` | Сетка 3 карточек |
| `.video-card` | Карточка-превью, hover |
| `.video-thumb` | Область aspect-ratio 16:9 |
| `.video-thumb-bg` | Gradient-фон thumbnail |
| `.video-thumb-1/2/3` | Индивидуальные градиенты карточек |
| `.video-thumb-deco` | Декоративный номер задания |
| `.video-play-btn` | Кнопка Play |
| `.video-play-icon` | CSS-треугольник play |
| `.video-card-body` | Контентная часть карточки |
| `.video-task-badge` | Бейдж «Задание N» |
| `.video-card-title` | Заголовок видео |
| `.video-card-meta` | Длительность с иконкой |
| `.video-preview-more` | Ссылка «Смотреть все уроки» |
| `.video-preview-link` | Стиль ссылки |

**Результаты финального аудита:**

| Проверка | Статус |
|---|---|
| Hero содержит 4 статистики | ✅ |
| Видеоразборы (100+) присутствуют в Hero | ✅ |
| Блок новостей полностью удалён | ✅ |
| Блок «Что нового» сохранён | ✅ |
| Карточки обновлений ориентированы на ученика | ✅ |
| Новый блок видеоразборов присутствует | ✅ |
| Блок видеоразборов между interactive-zone и features-section | ✅ |
| В блоке видеоразборов ровно 3 карточки | ✅ |
| Reveal-анимации: ease-out | ✅ |
| Hover-анимации на video-card | ✅ |
| Адаптив 900px: video-grid 2 колонки | ✅ |
| Адаптив 768px: нет регрессий | ✅ |
| Адаптив 480px: hero-mini-stats 2×2, video-grid 1 колонка | ✅ |
| Navbar не изменён | ✅ |
| Logout POST + CSRF не изменены | ✅ |
| JS интерактивной зоны не изменён | ✅ |
| Backend не изменён | ✅ |

**Итого: 17/17 ✅**

**Не изменялось:** `checkMiniTask`, `checkReadiness`, `goToStep2`, `goToStep3`, `updateIzProgress`, scroll reveal IIFE, count-up IIFE, `app.py`, все маршруты, navbar, logout, CSRF.

---

### v1.6.2 — Горизонтальная динамика интерактивной зоны

**Дата:** 2026-06-18

**Описание:** Переход от fade-анимации к единым горизонтальным slide+fade переходам во всей интерактивной зоне. Оба шага теперь выглядят единообразно: уходящая карточка уезжает влево, входящая приезжает справа. Добавлены анимированные коннекторы stepper, защита от горизонтального скролла, фикс скачка высоты при появлении roadmap. Изменения только в `templates/start.html` (CSS + JS). HTML-структура, `checkMiniTask`, `checkReadiness`, backend, маршруты, navbar/logout/CSRF — не тронуты.

**Переход Задача → Готовность (goToStep2):**
- Minitask: добавлен CSS-класс `.iz-slide-out-left` (`translateX(-48px) + opacity:0`, 0.26s ease-in)
- Calculator подготавливается до начала анимации: `display:block`, `opacity:0`, `translateX(48px)`, `transition:none`
- После 280ms calculator въезжает на место: `transition 0.32s ease-out`, `opacity:1`, `translateX(0)`
- Работает через double rAF — calculator был подготовлен за 280ms, браузер уже отрендерил его начальное состояние

**Переход Готовность → Маршрут (goToStep3):**
- Calculator получает тот же `.iz-slide-out-left` (зеркально с minitask)
- Roadmap и CTA подготавливаются внутри setTimeout: `display:block`, `opacity:0`, `translateX(48px)`
- `void roadmap.offsetHeight` — принудительный layout flush, гарантирует фиксацию `translateX(48px)` до запуска transition
- Roadmap: `transition 0.32s ease-out`, `opacity:1`, `translateX(0)`
- CTA: то же с задержкой `0.06s`
- `zone.style.minHeight` зафиксирован перед анимацией → снимается через 520ms

**Индикатор прогресса — коннекторы:**
- `updateIzProgress(step)` расширена: добавлен второй forEach по `.iz-step-connector`
- Коннектор i заполняется при `step >= i + 2`
- CSS: `.iz-step-connector { position: relative; overflow: hidden }` + `::after { scaleX(0→1) }` с `transition 0.38s ease delay 0.12s`
- `.iz-connector-filled::after { scaleX(1) }` — заливка слева направо

**Индикатор прогресса — точки:**
- `.iz-dot.iz-dot-active` scale: `1.2` → `1.25`

**Защита от горизонтального скролла:**
- `overflow: hidden` добавлен к `.interactive-zone` (body уже имел `overflow-x: hidden`)

**Reduced-motion:**
- CSS `@media (prefers-reduced-motion: reduce)`: `.iz-slide-out-left { transform: none !important }`, мгновенный коннектор, упрощённый dot
- JS: `window.matchMedia('(prefers-reduced-motion: reduce)').matches` — при `true` transform не применяется, только opacity fade

**Новые CSS-классы:**

| Класс / правило | Описание |
|---|---|
| `.iz-slide-out-left` | Уход влево: `translateX(-48px) + opacity:0`, `!important` |
| `.iz-step-connector::after` | Псевдо-элемент заливки коннектора |
| `.iz-step-connector.iz-connector-filled::after` | Финальное состояние: `scaleX(1)` |
| `.iz-step-connector` (обновлён) | Добавлено `position: relative; overflow: hidden` |
| `.iz-dot.iz-dot-active` (обновлён) | scale `1.2` → `1.25` |
| `.interactive-zone` (обновлён) | Добавлено `overflow: hidden` |
| `@media (prefers-reduced-motion: reduce)` | Новый блок |

**Результаты проверок:**

| Проверка | Статус |
|---|---|
| Переход 1→2: minitask уходит влево | ✅ |
| Переход 1→2: calculator приезжает справа | ✅ |
| Переход 2→3: calculator уходит влево | ✅ |
| Переход 2→3: roadmap приезжает справа | ✅ |
| CTA появляется вместе с roadmap | ✅ |
| Коннектор 1→2 заполняется при переходе | ✅ |
| Коннектор 2→3 заполняется при переходе | ✅ |
| Нет горизонтального скролла (desktop + mobile) | ✅ |
| Нет скачка высоты при появлении roadmap | ✅ |
| prefers-reduced-motion: только opacity fade | ✅ |
| checkMiniTask() не изменён | ✅ |
| checkReadiness() не изменён | ✅ |

**Итого: 12/12 ✅**

**Не изменялось:** HTML-структура интерактивной зоны, `checkMiniTask`, `checkReadiness`, логика показа кнопок, scroll reveal (IIFE), count-up (IIFE), backend `app.py`, маршруты, navbar, logout, CSRF.

---

### v1.6.1 — Живой интерфейс главной страницы

**Дата:** 2026-06-18

**Описание:** Четыре этапа улучшения визуального восприятия и микро-взаимодействий на главной странице. Ориентир — современные EdTech и SaaS платформы. Изменения только в `templates/start.html` (CSS + JS). HTML-структура, JS-сценарий интерактивной зоны, backend, маршруты, база данных — не тронуты.

**Этап 1 — Hover-анимации карточек:**

| Компонент | Эффект |
|---|---|
| `.start-card` | `translateY(-4px)` + усиленная тень |
| `.update-card` | `translateY(-3px)` + тень |
| `.progress-card` | `translateY(-3px)` + тень |
| `.guest-cta-card` | `translateY(-4px)` + тень |
| `.advantage-item` | `translateY(-2px)` + bg |
| `.feature-card` | уже был, не изменён |

Также исправлены level-цвета start-card для WCAG AA контраста (`#38bdf8`→`#0284c7`, `#4ade80`→`#16a34a`).

**Этап 2 — Уплотнение интерактивной зоны:**

| Параметр | До | После |
|---|---|---|
| `.interactive-zone padding` | `64px 0` | `36px 0` |
| `.iz-progress margin-bottom` | `44px` | `22px` |
| `.iz-dot` размер | `10×10px` | `14×14px` |
| `.iz-step-connector` | `52px × 1px` | `72px × 2px` |
| `.minitask-card / .calculator-card max-width` | `580px` | `680px` |
| `.interactive-zone .section-heading margin-bottom` | `36px` (глобальное) | `20px` (локальный override) |

Убрано ~100px мёртвого пространства. JS-сценарий не тронут.

**Этап 3 — Scroll Reveal:**

- CSS: класс `.reveal` (opacity:0 + translateY:22px → visible). Transition 0.45s ease.
- CSS: stagger-задержки 80–240ms для start-card, feature-card, advantage-item, update-card, progress-card.
- JS: IIFE с IntersectionObserver, threshold 0.1, rootMargin -24px снизу. Fallback для браузеров без IO.
- Reveal добавлен: section-heading'и, start-card ×3, iz-progress, minitask-card, advantage-item ×4, feature-card ×4, progress-header, progress-card ×3, guest-cta-card, update-card ×3, news-feed.
- Reveal НЕ добавлен: Hero (выше fold), navbar, calculator-section, roadmap-section, iz-cta (управляются JS display:none/block).

**Этап 4 — Count-up анимации:**

- JS: отдельный IntersectionObserver, threshold 0.7. Regex `/^\d+\+?$/` — только чистые числа.
- Анимирует: `hero-mini-stat-num` ("1200+", "27", "90+") и `progress-num` ("145", "90"). Пропускает "9 / 27".
- easeOutCubic за 900ms. Финальное значение точно восстанавливается.

**Результаты проверок:**

| Компонент | Этап | Статус |
|---|---|---|
| `.start-card` hover `translateY(-4px)` + тень | 1 | ✅ |
| `.update-card` hover `translateY(-3px)` + тень | 1 | ✅ |
| `.progress-card` hover `translateY(-3px)` + тень | 1 | ✅ |
| `.guest-cta-card` hover `translateY(-4px)` + тень | 1 | ✅ |
| `.advantage-item` hover `translateY(-2px)` + bg | 1 | ✅ |
| Level-цвета WCAG AA на белом фоне | 1 | ✅ |
| Нет скачков layout (transform, не margin) | 1 | ✅ |
| Нет горизонтального скролла | 1 | ✅ |
| Navbar не затронут | 1–4 | ✅ |
| `.interactive-zone` padding 64→36px | 2 | ✅ |
| `.iz-progress` margin-bottom 44→22px | 2 | ✅ |
| `.iz-dot` 10→14px; connector 52→72px, 1→2px | 2 | ✅ |
| Карточки 580→680px, без поломки адаптива 480px | 2 | ✅ |
| Мини-задача работает корректно | 2 | ✅ |
| Калькулятор → roadmap → CTA: сценарий не нарушен | 2 | ✅ |
| Scroll reveal: IntersectionObserver, fallback | 3 | ✅ |
| Нет секций, которые остаются невидимыми | 3 | ✅ |
| Stagger: start-card / feature / advantage / update / progress | 3 | ✅ |
| Calculator/roadmap/iz-cta без `reveal` — нет конфликта с JS | 3 | ✅ |
| Count-up: "1200+", "27", "90+", "145", "90" | 4 | ✅ |
| "9 / 27" корректно пропускается regex'ом | 4 | ✅ |
| Финальные значения точно совпадают с исходными | 4 | ✅ |
| Нет ошибок JS в консоли | 3–4 | ✅ |

**Итого: 23/23 ✅**

**Не изменялось:** navbar, logout/CSRF, HTML-разметка, JS-функции `checkMiniTask`, `checkReadiness`, `updateIzProgress`, `goToStep2`, `goToStep3`, backend `app.py`, маршруты, база данных.

---

### v1.6.0 — Визуальный редизайн главной страницы (светлая тема)

**Дата:** 2026-06-17

**Описание:** Переход главной страницы от тёмной «геймерской» стилистики к светло-голубому образовательному стилю. Изменения затронули только CSS в `templates/start.html` (~55 селекторов). HTML-структура, JS, backend, navbar, маршруты и CSRF — не тронуты.

**Изменения в CSS `start.html`:**

| Область | Было (тёмная тема) | Стало (светлая тема) |
|---|---|---|
| `body { background }` | `#111827` | градиент `#eaf6ff → #f5fbff → #eef8ff` |
| `body { color }` | `#e2e8f0` | `#0f172a` |
| Фоны карточек | `rgba(255,255,255,0.04–0.06)` | `rgba(255,255,255,0.92–0.96)` |
| Рамки карточек | `rgba(255,255,255,0.08–0.11)` | `rgba(37,99,235,0.12–0.18)` |
| Тени карточек | отсутствуют | `0 N px M px rgba(37,99,235,0.07–0.12)` |
| Основной текст в карточках | `#e2e8f0` | `#0f172a` |
| Вторичный текст | `#94a3b8` | `#475569` |
| Числа progress-card | `#e2e8f0` | `#1e40af` (синий акцент) |
| Состояния correct/incorrect | неоновые `#86efac / #fca5a5` | пастельные `#166534 / #991b1b` |
| Акцент roadmap-circle | `rgba(56,189,248,0.1)` / `#38bdf8` | `rgba(219,234,254,0.85)` / `#2563eb` |

**Адаптированные компоненты (7 этапов):**
1. Глобальные токены: `body`, `hero-tagline/desc`, `section-heading`, `btn-secondary`, `section-title`, `features-heading`
2. Hero: `hero-mockup`, `mockup-topbar/body/choice/result/progress`, `hero-mini-stat`
3. Start-flow: `start-card`, `start-card-btn-1/2/3`, `start-arrow`
4. Интерактивная зона: `iz-dot/connector`, `iz-next-btn`, `minitask-card`, `minitask-option/result`, `calculator-card`, `calc-option/result`, `roadmap-section`, `roadmap-circle/connector/step`, `iz-cta`, `iz-result-header/check`
5. Advantages / Features / Updates / News: `advantages-panel`, `advantage-item`, `feature-card`, `update-card`, `news-item`
6. Progress / Guest CTA: `progress-card`, `progress-num/label`, `guest-cta-card`, `guest-cta-title/desc`
7. Глобальная проверка: `section-tag-blue/purple`, `footer-border`, `advantage-item` (media query), `minitask-question`

**Не изменялось:** navbar, logout/CSRF, HTML-разметка, JS-функции (`checkMiniTask`, `checkReadiness`, `updateIzProgress`, `goToStep2`, `goToStep3`), backend `app.py`, маршруты, база данных.

**Визуальный итог:** страница стала светлее, дружелюбнее и значительно ближе к облику образовательной платформы. Исчезла «геймерская» тёмная стилистика; пользователи видят чистые белые карточки на небесно-голубом фоне с сохранёнными цветовыми акцентами (синий/фиолетовый/зелёный).

---

### v1.0.0 — Базовая платформа

Первоначальный запуск платформы.

**Функционал:**
- Система авторизации (вход, регистрация с паролем сайта)
- Варианты ЕГЭ в старом формате (список задач в JSON)
- Проверка ответов (одиночный ответ, два ответа, таблица)
- Таймер в режиме решения
- Профиль с аватаром и статистикой
- Теория по заданиям с изображениями и видео
- Подготовительные уроки
- Базовая админ-панель

**Известные проблемы на момент выпуска:**
- Секреты захардкожены в `app.py`
- `debug=True` в продакшене
- Отсутствие CSRF-защиты
- Уязвимость в `/api/theory/save` (нет проверки is_admin)

---

### v1.1.0 — Новый формат вариантов и база задач

**Добавлено:**
- Новый формат вариантов (словарь ссылок на базу задач вместо полных объектов)
- База задач в `tasks/task_XX/tasks.json`
- Конструктор вариантов из базы (`/constructor_from_base`)
- Редактор теории (`/constructor_theory`)
- Редактор вариантов (`/constructor_editor`)
- Поддержка обоих форматов в `load_variant_tasks()`
- Экзаменационный режим (`/exam/<variant_num>`)
- Выбор режима (`/choose-mode/<variant_num>`)
- Управление доступом к урокам и теории через админку
- Статистика решений попыток с деталями

**Изменения в архитектуре:**
- `task["_source_task_num"]` — маркер нового формата для маршрутизации изображений
- Два маршрута для изображений: `task_images` (новый) и `variant_images` (старый)

---

### v1.2.0 — Аудит безопасности и исправление уязвимостей

**Дата:** 2026-06-15

**Исправленные проблемы:**

#### P0-1: Уязвимость /api/theory/save (КРИТИЧЕСКАЯ)
- **Проблема:** Маршрут `POST /api/theory/save` не проверял `is_admin`.
  Любой авторизованный пользователь мог изменять теоретические материалы.
- **Исправление:** Добавлена проверка `is_admin == 1` перед сохранением.
- **Файл:** `app.py`, маршрут `/api/theory/save`

#### P0-2: debug=True в продакшене (КРИТИЧЕСКАЯ)
- **Проблема:** `app.run(debug=True)` — интерактивный отладчик Werkzeug
  доступен через браузер, раскрывает код и даёт выполнение произвольного Python.
- **Исправление:** `app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")`
- **Файл:** `app.py`, конец файла

#### P0-3: Секреты в коде (КРИТИЧЕСКАЯ)
- **Проблема:** `SECRET_KEY`, `SITE_PASSWORD`, логин и пароль администратора
  хранились захардкожено в `app.py`.
- **Исправление:**
  - Добавлен `python-dotenv==1.0.0`
  - Создан `.env.example` с документацией
  - `.env` уже был в `.gitignore`
  - Проверка наличия всех 4 обязательных переменных при старте
  - Паттерн `os.environ.get(key) or default` для пустых строк из `.env`
- **Файлы:** `app.py`, `.env.example`, `requirements.txt`

#### P0-4: Отсутствие CSRF-защиты (КРИТИЧЕСКАЯ)
Внедрение проводилось в 3 этапа.

**Этап 1 — Инфраструктура:**
- Добавлен `Flask-WTF==1.2.1` в `requirements.txt`
- `CSRFProtect(app)` — глобальная защита всех POST-маршрутов
- `WTF_CSRF_SECRET_KEY` настроен через `os.environ.get() or SECRET_KEY`
- Обработчик `CSRFError`: JSON-ответ для API, HTML-страница для форм
- Создан шаблон `csrf_error.html` в стиле проекта
- **Файлы:** `app.py`, `templates/csrf_error.html`, `requirements.txt`

**Этап 2 — HTML-формы (9 форм):**
Добавлен `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`

| Файл | Форма |
|---|---|
| login.html | Вход |
| register.html | Регистрация |
| profile.html | Загрузка аватара |
| reshenie.html | Проверка ответа (в цикле) |
| admin_panel.html | Удаление пользователя (в цикле) |
| admin_tasks_view.html | Удаление задачи (в цикле) |
| admin_task_form.html | Создание/редактирование задачи |
| admin_user_stats.html | Переключение доступа к уроку (в цикле) |
| admin_user_stats.html | Переключение доступа к теории (в цикле) |

Примечание: `teoria_zadanie.html` — форма без `method="POST"`, токен добавлен
как заготовка для Этапа 3.

**Этап 3 — JavaScript fetch (7 запросов):**
Добавлен заголовок `'X-CSRFToken': '{{ csrf_token() }}'`

| Файл | Endpoint |
|---|---|
| reshenie.html | POST /save_results/ |
| exam.html | POST /finish_exam/ |
| stats.html | POST /clear_stats |
| teoria_zadanie.html | POST /check_theory_answer |
| preparation_lesson.html | POST /check_lesson_task |
| constructor_from_base.html | POST /api/variants/save |
| constructor_theory.html | POST /api/theory/save |

FormData-запрос (`/check/`) уже защищён через hidden input — X-CSRFToken не добавлялся.

#### P1-1: Ошибка маршрута в choose_mode.html (ВЫСОКИЙ)
- **Проблема:** Кнопка "Обычный режим" вела на `/tasks/{{ variant_num }}`
  вместо `/solve/{{ variant_num }}`.
- **Исправление:** Исправлен `href` в кнопке.
- **Файл:** `templates/choose_mode.html`

#### P1-2: Неверные ссылки на варианты в start.html (СРЕДНИЙ)
- **Проблема:** Ссылки на варианты 3, 4, 5 на главной странице вели
  на несуществующие маршруты.
- **Исправление:** Исправлены href на `/choose-mode/3`, `/choose-mode/4`, `/choose-mode/5`.
- **Файл:** `templates/start.html`

#### P1-3: "undefined" в заголовках заданий (СРЕДНИЙ)
- **Проблема:** Варианты нового формата не имеют поля `title`.
  Шаблоны выводили `undefined` или пустую строку вместо "Задание №X".
- **Исправление:** Добавлен fallback `task.title or 'Задание №' ~ task.id`
  во всех шаблонах. Аналогично для JS: `task.title || 'Задание №' + task.id`.
- **Файлы:** `reshenie.html`, `exam.html`, `results.html`

---

### v1.2.1 — Аудит прав доступа (P1/P2)

**Дата:** 2026-06-15

Проведён аудит всех 18 маршрутов, изменяющих данные. Найдено и исправлено 3 проблемы приоритетов P1 и P2.

#### P1: /api/variants/save без проверки is_admin (ВЫСОКИЙ)
- **Проблема:** Маршрут `POST /api/variants/save` проверял только наличие сессии.
  Любой авторизованный пользователь мог создавать новые варианты ЕГЭ на диске
  и писать в таблицу `task_usage`.
- **Исправление:** Добавлена проверка `is_admin == 1` после проверки сессии.
  Обычный пользователь получает `403 Forbidden`.
- **Файл:** `app.py`, маршрут `/api/variants/save`

#### P2-1: /api/variant/preview без проверки is_admin (СРЕДНИЙ)
- **Проблема:** Маршрут `POST /api/variant/preview` проверял только наличие сессии.
  Любой авторизованный пользователь получал полные объекты задач включая поля
  `correct_answer`, `answers`, `answer_grid` — фактически все правильные ответы.
- **Исправление:** Добавлена проверка `is_admin == 1`. Обычный пользователь
  получает `403 Forbidden`.
- **Файл:** `app.py`, маршрут `/api/variant/preview`

#### P2-2: GET /logout уязвим к CSRF (СРЕДНИЙ)
- **Проблема:** `GET /logout` не защищён CSRF (Flask-WTF защищает только POST).
  Атакующий мог встроить `<img src="/logout">` на сторонней странице и
  принудительно завершить сессию пользователя.
- **Исправление:**
  - Маршрут переведён на `POST /logout`.
  - В `start.html` и `profile.html` ссылки `<a href="/logout">` заменены
    на `<form method="POST">` с CSRF-токеном и стилизованной кнопкой.
  - Стиль кнопки визуально совпадает с прежними ссылками (те же CSS-классы).
- **Файлы:** `app.py`, `templates/start.html`, `templates/profile.html`

**Проверка (автотест):**

| Запрос | Ожидание | Результат |
|---|---|---|
| `GET /logout` (авторизован) | 405 | 405 ✅ |
| `POST /logout` | 302 → /login | 302 ✅ |
| `POST /api/variants/save` (user) | 403 | 403 ✅ |
| `POST /api/variants/save` (admin) | не 403 | 400 (нет 27 заданий) ✅ |
| `POST /api/variant/preview` (user) | 403 | 403 ✅ |
| `POST /api/variant/preview` (admin) | 200 | 200 ✅ |

**Не исправлено (P3, отложено):**
- `POST /clear_stats` — нет явного guard в теле, `except` раскрывает ошибку
- `POST /save_results` и `POST /finish_exam` — нет ограничения числа сохранений

---

### v1.2.2 — Исправление Stored XSS в admin_panel.html

**Дата:** 2026-06-15

Проведён аудит XSS и небезопасного рендеринга. Найдено 3 проблемы. Исправлена критическая (#1).

#### XSS-1 (КРИТИЧЕСКИЙ): Stored XSS через имя пользователя в onclick
- **Проблема:** `admin_panel.html`, строка 193:
  ```
  onclick="return confirm('Удалить пользователя {{ user.username }}?')"
  ```
  `username` попадал в тело JavaScript-строкового литерала. Jinja2 экранирует `'` в `&#39;`,
  но HTML-парсер декодирует `&#39;` обратно в `'` до передачи в JS-движок. Любой пользователь
  мог зарегистрироваться с именем `'); alert(document.cookie);//` и получить выполнение
  произвольного JS в браузере администратора при открытии `/admin`.
- **Исправление:** `username` перенесён в `data-username` атрибут кнопки.
  JS читает значение через `this.dataset.username` — как строку данных, а не как код:
  ```html
  <button data-username="{{ user.username }}"
          onclick="return confirm('Удалить пользователя ' + this.dataset.username + '?')">
  ```
  Строковая конкатенация `+` не выполняет код. Payload отображается как текст в диалоге.
- **Файл:** `templates/admin_panel.html`, строка 193

**Не исправлено (отложено на следующий этап):**
- XSS-3 (СРЕДНИЙ): `| safe` в `preparation_lesson.html` (строки 357, 390) —
  рендерит описания уроков без экранирования. Источник — admin-controlled lesson JSON.

---

### v1.2.3 — Безопасный replace_markers (XSS-2)

**Дата:** 2026-06-15

#### XSS-2 (ВЫСОКИЙ): уязвимая ветка в replace_markers
- **Проблема:** `app.py`, строки 97–98 (было):
  ```python
  if "<sup>" in text or "<sub>" in text or "<b>" in text or "<i>" in text:
      return markupsafe.Markup(text)   # текст не экранировался
  ```
  Если строка содержала хотя бы один из четырёх разрешённых тегов (`<sup>`, `<sub>`,
  `<b>`, `<i>`), весь текст целиком помечался как доверенный HTML без экранирования.
  Любой другой тег в той же строке (`<script>`, `<img onerror=...>`, `<iframe>`)
  передавался браузеру как сырой HTML. Источник данных — task/theory JSON,
  редактируемый администратором.

- **Исправление:** Уязвимая ветка удалена. Обе старые ветки (сырые HTML-теги и
  BBCode-маркеры `[sup]` / `[sub]` / `[b]` / `[i]`) объединены в единый безопасный
  pipeline:
  1. Все вхождения обоих форматов (`<sup>`, `[sup]` и т.д.) заменяются на нейтральные
     плейсхолдеры `___SUP___` и т.п. — до экранирования.
  2. `str(markupsafe.escape(text))` экранирует весь оставшийся HTML (`<script>`,
     `<img>`, `onerror`, `<iframe>` и любые другие теги и атрибуты).
  3. Только плейсхолдеры из whitelist восстанавливаются в HTML-теги.
     `str()` перед `.replace()` обязателен: замена на объекте `Markup` автоматически
     экранировала бы HTML-строки при подстановке.
  - **Whitelist:** `sup`, `sub`, `b`, `i` (открывающие и закрывающие).
  - **Файл:** `app.py`, функция `replace_markers`

- **Проверка (12 тестов):**

| Входная строка | Результат до | Результат после |
|---|---|---|
| `4<sup>2020</sup>` (task_14) | `4<sup>2020</sup>` ✅ | `4<sup>2020</sup>` ✅ |
| `x<sup>2</sup>` (task_15) | `x<sup>2</sup>` ✅ | `x<sup>2</sup>` ✅ |
| `<b>Пример</b>` (theory_26) | `<b>Пример</b>` ✅ | `<b>Пример</b>` ✅ |
| `<i>код</i>` (theory_26) | `<i>код</i>` ✅ | `<i>код</i>` ✅ |
| `[sup]2[/sup]` (BBCode) | `<sup>2</sup>` ✅ | `<sup>2</sup>` ✅ |
| `<sup>1</sup><script>alert(1)</script>` | ❌ XSS | `<sup>1</sup>&lt;script&gt;…` ✅ |
| `<img src=x onerror=alert(1)>` | ❌ XSS | `&lt;img src=x onerror=alert(1)&gt;` ✅ |
| `<b>текст</b><img src=x onerror=alert(1)>` | ❌ XSS | `<b>текст</b>&lt;img…&gt;` ✅ |

  Регрессий нет: в реальных JSON-файлах используются только теги из whitelist.
  Сканирование 27 tasks.json и 4 theory.json не выявило нежелательных тегов.

---

### v1.2.4 — Исправление XSS-3 (preparation_lesson.html)

**Дата:** 2026-06-15

#### XSS-3 (СРЕДНИЙ): `| safe` в preparation_lesson.html

- **Проблема:** Строки 357 и 390 шаблона `preparation_lesson.html` использовали
  фильтр `| safe` для рендеринга описаний из `urok_XX.json`:
  ```jinja
  {{ para | safe }}   {# theory.description #}
  {{ para | safe }}   {# practice.tasks[].description #}
  ```
  Любой тег в lesson JSON (`<script>`, `<img onerror=...>`, `<svg onload=...>`,
  `<iframe>`) передавался браузеру без экранирования. Изменить содержимое уроков
  можно только через файловую систему сервера — эксплойт требует серверного доступа,
  поэтому приоритет ниже XSS-1 и XSS-2, но уязвимость реальная.

- **Исправление:** Оба `| safe` заменены на `| replace_markers` (уже исправленный
  в v1.2.3 whitelist-pipeline для `sup`/`sub`/`b`/`i`):
  ```jinja
  {{ para | replace_markers }}   {# строка 357, theory.description #}
  {{ para | replace_markers }}   {# строка 390, practice.tasks[].description #}
  ```
  - `<b>`, `<i>`, `<sup>`, `<sub>` — сохраняются (входят в whitelist).
  - `<script>`, `<img>`, `<iframe>`, `<svg>`, атрибуты `onerror`/`onload` и любые
    другие теги — экранируются в `&lt;...&gt;`.
  - **Файл:** `templates/preparation_lesson.html`

- **Проверка реального контента (urok_01.json):**

| Строка | Вход | Выход |
|---|---|---|
| theory[0] | `<b>Система счисления</b> — …` | `<b>Система счисления</b> — …` ✅ |
| theory[1] | `… <b>позиционные</b> и <b>непозиционные</b>…` | теги `<b>` сохранены ✅ |
| theory[2] | `<b>Основание…</b> — это…` | `<b>` сохранён ✅ |
| theory[3–5] | plain text | без изменений ✅ |
| practice[0–3] | plain text | без изменений ✅ |

- **XSS-векторы (6 проверок):**

| Вектор | Выход |
|---|---|
| `<script>alert(document.cookie)</script>` | `&lt;script&gt;…&lt;/script&gt;` ✅ |
| `<img src=x onerror=alert(1)>` | `&lt;img src=x onerror=alert(1)&gt;` ✅ |
| `<b>bold</b><script>alert(1)</script>` | `<b>bold</b>&lt;script&gt;…` ✅ |
| `<iframe src="evil.com">` | `&lt;iframe src=…&gt;` ✅ |
| `<b>bold</b><img src=x onerror=fetch(…)>` | `<b>bold</b>&lt;img…&gt;` ✅ |
| `<svg onload=alert(1)>` | `&lt;svg onload=alert(1)&gt;` ✅ |

---

### v1.2.5 — P3-аудит Этап 1: auth-guard и валидация variant_num

**Дата:** 2026-06-16

Устранены три низкорисковые проблемы, выявленные в P3-аудите маршрутов `clear_stats`,
`save_results`, `finish_exam`. Double-submit защита отложена отдельным этапом (P3 Этап 2).

#### P3-A: Раскрытие внутренних ошибок в /clear_stats (LOW)
- **Проблема:** `except Exception as e` возвращал `str(e)` в JSON-ответе, раскрывая
  имена ключей сессии или сообщения SQLite.
- **Исправление:** `str(e)` заменён на generic-строку `"Не удалось очистить статистику"`.
  Исключение поглощается (`except Exception` без аргумента).
- **Файл:** `app.py`, маршрут `/clear_stats`

#### P3-B: Неполная очистка — осиротевшие записи в user_task_answers (LOW)
- **Проблема:** `/clear_stats` удалял только строки из `user_results`.
  `user_task_answers` не имеет FK-каскада на `user_results`, поэтому детальные
  ответы пользователя оставались в БД после очистки статистики.
- **Исправление:** Перед DELETE из `user_results` добавлен DELETE из `user_task_answers`
  по `user_id`. Порядок: сначала детали, потом заголовки.
- **Файл:** `app.py`, маршрут `/clear_stats`

#### P3-C + P3-F + P3-G: Явные auth-guard во всех трёх маршрутах (VERY LOW)
- **Проблема:** Все три маршрута опирались исключительно на `before_request` для
  проверки авторизации. В `clear_stats` отсутствующий `user_id` в сессии попадал
  в `try/except` и раскрывался через `str(e)`. В `finish_exam` — `session["user_id"]`
  передавался прямо в аргумент функции без переменной, что затрудняло отладку.
- **Исправление:**
  - Добавлен явный `if "user_id" not in session: return jsonify(...), 401` в начало
    каждого из трёх маршрутов.
  - `user_id = session["user_id"]` вынесен в переменную в `finish_exam` (было прямо
    в аргументе вызова `save_user_result`).
- **Файлы:** `app.py`, маршруты `/clear_stats`, `/save_results`, `/finish_exam`

#### P3-E: Нет валидации variant_num → мусорные записи (LOW)
- **Проблема:** `load_tasks()` для несуществующего варианта возвращает `[]`.
  Обработчики не проверяли результат и сохраняли строку `score=0` в `user_results`
  для любого `variant_num`, включая несуществующие (например, `variant_num=9999`).
- **Исправление:** После `load_tasks(variant_num)` добавлена проверка:
  `if not tasks: return jsonify({"success": False, "error": "Вариант не найден"}), 404`
- **Файлы:** `app.py`, маршруты `/save_results`, `/finish_exam`

**Формат успешных ответов не изменился:**
- `save_results`: `{"success": true, "message": "Результаты сохранены!"}` — 200
- `finish_exam`: `{"success": true, "redirect": "/results/<n>"}` — 200
- `clear_stats`: `{"success": true, "message": "Ваша статистика очищена"}` — 200

**Проверка (11 тестов, Flask test client):**

| Сценарий | Маршрут | Ожидание | Результат |
|---|---|---|---|
| Неавторизованный (before_request) | все три | 302 → /login | ✅ 302 |
| Inner guard без сессии | clear_stats | 401 JSON | ✅ 401 |
| Inner guard без сессии | save_results | 401 JSON | ✅ 401 |
| Inner guard без сессии | finish_exam | 401 JSON | ✅ 401 |
| variant_num=9999 | save_results | 404 JSON | ✅ 404 |
| variant_num=9999 | finish_exam | 404 JSON | ✅ 404 |
| variant_num=1, формат ответа | save_results | 200 `{success, message}` | ✅ 200 |
| variant_num=1, формат ответа | finish_exam | 200 `{success, redirect}` | ✅ 200 |

**Не исправлено (P3 Этап 2 — отложено):**
- Double-submit: `/save_results` и `/finish_exam` по-прежнему принимают неограниченное
  число вызовов и создают новую строку в `user_results` при каждом запросе.

---

### v1.2.6 — Исправление D-1: каскадное удаление пользователя

**Дата:** 2026-06-16

#### D-1: delete_user() не удалял данные из 5 таблиц (LOW, целостность данных)
- **Проблема:** `POST /admin/delete_user/<user_id>` удалял записи только из двух таблиц
  (`users` и `user_results`). Данные пользователя в `user_task_answers`,
  `user_lesson_progress`, `user_theory_progress`, `user_lesson_access`,
  `user_theory_access` оставались в БД как осиротевшие строки с несуществующим `user_id`.
  Дополнительно: `users` удалялась первой, до дочерних таблиц — при включении
  `PRAGMA foreign_keys = ON` это вызвало бы FK-ошибку.

- **Исправление:** Блок DELETE заменён на полный каскад в правильном порядке
  (дочерние таблицы → родительская):
  1. `DELETE FROM user_task_answers WHERE user_id = ?`
  2. `DELETE FROM user_results WHERE user_id = ?`
  3. `DELETE FROM user_lesson_progress WHERE user_id = ?`
  4. `DELETE FROM user_theory_progress WHERE user_id = ?`
  5. `DELETE FROM user_lesson_access WHERE user_id = ?`
  6. `DELETE FROM user_theory_access WHERE user_id = ?`
  7. `DELETE FROM users WHERE id = ?` ← последней

- **Файл:** `app.py`, строки 2158–2167, маршрут `/admin/delete_user/<user_id>`

- **Проверка (тест с временной БД):**

| Таблица | До удаления | После удаления |
|---|---|---|
| `users` | 1 | 0 ✅ |
| `user_results` | 1 | 0 ✅ |
| `user_task_answers` | 1 | 0 ✅ |
| `user_lesson_progress` | 1 | 0 ✅ |
| `user_theory_progress` | 1 | 0 ✅ |
| `user_lesson_access` | 1 | 0 ✅ |
| `user_theory_access` | 1 | 0 ✅ |

  HTTP-ответ: `302 → /admin`. Flash-сообщения и redirect не изменились. Регрессий нет.

---

### v1.2.7 — Исправление D-2 и D-3: валидация task_id и generic-ошибки

**Дата:** 2026-06-16

#### D-2: task_id из JSON не валидируется как int (LOW, целостность данных)

- **Проблема:** В `POST /api/variants/save` значение `task_id = ref.get("task_id")`
  бралось из тела запроса без проверки типа и передавалось прямо в INSERT.
  SQL-инъекция невозможна (`?`-плейсхолдер), но в `task_usage` могло попасть
  `None` (IntegrityError → partial failure), строка или float вместо int.
  Дополнительно: JSON-файл варианта писался на диск ДО INSERT в `task_usage`,
  поэтому при ошибке вариант оказывался создан, а `task_usage` — пустым
  (неатомарная операция, вариант существовал при 500 в ответе).

- **Исправление:** Добавлен предварительный цикл валидации `validated_tasks`
  **до** `os.makedirs()` и записи JSON-файла. Финальная реализация:
  ```python
  validated_tasks = {}
  for position, ref in tasks_refs.items():
      try:
          task_num_v = int(position)       # position — всегда строка (ключ JSON-объекта)
          task_id_raw = ref.get("task_id")
          if isinstance(task_id_raw, (bool, float)):
              raise TypeError              # bool/float — явно отклоняются до int()
          task_id_v = int(task_id_raw)    # int→int, "5"→5; None/list/dict→TypeError
      except (TypeError, ValueError):
          return jsonify({"error": f"Некорректный task_id в задании {position}"}), 400
      validated_tasks[position] = (task_num_v, task_id_v)
  ```
  В цикле INSERT используется `validated_tasks` вместо `tasks_refs`.
  - `bool` проверяется явно до `int()`: без проверки `int(True)` → 1 (тихая ошибка).
  - `float` проверяется явно до `int()`: без проверки `int(5.7)` → 5 (потеря данных).
  - Атомарность: при некорректных данных ни папка, ни JSON-файл не создаются.
  - Формат успешного ответа не изменился.

- **Файл:** `app.py`, строки 2015–2030 и 2062 (маршрут `/api/variants/save`)

- **Правила принятия/отклонения task_id:**
  - `int` (JSON `5`) → принимается
  - `str` с цифрами (JSON `"5"`) → принимается как `int` (совместимость)
  - `float` (JSON `5.7`, `5.0`) → **отклоняется 400** (явная проверка `isinstance`)
  - `bool` (JSON `true`/`false`) → **отклоняется 400** (явная проверка `isinstance`)
  - `null`, `"abc"`, `[]`, `{}` → **отклоняются 400**

- **Проверка (9 сценариев, изолированная БД):**

| Сценарий | HTTP | Папка на диске |
|---|---|---|
| `task_id: 5` (int) | 200 `{success: true}` | создана ✅ |
| `task_id: "5"` (str) | 200, принят как 5 | создана ✅ |
| `task_id: 5.7` (float) | 400 | не создана ✅ |
| `task_id: true` (bool) | 400 | не создана ✅ |
| `task_id: false` (bool) | 400 | не создана ✅ |
| `position: "evil"` | 400 | не создана ✅ |
| `task_id: null` | 400 | не создана ✅ |
| `task_id: "abc"` | 400 | не создана ✅ |
| `task_id: []` (list) | 400 | не создана ✅ |

#### D-3: str(e) в двух admin-only маршрутах (LOW, утечка ошибок)

- **Проблема:** `/api/theory/save` и `/api/variants/save` возвращали `str(e)` при
  исключении, раскрывая внутренние сообщения SQLite/ОС. Оба маршрута закрыты
  `is_admin == 1`, поэтому риск низкий, но несовместим с принятым в v1.2.5 подходом.

- **Исправление:** `except Exception as e: return jsonify({"error": str(e)})` заменён на
  `except Exception: return jsonify({"error": "Не удалось сохранить …"})` в обоих маршрутах.

- **Файл:** `app.py`, строки 1638 (theory/save) и 2073 (variants/save)

---

### v1.3.0 — Релиз: завершение аудита безопасности и целостности данных

**Дата:** 2026-06-16

Релиз закрывает все задачи аудита безопасности, начатого в v1.2.0.
Новой функциональности не добавлено — только исправления.

**Итого по аудиту:**

| Категория | Найдено | Исправлено |
|---|---|---|
| P0 (критические) | 4 | 4 ✅ |
| P1 (высокие) | 4 | 4 ✅ |
| P2 (средние) | 2 | 2 ✅ |
| XSS | 3 | 3 ✅ |
| P3 Этап 1 | 4 | 4 ✅ |
| SQL-инъекции | 72 запроса | 0 уязвимостей ✅ |
| Целостность данных (D-1, D-2, D-3) | 3 | 3 ✅ |

**Открытые вопросы (отложено на следующий цикл):**
- P3 Этап 2: double-submit защита (`/save_results`, `/finish_exam`)
- MIME-валидация при загрузке аватаров
- Content Security Policy (CSP) заголовки
- Rate limiting на `/login` и `/register`
- Аудит файловых маршрутов (`/variant_files/`, `/theory_videos/`)

---

### v1.4.0 — Расширенный редактор задач

**Дата:** 2026-06-16

#### Этап 1 — Форматирование текста ✅

Добавлена панель форматирования в редактор задач (`admin_task_form.html`).

- Кнопки: **Жирный** (`<b>`), *Курсив* (`<i>`), верхний индекс (`<sup>`), нижний индекс (`<sub>`)
- Панель появляется над каждым textarea — существующим и добавленным динамически
- Кнопки `type="button"` — не вызывают submit формы
- **Файл:** `templates/admin_task_form.html`

#### Этап 2 — Загрузка изображений ✅

Добавлена полная поддержка изображений в редакторе задач: добавление при создании задачи,
редактирование (добавление новых + удаление существующих).

**Что добавлено:**

- Форма переведена на `enctype="multipart/form-data"`
- Изображения сохраняются в `tasks/task_XX/images/` — директория создаётся автоматически
- Имя файла: `t{task_num}_{task_id}_{timestamp}_{secure_filename}` — уникальность гарантирована timestamp
- Поле `images[]` в `tasks.json` заполняется автоматически; структура совместима с existing JSON:
  `{"path": "...", "after_paragraph": 0, "size": "img-medium", "alt": ""}`
- Поддерживаемые поля:
  - `after_paragraph` — изображение отображается после указанного абзаца (0-based)
  - `size` — `img-small`, `img-medium`, `img-large`
  - `alt` — текст для accessibility
- При редактировании: кнопка "× Удалить" помечает изображение на удаление,
  файл удаляется с диска и запись убирается из JSON при сохранении
- Селектор "После абзаца" обновляется автоматически при добавлении/удалении абзацев

**Отображение:**
- `tasks_view.html` — прямой `task_images` по `task_num`; CSS-классы `img-small/img-medium/img-large` уже были определены
- `reshenie.html`, `exam.html` — `task_images` по `_source_task_num` (новый формат) или `variant_images` (старый)

**Баг после выпуска — исправлен:** CSS-классы `img-small`, `img-medium`, `img-large` отсутствовали
в `reshenie.html` и `exam.html`. Класс прописывался в атрибуте `class=""` корректно,
но без CSS-правила браузер применял только базовый `max-width: 100%` — все три размера
выглядели одинаково. Исправление: добавлены три правила в оба шаблона рядом с `.task-image`:
```css
.img-small  { max-width: 250px !important; }
.img-medium { max-width: 350px !important; }
.img-large  { max-width: 500px !important; }
```
Теперь `img-small/img-medium/img-large` работают единообразно во всех трёх шаблонах.

**Безопасность загрузки:**
- `allowed_file()` — whitelist расширений: `png`, `jpg`, `jpeg`, `gif`; `svg`/`html`/`txt` отклоняются
- `is_valid_image()` — magic bytes: `\xff\xd8\xff` (JPEG), `\x89PNG` (PNG), `GIF8` (GIF);
  txt-файл под видом `.png` отклоняется
- `secure_filename()` применяется до формирования имени файла
- `MAX_CONTENT_LENGTH = 5 МБ` — глобальный лимит на все POST-запросы

**Исправления, выявленные в ходе верификации:**
- **Orphaned files** при дублировании `task_id`: проверка дубликата ID перенесена
  **до** цикла сохранения файлов; при дублировании файлы на диск не записываются
- **Path traversal в `delete_image`**: `os.remove()` вызывается только для имён,
  реально присутствующих в `task["images"]`; `safe_to_delete = to_delete & existing_paths`
  исключает любые crafted-пути типа `../../../...`

**Изменённые файлы:**

| Файл | Что добавлено |
|---|---|
| `app.py` | `import time`; `MAX_CONTENT_LENGTH`; `_IMAGE_MAGIC`, `is_valid_image()`, `save_task_image()`; обновлены `admin_task_add()` и `admin_task_edit()` |
| `templates/admin_task_form.html` | `enctype`; CSS для `.img-card`, `.new-img-block`; секция "Изображения"; JS: `addImageBlock()`, `markDeleteImage()`, `updateParagraphSelectors()` |
| `templates/reshenie.html` | Добавлены `.img-small`, `.img-medium`, `.img-large` рядом с `.task-image` |
| `templates/exam.html` | Добавлены `.img-small`, `.img-medium`, `.img-large` рядом с `.task-image` |

#### Этап 3 — Прикрепление файлов ✅

Добавлена полная поддержка файловых вложений в редакторе задач: прикрепление при создании,
замена и удаление при редактировании, скачивание во всех шаблонах отображения.

**Что добавлено:**

- Файлы сохраняются в `tasks/task_XX/files/` — директория создаётся автоматически
- Имя файла: `f{task_num}_{task_id}_{timestamp}_{secure_filename}` — уникальность гарантирована timestamp
- Поле `file` в `tasks.json`: `{"path": "...", "name": "...", "description": "..."}`
  - `name` — отображаемое название (fallback: оригинальное имя файла)
  - `description` — необязательный пояснительный текст
- Один файл на задачу (замена, а не накопление)
- UI: карточка текущего файла с кнопкой "× Удалить", блок загрузки нового файла
- `markDeleteTaskFile()` — помечает удаление визуально и добавляет `delete_task_file=1` в форму,
  одновременно показывает блок загрузки нового файла

**Whitelist расширений** (`ALLOWED_FILE_EXTENSIONS`):
`xlsx`, `xls`, `csv`, `txt`, `zip`, `db`, `sqlite`, `ods`, `odt`
— `.exe`, `.html`, `.php`, `.py` и прочие отклоняются с flash-ошибкой

**Логика замены файла (без orphaned files):**
- Новый файл загружается → старый удаляется с диска ДО сохранения нового
- Кнопка "Удалить" → `_delete_task_file_from_disk` → `task["file"] = None`
- Нет действий → `task["file"]` остаётся без изменений

**Маршрутизация скачивания — исправлена для всех шаблонов:**

| Шаблон | Логика | Было |
|---|---|---|
| `tasks_view.html` | `task_files` + `task_num` из маршрута | Уже корректно |
| `reshenie.html` | `{% if task._source_task_num is defined %}` → `task_files`, иначе → `variant_files` | Всегда `variant_files` |
| `exam.html` (JS) | `currentTask._source_task_num !== undefined` → `/task_files/${num}/...`, иначе → `variant_files` | Всегда `variant_files` |

**Безопасность загрузки файлов:**
- Whitelist расширений (см. выше); `secure_filename()` применяется
- Path traversal при удалении: `"/" in path or "\\" in path` → ранний `return`; `(FileNotFoundError, OSError)` поглощается
- Файлы не выходят за пределы `tasks/task_XX/files/` — `task_num` из `<int:task_num>` маршрута
- Magic bytes не применяется (слишком разные форматы) — только расширение

**Наблюдение (не исправлено, отдельная задача):**
`admin_task_delete` при удалении задачи из базы не удаляет связанные файлы и изображения с диска.
Orphaned-файлы остаются в `tasks/task_XX/files/` и `tasks/task_XX/images/`.
Это существующий паттерн — аналогично для изображений с момента Этапа 2.

**Изменённые файлы:**

| Файл | Что добавлено |
|---|---|
| `app.py` | `ALLOWED_FILE_EXTENSIONS`; `allowed_task_file()`, `save_task_file()`, `_delete_task_file_from_disk()`; обновлены `admin_task_add()` и `admin_task_edit()` |
| `templates/admin_task_form.html` | CSS `.file-card`, `.file-card-info`; секция "Прикреплённый файл" (existing-file-card + new-file-block); JS `markDeleteTaskFile()` |
| `templates/reshenie.html` | `_source_task_num is defined` → `task_files` вместо жёсткого `variant_files` |
| `templates/exam.html` | JS `updateFileLink()`: `_source_task_num` → `/task_files/${num}/...` вместо жёсткого `variant_files` |

---

### v1.5.0 — Редизайн главной страницы (start.html)

**Дата:** 2026-06-16

Полный редизайн `templates/start.html` в три итерации (v1.5.0 → v1.5.1 → v1.5.2).
**Backend (`app.py`) не менялся.** Маршруты, схема БД, логика авторизации — без изменений.
Logout: `method="POST"` + `{{ url_for('logout') }}` + `{{ csrf_token() }}` сохранены во всех итерациях.

#### v1.5.0 — Новая структура лендинга

- Hero: логотип + градиентный H1 «Подготовка к ЕГЭ по информатике» + тэглайн + 2 CTA-кнопки (`/preparation`, `/variants`)
- Блок статистики платформы: 4 карточки (1200+, 27, 14, 90+)
- Сетка возможностей: 5 карточек (3 колонки), ссылки на `/theory`, `/variants`, `/tasks`, `/preparation`, `/stats`
- Компактный footer: бренд + соцсети строкой + телефоны

#### v1.5.1 — Контент и интерактивность

- Блок «С чего начать»: 3 карточки по уровням (`/preparation`, `/theory`, `/variants`)
- Мини-задача: интерактивный вопрос (256 символов = 8 бит), проверка на JS, без backend
- Маршрут подготовки: 5 шагов ①–⑤
- Блок преимуществ: 2×2 карточки
- Визуальное осветление: фон `#0f172a` → `#111827`, карточки чуть светлее

#### v1.5.2 — Персонализация, dropdown navbar, мобильная версия

**Персонализация:**
- Блок «Ваш прогресс» (`{% if session.get('user_id') %}`): 3 карточки, ссылка на `/stats`
- Гостевой CTA (`{% if not session.get('user_id') %}`): кнопки `/register`, `/login`
- Калькулятор готовности: 3 да/нет вопроса, результат (начальный / средний / высокий) в JS
- Блок «Что нового»: 3 карточки

**Dropdown-меню в navbar (по центру, между логотипом и auth-кнопками):**
- Кнопка «Разделы» (desktop) / «Меню» (≤480px) — по центру через `position: absolute; left: 50%; transform: translateX(-50%)`
- 5 пунктов: `/preparation`, `/theory`, `/variants`, `/stats`, `/tasks`
- Desktop: dropdown открывается вниз (`position: absolute; top: calc(100% + 9px)`)
- Mobile ≤768px: `.nav-center { position: static; transform: none }` — убирает transform-контекст; dropdown переключается на `position: fixed; top: 62px; left: 10px; right: 10px` — привязан к viewport, не уезжает за экран
- Mobile ≤480px: `.nav-label-desktop { display: none }`, `.nav-label-mobile { display: inline }` — текст «Меню»
- JS: `toggleNavDropdown()` (toggle `.open`/`.active`), закрытие по клику вне (`!wrap.contains(e.target)`), закрытие по клику на пункт

**Улучшения мобильной версии (≤480px):**
- Hero: `padding: 24px 0 32px`, logo `38px`, title `1.65em`, кнопки `9px 18px`
- Карточки прогресса: горизонтальный flex-layout, `padding: 14px`, `progress-num: 1.55em`
- stat-card: `padding: 14px 10px`, `stat-num: 1.5em`
- start/minitask/calculator/advantage/feature/update карточки: уменьшены padding до 14–18px
- Варианты мини-задачи: одна колонка (`grid-template-columns: 1fr`)
- `.calc-question`: `flex-direction: column; gap: 8px`
- Все секции: `margin-bottom` 72px → 44–48px; `.section-heading`: `margin-bottom: 20px`
- `navbar-site-title` скрыт, nav-btn и nav-dropdown-btn: `padding: 5px 9/10px; font-size: 0.775em`

**Изменённые файлы:**

| Файл | Что изменено |
|---|---|
| `templates/start.html` | Полная перезапись: новая структура, все блоки, CSS, JS |

**Что не менялось:**

| Компонент | Статус |
|---|---|
| `app.py` | Не трогался |
| Маршруты | Без изменений |
| Схема БД | Без изменений |
| Logout POST + CSRF | Сохранены (`method="POST"`, `{{ url_for('logout') }}`, `{{ csrf_token() }}`) |
| `/preparation`, `/theory`, `/variants`, `/stats`, `/tasks` | Все ссылки корректны |

---

### v1.5.3 — Визуальная иерархия главной страницы (start.html)

**Дата:** 2026-06-16

Переработка визуальной иерархии секций `templates/start.html` в два этапа.
**Backend (`app.py`) не менялся.** Маршруты, схема БД, логика авторизации — без изменений.
Logout: `method="POST"` + `{{ url_for('logout') }}` + `{{ csrf_token() }}` сохранены.

#### Этап 1 — Двухколоночный Hero ✅

- Hero переведён на CSS grid `1fr 1fr`.
- Левая колонка: логотип, градиентный H1, тэглайн, описание, 2 CTA-кнопки.
- Правая колонка: HTML/CSS mockup интерфейса решения задачи (без изображений) + 3 мини-статы под mockup.
- ≤900px: grid коллапсирует в 1 колонку, правая колонка скрывается (`display: none`).
- Фоновый radial-gradient смещён вправо — визуально обрамляет mockup.

#### Этап 2 — Визуальная иерархия секций ✅

**stats-row** — снята «карточность» (фон + рамки на каждом стате удалены):
- Flex-layout; весь блок ограничен тонкими `border-top` / `border-bottom`.
- Разделитель между статами — `border-right` на каждом элементе; `last-child` без бордера.
- ≤768px: `flex-wrap: wrap`, 2×2 с внутренними разделителями; горизонтальные линии убираются (`border-top/bottom: none`).

**"С чего начать"** — 3 равнозначные карточки преобразованы в визуальный маршрут пользователя:
- `.start-cards` grid → `.start-flow` flex-row; между карточками вставлены `.start-arrow` (`→`).
- Левый акцентный бордер: синий (Уровень 1) / фиолетовый (Уровень 2) / зелёный (Уровень 3).
- ≤900px: стак вертикально (`flex-direction: column`); стрелки поворачиваются `rotate(90deg)` → `↓`.

**Мини-задача** — синий акцент, визуально отличается от нейтральных карточек:
- Фон: `rgba(56,189,248,0.04)`, бордер: `rgba(56,189,248,0.16)`.
- Тег `.section-tag.section-tag-blue` («Задание») над заголовком секции.

**Калькулятор готовности** — фиолетовый акцент, визуально отличается от мини-задачи:
- Фон: `rgba(129,140,248,0.04)`, бордер: `rgba(129,140,248,0.16)`.
- `.calc-btn` градиент изменён: `#6366f1 → #a855f7` (был `#3b82f6 → #6366f1`).
- `.calc-option.calc-selected`: фиолетовый (был синий).
- Тег `.section-tag.section-tag-purple` («Калькулятор») над заголовком секции.

**Преимущества** — 4 отдельных карточки объединены в единую панель:
- `.advantages-grid` (4× `advantage-card`) → `.advantages-panel` → `.advantages-list` (CSS grid 2×2) → `.advantage-item` (flex-row: иконка + текст).
- Единый внешний бордер + `border-radius: 16px; overflow: hidden`.
- Разделители через `border-right` и `border-bottom` на элементах.
- ≤768px: 1 колонка (`grid-template-columns: 1fr`); `border-right: none` на всех; `border-bottom` на каждом, кроме последнего.

**Финальная проверка Этапа 2: 8/8 OK**

| Проверка | Результат |
|---|---|
| Ссылки в "С чего начать" (`/preparation`, `/theory`, `/variants`) | ✅ |
| Мини-задача (`checkMiniTask`, верный ответ `'8'`) | ✅ |
| Калькулятор (`checkReadiness`, ветки low/mid/high) | ✅ |
| start-flow ≤900px (column + rotate arrow) | ✅ |
| stats-row ≤768px (2×2 wrap, внутренние разделители) | ✅ |
| advantages-panel ≤768px (1 колонка) | ✅ |
| Backend не изменён (`git status`: только `start.html`) | ✅ |
| Navbar / logout POST + CSRF / footer | ✅ |

#### Этап 3.1 — Feature Grid 2×2, порядок карточек ✅

**Feature Grid:**
- `.features-grid` изменён с 3 колонок на 2 (`grid-template-columns: repeat(2, 1fr)`).
- Карточка «Статистика» (`/stats`) удалена — устранён orphan при нечётном числе элементов.
- Осталось 4 карточки в симметричном grid 2×2.
- Дублирующее правило `repeat(2, 1fr)` из медиазапроса 900px удалено.

**Порядок карточек** — приведён в соответствие с пользовательским маршрутом:

| Позиция | Раздел | Ссылка |
|---|---|---|
| 1 | Начальная подготовка | `/preparation` |
| 2 | Теория | `/theory` |
| 3 | Варианты | `/variants` |
| 4 | База заданий | `/tasks` |

#### Этап 3.2 — Повышение контраста вторичного текста ✅

**Проблема:** `#64748b` на фоне `#111827` — контраст ≈ 3.7:1 (ниже WCAG AA 4.5:1 для обычного текста).

**Решение:** 15 CSS-селекторов вторичного текста переведены с `#64748b` → `#94a3b8` (контраст ≈ 5.3:1 ✅).

**Изменены:**
`.hero-desc`, `.hero-mini-stat-label`, `.progress-label`, `.guest-cta-desc`, `.stat-label`,
`.section-heading p`, `.start-card-desc`, `.roadmap-step-desc`, `.advantage-item-desc`,
`.feature-desc`, `.update-desc`, `.new-variant-info p`, `.date-value`, `.news-description`, `.footer-name`

**Оставлены `#64748b`** (намеренно приглушены):
- `.mockup-bar-label`, `.mockup-choice`, `.mockup-result-explain` — декорации mockup-интерфейса
- `.progress-header-title`, `.features-heading`, `.section-title` — uppercase-лейблы-разделители

Итого: 15 изменено, 6 сохранено. Баланс иерархии заголовок → вторичный текст сохранён.

#### Этап 3.3 — Interactive Zone ✅

**Задача:** объединить три секции («Мини-задача», «Калькулятор готовности», «Маршрут подготовки»)
в единую визуальную зону, не трогая их контент и JS.

**HTML:** три `<section>` обёрнуты в `<div class="interactive-zone">` (строки 2130–2258).

**CSS `.interactive-zone`:**
- `border-top / border-bottom: 1px solid rgba(255,255,255,0.07)` — тонкие горизонтальные линии
- `background: rgba(255,255,255,0.018)` — едва заметный фон-полоса
- `padding: 64px 0; margin-bottom: 72px`
- `.interactive-zone .roadmap-section { margin-bottom: 0 }` — убирает зазор последней секции (зона сама даёт паддинг снизу)
- `@media (max-width: 480px)`: `padding: 44px 0; margin-bottom: 48px`

Зона — горизонтальная полоса (нет left/right бордеров, нет border-radius, нет card-фона).
Карточки внутри (`minitask-card`, `calculator-card`) сохраняют собственное оформление без наложения.

**Финальная проверка Этапа 3.3: 9/9 OK**

| Проверка | Результат |
|---|---|
| `interactive-zone` содержит только mini-task, calculator, roadmap | ✅ |
| Порядок внутри зоны: mini-task → calculator → roadmap | ✅ |
| `checkMiniTask()` не изменён | ✅ |
| `checkReadiness()` не изменён | ✅ |
| Backend не изменён | ✅ |
| Navbar / logout / footer не изменены | ✅ |
| Desktop: зона визуально отделяет интерактивные блоки (border + фон) | ✅ |
| Mobile 375px: padding зоны 44px — страница не раздута | ✅ |
| Нет вложенных карточек и двойных border-эффектов | ✅ |

**Изменённые файлы (Этапы 1–3.3):**

| Файл | Что изменено |
|---|---|
| `templates/start.html` | Этапы 1–2: stats-row (flex), start-flow + start-arrow, section-tag, minitask/calculator акценты, advantages-panel, медиазапросы 900/768/480px |
| `templates/start.html` | Этап 3.1: features-grid → 2 колонки, удалена карточка Статистика, порядок карточек по маршруту |
| `templates/start.html` | Этап 3.2: 15 селекторов `#64748b` → `#94a3b8` (вторичный текст, WCAG AA) |
| `templates/start.html` | Этап 3.3: `<div class="interactive-zone">` вокруг 3 секций; CSS `.interactive-zone` и адаптив |

---

### v1.5.4 — UX-доработка главной страницы (start.html)

**Дата:** 2026-06-16

Продолжение доработки `templates/start.html`.
**Backend (`app.py`) не менялся.** Маршруты, схема БД, логика авторизации — без изменений.
Logout: `method="POST"` + `{{ url_for('logout') }}` + `{{ csrf_token() }}` сохранены.

#### Этап 1 — Убрать «Новые варианты», усилить кнопку navbar ✅

**Блок «Новые варианты»:**
- HTML-секция `section.block` с тремя карточками вариантов 3, 4, 5 полностью удалена.
- 9 CSS-селекторов удалены: `.new-variant-card`, `.new-variant-card:hover`, `.new-variant-card:last-child`, `.new-variant-info h3`, `.new-variant-info p`, `.new-variant-date`, `.date-label`, `.date-value`, `.badge-new` + адаптивное правило для `.new-variant-date`.
- Комментарий секции переименован: `ВАРИАНТЫ И НОВОСТИ` → `НОВОСТИ`.
- **Маршруты `/choose-mode/3`, `/choose-mode/4`, `/choose-mode/5` в `app.py` не удалены** — только скрыто отображение.

**Кнопка navbar:**
- Текст кнопки: `Разделы` → `Разделы платформы` (desktop); мобильный текст «Меню» не изменился.
- `padding`: `7px 14px` → `7px 18px`.
- `font-weight`: `500` → `600`.
- `color`: `#94a3b8` → `#cbd5e1`.
- `background`: `transparent` → `rgba(255,255,255,0.04)`.
- `border-color`: `rgba(255,255,255,0.09)` → `rgba(255,255,255,0.12)`.
- Добавлены: `border-radius: 8px`, `white-space: nowrap`, явные `display: flex`, `align-items: center`.

**Финальная проверка Этапа 1: 8/8 OK**

| Проверка | Результат |
|---|---|
| Блок «Новые варианты» отсутствует в HTML | ✅ |
| 9 CSS-селекторов + адаптив удалены | ✅ |
| Маршруты `/choose-mode/3,4,5` в app.py не удалены | ✅ |
| Кнопка navbar: «Разделы платформы» на desktop | ✅ |
| Кнопка navbar: «Меню» на мобильном (≤480px) | ✅ |
| Logout POST + CSRF не тронуты | ✅ |
| Hero / interactive-zone / footer не тронуты | ✅ |
| Backend не изменён | ✅ |

#### Этап 2 — Последовательная интерактивная зона ✅

**Задача:** преобразовать три параллельные секции интерактивной зоны в последовательный пошаговый сценарий с явными переходами по кнопкам.

**Сценарий:**
1. **Шаг 1 — Мини-задача:** пользователь нажимает «Проверить» → получает результат → видит кнопку «Оценить свою готовность →»
2. **Шаг 2 — Калькулятор готовности:** пользователь отвечает на 3 вопроса → нажимает «Показать результат» → видит кнопку «Посмотреть маршрут подготовки →»
3. **Шаг 3 — Roadmap + CTA:** маршрут подготовки к ЕГЭ (5 шагов ①–⑤) + CTA-блок «Запишись на первое бесплатное вводное занятие»

**Начальное состояние при загрузке:**
- Видима только `section.minitask-section`.
- `section.calculator-section` — `style="display:none"` в HTML.
- `section.roadmap-section` — `style="display:none"` в HTML.
- `#izCta` — `style="display:none"` в HTML.

**Индикатор прогресса:** `div.iz-progress` — первый элемент внутри `.interactive-zone`.
- Текст «Шаг N из 3» (`#izProgressLabel`), три точки `.iz-dot` (активные — `.iz-dot-active`).
- Шаг 1: ● ○ ○ | Шаг 2: ● ● ○ | Шаг 3: ● ● ●

**Анимация переходов:**
- `goToStep2()`, `goToStep3()` — fade-out текущей секции (`opacity: 0`, `transition: 0.25s`), затем `setTimeout(280ms)` → `display: none` → следующая секция `display: block` → двойной `requestAnimationFrame` → `opacity: 1`.
- **Переходы только по кнопкам** — авто-переходов без действия пользователя нет.
- **`scrollIntoView` не используется** — 0 вхождений в файле.

**Кнопки перехода** (`#izNextToCalc`, `#izNextToRoadmap`):
- Стиль `.iz-next-btn` — вторичный, тихий (не конкурирует с «Проверить» / «Показать результат»).
- `#izNextToCalc` появляется только при выборе ответа в мини-задаче (ветки `correct` и `incorrect`); при `no-answer` — **не появляется**.
- `#izNextToRoadmap` появляется только при ответе на все 3 вопроса калькулятора (ветки low/mid/high); при `warn` — **не появляется**.

**CTA-блок (`div.iz-cta`, `#izCta`):**
- Заголовок: «Запишись на первое бесплатное вводное занятие»
- Подзаголовок: «Разберём твой уровень, составим план подготовки и ответим на вопросы.»
- Кнопка Telegram: `https://t.me/Tyomkinss`
- Кнопка MAX: идентичный URL из footer (`https://max.ru/u/f9LH...`)
- Появляется одновременно с roadmap в `goToStep3()`.

**Изменённые JS-функции:**
- `checkMiniTask()` — добавлена одна строка: показ `#izNextToCalc` вне ветки `no-answer`.
- `checkReadiness()` — добавлена одна строка: показ `#izNextToRoadmap` вне ветки `warn`.

**Новые JS-функции:** `updateIzProgress(step)`, `goToStep2()`, `goToStep3()`.

**Новые CSS-классы:** `.iz-progress`, `.iz-progress-label`, `.iz-progress-dots`, `.iz-dot`, `.iz-dot.iz-dot-active`, `.iz-next-btn`, `.iz-next-btn:hover`, `.iz-cta`, `.iz-cta-title`, `.iz-cta-sub`, `.iz-cta-buttons`, `.iz-cta-btn`, `.iz-cta-btn:hover`, `.iz-cta-btn-tg`, `.iz-cta-btn-max`.

**Адаптивность (≤480px):** `.iz-progress` (`margin-bottom: 32px`), `.iz-cta` (`padding` уменьшен), `.iz-cta-buttons` (`flex-direction: column`), `.iz-cta-btn` (`width: 100%`).

**Что не менялось:**
- Тексты вопросов мини-задачи и калькулятора — без изменений.
- Содержимое roadmap (5 шагов ①–⑤) — без изменений.
- Логика `checkMiniTask()` и `checkReadiness()` — только добавлены строки показа кнопок.
- Navbar / logout POST + CSRF / footer / hero — не тронуты.
- `app.py` — не открывался.

**Финальная проверка Этапа 2: 24/24 OK**

| # | Проверка | Результат |
|---|---|---|
| 1.1 | mini-task видна при загрузке | ✅ |
| 1.2 | calculator скрыт при загрузке | ✅ |
| 1.3 | roadmap скрыт при загрузке | ✅ |
| 1.4 | CTA скрыт при загрузке | ✅ |
| 1.5 | Индикатор «Шаг 1 из 3», первая точка активна | ✅ |
| 2.1 | Без выбора → предупреждение, кнопка перехода не появляется | ✅ |
| 2.2 | Правильный ответ → результат + кнопка перехода | ✅ |
| 2.3 | Неправильный ответ → результат + кнопка перехода | ✅ |
| 3.1 | По кнопке «Оценить» мини-задача скрывается | ✅ |
| 3.2 | Калькулятор появляется | ✅ |
| 3.3 | Индикатор «Шаг 2 из 3» | ✅ |
| 3.4 | Авто-перехода без кнопки нет | ✅ |
| 4.1 | Без ответов → предупреждение, кнопка перехода не появляется | ✅ |
| 4.2 | Все вопросы → результат + кнопка перехода | ✅ |
| 5.1 | По кнопке «Посмотреть маршрут» калькулятор скрывается | ✅ |
| 5.2 | Roadmap появляется | ✅ |
| 5.3 | CTA появляется вместе с roadmap | ✅ |
| 5.4 | Индикатор «Шаг 3 из 3» | ✅ |
| 6.1 | Telegram → `https://t.me/Tyomkinss` | ✅ |
| 6.2 | MAX URL совпадает с footer | ✅ |
| 7.1 | `scrollIntoView` не используется (0 вхождений) | ✅ |
| 7.2 | `setTimeout` только для fade-анимации внутри button-handler | ✅ |
| 7.3 | Backend не изменён | ✅ |
| 7.4 | Navbar / logout / footer / hero не тронуты | ✅ |

#### Этап 3 — Roadmap как карточка результата; убран фон .interactive-zone ✅

**Задача:** оформить roadmap как компактную карточку результата (split-card вместе с CTA); убрать декоративный фон и рамки `.interactive-zone`.

**CSS `.roadmap-section` — стала верхней половиной split-card:**
- `max-width: 580px; margin-left: auto; margin-right: auto` — центрирование
- `background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1)` — карточный фон
- `border-radius: 20px 20px 0 0` — только верхние углы
- `padding: 32px 36px 28px`

**CSS `.iz-cta` — нижняя половина той же карточки (split-card):**
- `max-width: 580px; margin: 0 auto` — синхронизированная ширина с `.roadmap-section`
- `background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-top: none` — бесшовное соединение
- `border-radius: 0 0 20px 20px` — только нижние углы

**Новые CSS-классы:**
- `.iz-result-header` — flex-ряд (иконка ✓ + заголовок); `border-bottom` — разделитель перед шагами roadmap
- `.iz-result-check` — зелёный кружок 34×34px (`color: #4ade80`); визуально согласован с кружком ⑤ roadmap
- `.iz-result-title` — «Ваш маршрут подготовки готов» (`font-weight: 700; color: #e2e8f0`)

**CSS `.roadmap` — изменено:** `max-width: 500px; margin: 0 auto` → `max-width: 100%` (центрирование взял `.roadmap-section`).

**Адаптив ≤480px:** `.roadmap-section` — `padding: 24px 20px 20px`, `border-radius: 14px 14px 0 0`; `.iz-cta` — `padding: 20px 20px 26px`, `margin-top: 0`, `border-radius: 0 0 14px 14px`.

**HTML:** внутри `section.roadmap-section` — `div.section-heading` заменён на `div.iz-result-header` с `div.iz-result-check` (✓) и `div.iz-result-title`.

**CSS `.interactive-zone` — удалены три декоративных свойства:**
- Удалено: `border-top: 1px solid rgba(255,255,255,0.07)`
- Удалено: `border-bottom: 1px solid rgba(255,255,255,0.07)`
- Удалено: `background: rgba(255,255,255,0.018)`
- Сохранено: `padding: 64px 0; margin-bottom: 72px` — вертикальные отступы не изменились
- `.interactive-zone` теперь — только логическая обёртка и вертикальный отступ, без визуального оформления

**Принцип split-card:** `.roadmap-section` и `#izCta` остаются соседями (siblings) в DOM — `goToStep3()` не изменялась. Совпадение `max-width`, `background` и `border-color` создаёт единую карточку без изменения JS.

**Что не менялось:**
- JS-функции (`goToStep2`, `goToStep3`, `updateIzProgress`, `checkMiniTask`, `checkReadiness`) — не тронуты
- Тексты шагов roadmap ①–⑤ — без изменений
- Ссылки Telegram и MAX — без изменений
- Индикатор прогресса (`.iz-progress`) — без изменений
- Мини-задача и калькулятор — без изменений
- `.interactive-zone` в адаптиве ≤480px (`padding: 44px 0; margin-bottom: 48px`) — без изменений
- `app.py` — не открывался

---

### v1.5.5 — Улучшение структуры и конверсии главной страницы

**Дата:** 2026-06-17

Доработка `templates/start.html` в три этапа.
**Backend (`app.py`) не менялся.** Маршруты, схема БД, логика авторизации — без изменений.
Navbar / logout POST + CSRF / footer / интерактивная зона (логика сценария) — не тронуты.

#### Этап 1 — Устранение дублирования статистики ✅

**Проблема:** `hero-mini-stats` (внутри Hero: 1200+, 27, 90+) и `stats-row` (под Hero: 1200+, 27, 14, 90+) показывали одни числа дважды без смыслового разрыва.

**Решение — Вариант B:** `stats-row` удалён полностью; `hero-mini-stats` сохранён.

**Обоснование:** `hero-mini-stats` встроен в `.hero-right` (скрывается при ≤900px) и органично дополняет mockup платформы — стандартный SaaS-паттерн. `stats-row` добавлял только "14 вариантов" как новую цифру, что недостаточно для отдельного полосового блока.

**Удалено:**
- HTML: `<!-- СТАТИСТИКА ПЛАТФОРМЫ -->` + `<div class="stats-row">...</div>` (20 строк)
- CSS (базовые): `.stats-row`, `.stat-card`, `.stat-card:last-child`, `.stat-num`, `.stat-label` (38 строк + блок комментария)
- CSS (768px адаптив): `.stats-row`, `.stat-card`, `.stat-card:nth-child(odd)`, `.stat-card:nth-child(3/4)` (23 строки)
- CSS (480px адаптив): `/* Stats */`, `.stats-row`, `.stat-card`, `.stat-num`, `.stat-label` (18 строк)

**Финальная проверка Этапа 1: 10/10 OK**

#### Этап 2 — Блок преимуществ переписан под боли ученика ✅

**Проблема:** 4 преимущества описывали функции платформы ("Все темы ЕГЭ", "Практика без ограничений"), а не отвечали на вопрос пользователя "почему именно здесь?".

**Решение:** тексты переписаны по модели «боль ученика → решение платформы». Структура `.advantages-panel`, CSS, количество пунктов (4) — не изменились.

| # | Старый заголовок | Новый заголовок |
|---|---|---|
| 1 | Все темы ЕГЭ | Готовый маршрут от нуля до ЕГЭ |
| 2 | Практика без ограничений | Все 27 тем — без пробелов |
| 3 | Отслеживание прогресса | Видишь, где проваливаешься |
| 4 | Подготовка с нуля | Экзамен без страха |

Порядок соответствует пути ученика: маршрут → темы → прогресс → экзамен.

**Финальная проверка Этапа 2: 7/7 OK**

#### Этап 3 — Улучшен индикатор интерактивной зоны ✅

**Проблема:** "Шаг 1 из 3" + три точки не объясняли пользователю, что его ждёт впереди.

**Решение:** `iz-progress-label` (текст "Шаг N из 3") и `iz-progress-dots` (простые точки без контекста) заменены на именованные шаги с коннекторами:

```
● Задача  ————  ○ Готовность  ————  ○ Маршрут
```

**CSS:** удалены `.iz-progress-label`, `.iz-progress-dots`; добавлены `.iz-steps-row`, `.iz-step-item`, `.iz-step-connector`, `.iz-step-label`, `.iz-step-item:has(.iz-dot.iz-dot-active) .iz-step-label` (подсветка подписи активного шага).

**HTML:** три `iz-step-item` с `.iz-dot` и `.iz-step-label`, между ними `.iz-step-connector`.

**JS:** из `updateIzProgress()` удалена одна строка (`getElementById('izProgressLabel').textContent`). Логика обновления `.iz-dot` не изменилась — `goToStep2()`, `goToStep3()` работают без изменений.

**Что не менялось:**
- Логика сценария: `checkMiniTask()`, `checkReadiness()`, `goToStep2()`, `goToStep3()` — не тронуты
- CTA-ссылки Telegram и MAX — не тронуты
- Roadmap split-card — не тронут
- Backend не открывался

**Финальная проверка Этапа 3: 12/12 OK**

---

### v1.5.6 — Персонализация воронки главной страницы (start.html)

**Дата:** 2026-06-17

Доработка `templates/start.html`.
**Backend (`app.py`) не менялся.** Маршруты, схема БД, логика авторизации — без изменений.
Navbar / logout POST + CSRF / footer / Hero / интерактивная зона — не тронуты.

#### Этап 1 — Перенос блоков прогресса и регистрации в воронку ✅

**Проблема:** `progress-section` («Ваш прогресс», авторизованным) и `guest-cta-section` («Начните подготовку», гостям) располагались сразу после Hero — до того, как пользователь успевал понять продукт. Авторизованный пользователь видел свою статистику ещё до знакомства с платформой; гость видел призыв к регистрации до понимания ценности.

**Решение:** оба блока перенесены ниже по странице — в конец воронки знакомства.

**Старый порядок:** Hero → Прогресс/Регистрация → С чего начать → Интерактивная зона → Преимущества → Что есть на платформе → Что нового

**Новый порядок:**
1. Hero
2. С чего начать подготовку?
3. Интерактивная зона (мини-задача → готовность → маршрут)
4. Преимущества
5. Что есть на платформе
6. **Ваш прогресс** (авторизованным) / **Регистрация** (гостям) ← перемещено сюда
7. Что нового на платформе
8. Footer

**Что изменено в HTML:**
- `progress-section` и `guest-cta-section` вырезаны из позиции после Hero (между Hero и «С чего начать»)
- Вставлены между закрывающим `</section>` `features-section` и `<!-- ЧТО НОВОГО НА ПЛАТФОРМЕ -->`

**Что не изменено:**
- Jinja2-условия сохранены дословно:
  - `progress-section`: `{% if session.get('user_id') %} ... {% endif %}`
  - `guest-cta-section`: `{% if not session.get('user_id') %} ... {% endif %}`
- CSS обоих блоков — не тронут
- Содержимое обоих блоков — не изменено
- JS, backend, navbar/logout/CSRF, Hero, интерактивная зона — не тронуты

**Финальная проверка Этапа 1: 13/13 OK**

---

## Проведённые проверки

| Проверка | Результат | Дата |
|---|---|---|
| Аудит POST-маршрутов на авторизацию | Исправлен `/api/theory/save` | 2026-06-15 |
| Аудит режима запуска Flask | `debug=True` устранён | 2026-06-15 |
| Аудит секретов в коде | Все 4 секрета вынесены в `.env` | 2026-06-15 |
| Аудит CSRF (инфраструктура) | CSRFProtect установлен, проверен | 2026-06-15 |
| Аудит HTML POST-форм | 9/9 защищены | 2026-06-15 |
| Аудит JSON fetch POST-запросов | 7/7 защищены | 2026-06-15 |
| Проверка FormData-запросов | 1/1 защищён через hidden input | 2026-06-15 |
| Проверка на csrf.exempt | Ни одного | 2026-06-15 |
| Импорт приложения | OK, 55 маршрутов (@app.route) | 2026-06-15 |
| Совместимость форматов вариантов | Оба формата работают корректно | 2026-06-15 |
| Аудит прав доступа (18 маршрутов) | Найдено 5 проблем, P1/P2 исправлены | 2026-06-15 |
| Проверка is_admin в /api/variants/save | Добавлена, 403 для обычных пользователей | 2026-06-15 |
| Проверка is_admin в /api/variant/preview | Добавлена, 403 для обычных пользователей | 2026-06-15 |
| Перевод /logout на POST | GET→POST, CSRF-формы в 2 шаблонах | 2026-06-15 |
| Аудит XSS и небезопасного рендеринга | Найдено 3 проблемы, критическая (#1) исправлена | 2026-06-15 |
| Stored XSS в admin_panel.html | data-атрибут вместо JS-литерала, payload не выполняется | 2026-06-15 |
| Сканирование task/theory JSON на нежелательные теги | 27 tasks.json + 4 theory.json; только whitelist-теги, 0 нарушений | 2026-06-15 |
| XSS-2: replace_markers (app.py) | Whitelist-pipeline; script/img/iframe/onerror экранируются; 12/12 тестов | 2026-06-15 |
| XSS-3: `\| safe` в preparation_lesson.html | Заменён на `\| replace_markers`; 6/6 XSS-векторов экранированы; регрессий нет | 2026-06-15 |
| P3-аудит Этап 1: auth-guard и variant_num | `/clear_stats`, `/save_results`, `/finish_exam` — guard, очистка user_task_answers, 404 для несуществующих вариантов; 11/11 тестов | 2026-06-16 |
| Аудит SQL-запросов на параметризацию | 72 db.execute() проверено; 0 инъекций; все запросы используют `?`-плейсхолдеры; пользовательский ввод не попадает в ORDER BY / LIMIT; риск — минимальный | 2026-06-16 |
| D-1: каскадное удаление пользователя | `delete_user()` теперь удаляет из 7 таблиц в правильном порядке; 7/7 таблиц чистые после удаления | 2026-06-16 |
| D-2: валидация task_id в /api/variants/save | Строгая проверка типов: bool/float отклоняются явно (`isinstance`); int и digit-str принимаются; `str(e)` устранён; атомарность — папка не создаётся при 400; 9/9 сценариев | 2026-06-16 |
| D-3: str(e) в admin-only маршрутах | Generic-сообщения в /api/theory/save и /api/variants/save; `str(e)` не возвращается | 2026-06-16 |
| v1.4.0 Этап 1: форматирование текста | Панель B/I/sup/sub в admin_task_form.html; кнопки type=button; toolbars на новых абзацах | 2026-06-16 |
| v1.4.0 Этап 2: изображения в задачах | Загрузка в tasks/task_XX/images/; extension + magic bytes; orphaned files fix; path traversal fix | 2026-06-16 |
| v1.4.0 Этап 2: баг размеров изображений | img-small/img-medium/img-large не работали в reshenie.html и exam.html — CSS-правила отсутствовали; добавлены в оба шаблона | 2026-06-16 |
| v1.4.0 Этап 3: прикрепление файлов | Whitelist xlsx/xls/csv/txt/zip/db/sqlite/ods/odt; save/delete/replace; path traversal protection; 21/21 сценариев OK | 2026-06-16 |
| v1.4.0 Этап 3: маршрутизация скачивания | reshenie.html и exam.html: `_source_task_num` → task_files vs variant_files; tasks_view.html уже был корректен | 2026-06-16 |
| v1.5.0: navbar desktop + mobile 375px | Desktop: лого слева / dropdown по центру / auth справа ✅; Mobile: no overflow / «Меню» / dropdown fixed 10px-10px / hero compact / все карточки compact ✅; JS: toggle / клик вне / клик пункт / повторный клик ✅; ссылки /preparation /theory /variants /stats /tasks ✅; logout POST + csrf_token ✅; **21/21 OK** | 2026-06-16 |
| v1.5.3 Этап 2: визуальная иерархия | stats-row → flex-полоса без карточек; start-flow + стрелки (Уровень 1→2→3); мини-задача синий акцент; калькулятор фиолетовый акцент; advantages-panel единая панель с внутренними разделителями; backend не менялся; logout/navbar/footer не тронуты; **8/8 OK** | 2026-06-16 |
| v1.5.3 Этап 3.1: feature grid | features-grid 3 кол. → 2 кол. 2×2; карточка Статистика удалена; порядок: Подготовка / Теория / Варианты / База | 2026-06-16 |
| v1.5.3 Этап 3.2: контраст текста | 15 селекторов `#64748b` → `#94a3b8`; 6 декоративных/uppercase оставлены; WCAG AA 3.7:1 → 5.3:1 | 2026-06-16 |
| v1.5.3 Этап 3.3: interactive-zone | `<div class="interactive-zone">` оборачивает mini-task/calculator/roadmap; border-top/bottom + фон; JS не тронуты; backend не менялся; **9/9 OK** | 2026-06-16 |
| v1.5.4 Этап 1: убран блок «Новые варианты», усилена navbar-кнопка | Секция + 9 CSS-селекторов удалены; маршруты `/choose-mode/3,4,5` в app.py сохранены; кнопка «Разделы платформы» усилена визуально; **8/8 OK** | 2026-06-16 |
| v1.5.4 Этап 2: последовательная интерактивная зона | 3-шаговый сценарий (мини-задача → калькулятор → roadmap + CTA); переходы только по кнопкам; scrollIntoView отсутствует; setTimeout только для fade-анимации; backend не менялся; **24/24 OK** | 2026-06-16 |
| v1.5.4 Этап 3: roadmap-карточка + убран фон .interactive-zone | `.roadmap-section` → верхняя half split-card; `.iz-cta` → нижняя half; новые классы `.iz-result-header`, `.iz-result-check`, `.iz-result-title`; `section-heading` заменён в HTML; `border-top/bottom/background` из `.interactive-zone` удалены; JS/roadmap/CTA/backend не тронуты | 2026-06-17 |
| v1.5.5 Этап 1: устранение дублирования статистики | `stats-row` HTML + все CSS удалены (базовый + 768px + 480px адаптив); `hero-mini-stats` сохранён; дублирования 1200+/27/90+ нет; **10/10 OK** | 2026-06-17 |
| v1.5.5 Этап 2: блок преимуществ переписан | 4 преимущества: боль ученика → решение; маршрут / темы / прогресс / экзамен; структура и CSS не изменены; **7/7 OK** | 2026-06-17 |
| v1.5.5 Этап 3: улучшен индикатор интерактивной зоны | `iz-progress-label/dots` заменены именованными шагами (Задача/Готовность/Маршрут); CSS обновлён; `updateIzProgress()` — удалена 1 строка; сценарий не изменён; **12/12 OK** | 2026-06-17 |
| v1.5.6 Этап 1: перенос progress-section и guest-cta-section | Блоки перемещены после features-section; Jinja2-условия `session.get('user_id')` / `not session.get('user_id')` сохранены дословно; CSS/содержимое/JS/backend не тронуты; **13/13 OK** | 2026-06-17 |
| v1.6.0 Этап 1–7: визуальный редизайн главной страницы | Светло-голубой градиент body; белые карточки (0.92–0.96); мягкие синие рамки rgba(37,99,235,…); box-shadow; тёмный текст (#0f172a/#475569); hero-mockup, мини-статы, start-flow, interactive zone, roadmap, iz-cta, advantages, features, updates, news, progress-card, guest-cta адаптированы; ~55 CSS-селекторов; navbar/HTML/JS/backend/маршруты не тронуты | 2026-06-17 |

---

## Текущий статус безопасности

| Угроза | Статус |
|---|---|
| Выполнение кода через отладчик | ✅ Устранено (debug=False) |
| Секреты в репозитории | ✅ Устранено (.env) |
| Неавторизованное изменение теории | ✅ Устранено (is_admin check) |
| CSRF в HTML-формах | ✅ Устранено |
| CSRF в JSON fetch | ✅ Устранено |
| CSRF в FormData fetch | ✅ Устранено |
| Отсутствие csrf.exempt | ✅ Подтверждено |
| Создание вариантов без прав | ✅ Устранено (is_admin на /api/variants/save) |
| Утечка ответов через /api/variant/preview | ✅ Устранено (is_admin на /api/variant/preview) |
| CSRF принудительного выхода (logout) | ✅ Устранено (GET→POST, CSRF-форма) |
| SQL-инъекции | ✅ Аудит проведён: 72 запроса, 0 уязвимостей; все параметризованы (`?`) |
| XSS (Stored) в admin_panel.html | ✅ Устранено (data-атрибут, v1.2.2) |
| XSS в replace_markers (app.py) | ✅ Устранено (whitelist-pipeline, v1.2.3) |
| XSS через `\| safe` в preparation_lesson | ✅ Устранено (`\| replace_markers`, v1.2.4) |
| Загрузка файлов (аватары) | Частично: проверка расширения, нет проверки MIME |
| Загрузка изображений задач (admin) | ✅ Устранено: extension + magic bytes + secure_filename + 5 МБ лимит (v1.4.0) |
| Orphaned files при дублировании task_id | ✅ Устранено: duplicate-check до сохранения файлов (v1.4.0) |
| Path traversal в delete_image | ✅ Устранено: safe_to_delete = to_delete & existing_paths (v1.4.0) |
| Загрузка task-файлов (admin) | ✅ Устранено: whitelist расширений + secure_filename + path traversal check (v1.4.0) |
| Orphaned task-файлы при замене | ✅ Устранено: старый файл удаляется перед сохранением нового (v1.4.0) |
| Orphaned files при удалении задачи (admin_task_delete) | ⏳ Не исправлено: файлы/изображения остаются на диске — отдельная задача |
| /clear_stats без явного auth-guard | ✅ Устранено (v1.2.5) |
| /clear_stats раскрывал str(e) в ответе | ✅ Устранено (generic-сообщение, v1.2.5) |
| /clear_stats не очищал user_task_answers | ✅ Устранено (double DELETE, v1.2.5) |
| /save_results и /finish_exam без auth-guard | ✅ Устранено (v1.2.5) |
| /save_results и /finish_exam принимали несуществующий variant_num | ✅ Устранено (404, v1.2.5) |
| Нет ограничения сохранений результатов | P3 Этап 2 — отложено (/save_results, /finish_exam) |

---

## Текущий этап

**Выполнено: визуальный редизайн главной страницы под светло-голубую тему (v1.6.0, 2026-06-17)**

| Итерация | Описание | Статус |
|---|---|---|
| v1.5.0 | Новая структура лендинга: hero, stats, features, footer | ✅ |
| v1.5.1 | Контент и интерактивность: «С чего начать», мини-задача, маршрут, преимущества | ✅ |
| v1.5.2 | Персонализация: прогресс, гость, калькулятор; dropdown navbar; мобильная версия | ✅ |
| v1.5.3 Этап 1 | Hero двухколоночный: mockup платформы справа, мини-статы | ✅ |
| v1.5.3 Этап 2 | stats-row полоса, start-flow маршрут, акценты секций, advantages-panel | ✅ |
| v1.5.3 Этап 3.1 | Feature Grid 2×2, порядок карточек по пользовательскому маршруту | ✅ |
| v1.5.3 Этап 3.2 | Контраст вторичного текста: `#64748b` → `#94a3b8`, 15 селекторов, WCAG AA | ✅ |
| v1.5.3 Этап 3.3 | Interactive Zone: мини-задача + калькулятор + маршрут в единой визуальной полосе | ✅ |
| v1.5.4 Этап 1 | Убран блок «Новые варианты»; усилена кнопка navbar («Разделы платформы») | ✅ |
| v1.5.4 Этап 2 | Последовательный сценарий: мини-задача → калькулятор → roadmap → CTA | ✅ |
| v1.5.4 Этап 3 | Roadmap-карточка результата (split-card); убраны фон и рамки .interactive-zone | ✅ |
| v1.5.5 Этап 1 | Устранение дублирования: stats-row удалён, hero-mini-stats сохранён | ✅ |
| v1.5.5 Этап 2 | Блок преимуществ переписан под боли ученика (маршрут/темы/прогресс/экзамен) | ✅ |
| v1.5.5 Этап 3 | Индикатор интерактивной зоны: именованные шаги (Задача/Готовность/Маршрут) | ✅ |
| v1.5.6 Этап 1 | Перенос progress-section/guest-cta-section после features-section | ✅ |
| v1.6.0 Этап 1 | Глобальные токены: body color, hero desc/tagline, section headings, btn-secondary | ✅ |
| v1.6.0 Этап 2 | Hero mockup и мини-статистика: белый фон, синяя тень, зелёные состояния | ✅ |
| v1.6.0 Этап 3 | Start-flow карточки: белый фон, синяя рамка, тёмный текст, дневные акценты | ✅ |
| v1.6.0 Этап 4 | Интерактивная зона: minitask, calculator, roadmap, iz-cta — адаптация всех состояний | ✅ |
| v1.6.0 Этап 5 | Advantages, features, updates, news — светлые, тёмный текст, синие рамки | ✅ |
| v1.6.0 Этап 6 | Progress-card (синие числа #1e40af), guest-cta-card — белый фон, синяя тень | ✅ |
| v1.6.0 Этап 7 | Глобальная проверка: все остатки rgba(255,255,255,0.0x) и #e2e8f0 вне navbar устранены | ✅ |

**Что сделано в v1.6.0:**
- Фон `body` заменён на светло-голубой небесный градиент (`#eaf6ff → #f5fbff → #eef8ff`)
- Все карточки переведены с тёмно-прозрачного фона (`rgba(255,255,255,0.04–0.06)`) на белый (`rgba(255,255,255,0.92–0.96)`)
- Добавлены мягкие голубые рамки `rgba(37,99,235,0.12–0.18)` и тени `0 N px M px rgba(37,99,235,0.07–0.12)`
- Весь основной текст в карточках переведён на `#0f172a`, вторичный — на `#475569`
- Hero mockup адаптирован: белый фон, синяя тень, зелёные состояния «правильно» вместо неоновых
- Интерактивная зона: minitask (синий акцент), calculator (фиолетовый), roadmap (зелёный) — акценты сохранены, но стали «дневными»
- Результирующие состояния (correct/incorrect/no-answer) переведены с неонового на пастельные с тёмным текстом
- Section-tags, iz-dots, iz-step-connectors, footer-border адаптированы
- HTML, JS, backend, navbar/logout/CSRF, маршруты — не тронуты; изменения только в CSS `templates/start.html`
- **Визуальная оценка:** страница стала светлее, дружелюбнее и значительно ближе к образовательной платформе; исчезла «геймерская» тёмная стилистика

**Что сделано в v1.5.6:**
- `progress-section` и `guest-cta-section` перемещены: были сразу после Hero, теперь — между «Что есть на платформе» и «Что нового»
- Пользователь сначала проходит воронку (маршрут → зона → преимущества → платформа), затем видит персональный блок
- Jinja2-условия, CSS, содержимое блоков, JS, backend — не тронуты

**Что сделано в v1.5.5:**
- `stats-row` удалён (HTML + CSS базовый + CSS 768px + CSS 480px) — дублирование 1200+/27/90+ устранено
- Блок преимуществ: 4 формулировки переписаны под боли ученика: маршрут / темы без пробелов / прогресс / экзамен без страха
- Индикатор зоны: вместо "Шаг N из 3 + три точки" — именованные шаги "Задача ● — Готовность ○ — Маршрут ○" с коннекторами и активной подсветкой подписи через `:has()`
- Логика сценария, JS-функции, navbar, footer, backend — не тронуты

**Что сделано в v1.5.4:**
- Блок «Новые варианты» удалён с главной (маршруты `/choose-mode/3,4,5` в backend сохранены)
- Navbar: «Разделы» → «Разделы платформы»; кнопка визуально усилена (`font-weight: 600`, светлее)
- Интерактивная зона: три параллельные секции → пошаговый сценарий ● ○ ○ / ● ● ○ / ● ● ●
- Roadmap оформлен как карточка результата (split-card вместе с CTA)
- `.interactive-zone` — удалены декоративный фон и рамки; только логическая обёртка и отступ

**v1.4.0 (расширенный редактор задач):**
- Панель форматирования (B/I/sup/sub), загрузка изображений, прикрепление файлов
- Все три этапа завершены; security checks пройдены

**Аудит безопасности (v1.3.0, итог):**

| Область | Статус |
|---|---|
| P0 (критические) | ✅ 4/4 закрыты |
| P1 (высокие) | ✅ 4/4 закрыты |
| P2 (средние) | ✅ 2/2 закрыты |
| XSS | ✅ 3/3 закрыты |
| P3 Этап 1 | ✅ 4/4 закрыты |
| SQL-инъекции | ✅ Аудит завершён, уязвимостей нет |
| Целостность данных D-1, D-2, D-3 | ✅ Все закрыты |
| P3 Этап 2 (double-submit) | ⏳ Отложено |
| Rate limiting, MIME аватаров, CSP | ⏳ Отложено |

**Следующий шаг:** наполнение базы задач для заданий 11–27 или дальнейшая визуальная доработка `start.html`
