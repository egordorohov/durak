---
name: Durak Card Game — Current State & Pending Tasks
description: /root/durak — Telegram Mini App дурак 2-4 игрока, текущий стек и задачи
type: project
originSessionId: 54ce5e2e-e0fb-412e-ab15-40b4d9b1b971
---
## Проект

`/root/durak/` — Telegram Mini App, подкидной/переводной дурак, 2-4 игрока, 36/52 карт.

- **Frontend**: `/root/durak/web/` — `index.html`, `style.css`, `app.js?v=52`
- **Backend**: `/root/durak/server/` — FastAPI, WebSocket, `game.py`, `rooms.py`, `main.py`
- **Graphify граф**: `/root/durak/graphify-out/` — `graph.html`, `graph.json`, `GRAPH_REPORT.md` (обновлён 2026-04-23)

---

## 🔴 ГЛАВНАЯ ЗАДАЧА: Полный редизайн UI (все экраны)

**Why:** Игровой стол и меню магазина выглядят красиво, всё остальное уродски. Нужен единый дизайн-язык на миллионную аудиторию.

**How to apply:** При любой работе с frontend держать в уме — итоговая цель полный redress всех экранов к единому стилю. Не добавлять "быстрые фиксы" в старом стиле.

### Экраны с проблемами (приоритет переделки):
- **Лобби** (profile tab, rooms list, create game) — разношёрстный, без единого стиля
- **Waiting** ✅ переделан 2026-04-23 v=45 (animated dots, code-box как карточка)
- **Ready Check** ✅ переделан 2026-04-23 v=45 (rc-players-row, card-style per-player, .ready state)
- **Лидерборд** ✅ переделан 2026-04-23 (podium top-3, win-bar, rank chip)
- **Друзья** ✅ переделан 2026-04-23 v=45 (friend-avatar + online-dot, friend-info)
- **Friend Profile** ✅ переделан 2026-04-23 v=45 (stats как bordered grid, rank-bar улучшен)
- **Достижения** ✅ переделан 2026-04-23 v=45 (2-col grid, card-style, data-suit декор, grayscale locked)
- **Клан** ✅ переделан 2026-04-23 v=48 (clan-header с ♠ декором, stats-row bordered grid, form-actions, .owner highlight, clan-empty-icon)
- **Rooms list** ✅ переделан 2026-04-23 v=45 (suit icon, room-body, bet chip)
- **Профиль popup** — нормально, но можно лучше
- **Admin Panel** — не приоритет

### Дизайн-ориентиры (что нравится, держать стиль):
- Игровой стол (`#game`) — анимации, карточки, флэш-сообщения ✅
- Магазин (emoji packs, market-card) — карточки с рамками, округления ✅
- Кнопки лобби (карточный стиль: var(--fg) border, масти, JetBrains Mono) ✅

### Дизайн-принципы для нового UI:
- CSS-переменные только через `var(--fg)`, `var(--bg)`, `var(--line)`, `var(--red)` — НЕ `--text`, `--accent` (не определены)
- `color-mix(in srgb, var(--fg) X%, transparent)` для dimmed текста
- Border-radius: 12-14px для карточек, 8px для чипов
- Везде `transition` на hover/active
- Тёмная тема — основная, светлая — поддерживается

---

## Обновления (2026-04-23, v=48)

1. **Клан (финал)** — `clan-form-actions` вокруг кнопок форм, `.owner` класс на строке владельца в JS
2. **Bug: profile stats** — `myId` из lobby, `isMe = msg.target_id === myId` в `profile_data`
3. **Bug: custom stickers** — emoji validation на сервере проверяет `/static/packs/{user_pack}/` prefix
4. **Bug: E'" в никах клана** — член клана рендерится через DOM methods (`.textContent`), не `innerHTML`

---

## Обновления (2026-04-23, v=47 → v=45)

1. **Waiting** — animated search dots, code-box как карточка с border/bg
2. **Ready Check** — rc-players-row side-by-side, .rc-player-card с .ready state (border highlight + label)
3. **Achievements** — 2-col grid, card-style с data-suit декором, grayscale для locked
4. **Clan tab** — clan-header card, clan-stats-row с chips, формы с рамкой, fixed --bg2/--accent → proper vars
5. **Friends** — friend-avatar + online-dot (зелёный/серый), friend-info структура
6. **Friend Profile** — fp-stats как bordered grid с border-radius, rank-bar 6px rounded
7. **Rooms list** — suit icon, room-body, отдельный bet chip

---

## Обновления (2026-04-23, v=44)

1. **Лидерборд редизайн** — podium top-3 (gold/silver/bronze gradient + badge), win-bar прогресс, rank-chip, исправлены сломанные CSS vars по всему style.css
2. **Graphify граф обновлён** — 361 узел, 1048 рёбер, 21 community

---

## Обновления (2026-04-23, v=39)

1. **Confirm удаления из друзей** — `showConfirm()` перед `friend_remove`
2. **Лобби кнопки** — стиль игральных карт: жирная рамка var(--fg), масти ♠♣♦, Магазин красный (♦), JetBrains Mono метки
3. **Стикеры в магазине** — `renderEmojiPackShop` переработан
4. **Новые скины** — рубашки: Красная/Синяя/Золото/Шашки/Ромбы; столы: Красное/Фиолет/Золотое/Чёрное
5. **Правила 3/4 игроков** — `_throwing_eligible()` в game.py
6. **Лидерборд → профили** — клик по строке открывает popup профиля
7. **Карты соперника** — перекрытие через `margin-left: -5px`

---

## Архитектура

- `game.py`: игровая логика (attack, defend, transfer, take, done, pass_turn)
- `rooms.py`: Hub, матчмейкинг, rooms, ready check, send_state
- `main.py`: FastAPI WebSocket handler, БД, магазин, достижения
- `db.py`: SQLite (aiosqlite) — users, stats, cosmetics, achievements, friends
- `ranks.py`: военные ранги рф (14 рангов), get_rank(), get_rank_progress()
- `bot_player.py`: AI бот
- `auth.py`: Telegram initData verify + Redis session cache

## Что реализовано (полный список фич)

- Мобильный layout, карточный UI, анимации (deal, done→discard, take)
- Звуки (cardPlay, cardDefend, done, take, deal, tick, win, lose)
- Козырь: trump-card-area + trump-suit-only
- Таймер хода 30с + авто-действие
- Внутренняя валюта + магазин скинов
- Экран завершения (победа/поражение + монеты)
- Флэш-сообщения БИТО/БЕРУ/ПЕРЕВОД
- Стопка "бито" (discard pile) с анимацией
- Тёмная тема + светлая тема toggle
- Лобби: быстрая игра, против бота, создать игру (2-4 игрока, 36/52 карт, режим, пароль)
- Открытые + приватные комнаты (merged в один таб)
- Ready check экран с таймером 10с
- Профиль: аватарка, ранги как погоны (рядовой → маршал), статистика
- Прогресс-бар ранга в popup профиля
- Достижения (15 видов)
- Друзья (добавить по @username), friend profile экран
- Переводной дурак: ячейка перевода на столе
- Пасовать (Пас кнопка для 3-4 игроков)
- Мультиплеер 3-4 игрока: динамический opponents zone
- Admin Panel (для ADMIN_IDS)
- Клан система
- Marketplace пользовательских стикер-паков
- Disconnect overlay с reconnect таймером
- Лидерборд: players/clans × games/coins
