---
name: Graphify — Durak Graph Issues to Fix
description: Что нужно исправить при следующем /graphify на /root/durak
type: project
originSessionId: fc397544-a4cf-48fa-b8e9-abfe77d114d1
---
## Проблемы графа (запуск 2026-04-23, 332 nodes, 937 edges, 18 communities)

**Что попало лишнего:**
- `graphify-out/GRAPH_REPORT.md` и `graphify-out/graph.html` попали в corpus — нужно исключать папку `graphify-out/` из detect
- Скриншоты `server/screens/*.jpg` и emoji packs `web/packs/**/*.webp` — НЕ нужны (исправлено в CLAUDE.md: НЕ СМОТРИ СКРИНШОТЫ)

**Архитектурный инсайт (для редизайна):**
- `onmessage Handler` — bridge node между Game State & Rendering, UI Rendering Utilities, Friends UI, Screen Navigation & CSS
- Вся навигация по экранам идёт через один WebSocket обработчик — это точка роста сложности при добавлении новых экранов
- `connect()` и `handle()` — мосты через весь граф (betweenness 0.304 и 0.280)

**Why:** Граф показал что frontend монолитный — один onmessage обрабатывает и игровые события, и навигацию, и профиль. При редизайне стоит держать это в уме — не усугублять зацепленность.

**How to apply:** При следующем /graphify — исключить graphify-out/ и server/screens/ из detection вручную через `detect(Path('.'), exclude=['graphify-out', 'server/screens', 'web/packs'])` или переименовать перед запуском.
