---
name: ***Tools Telegram Bot Ecosystem
description: 6-bot Telegram ecosystem on one VPS — project context, stack, and conventions
type: project
originSessionId: 0797faee-5de4-42c9-a060-b8117d8910b6
---
Building ***Tools — 6 Telegram bots on a single VPS.

**Bots:** HubBot (@tools_bot), MediaBot (@tools_media_bot), PixelBot (@tools_pixel_bot), ToolsBot (@tools_util_bot), FunBot (@tools_fun_bot), LifeBot (@tools_life_bot)

**Stack:** Python 3.11, aiogram 3.x, PostgreSQL + asyncpg, Redis, Celery, Alembic, structlog, pydantic-settings

**Root dir:** /root/tools/

**Why:** Full production-grade bot ecosystem with shared infra (DB, Redis, Celery, limits, payments via Telegram Stars).

**How to apply:** Always write final working code, no skeletons. Texts in messages.py, not handlers. parse_mode=HTML globally. Heavy ops (ffmpeg, yt-dlp, rembg) only via Celery. Rate limit: 10 req/min per user in Redis. Files max 1hr, deleted by Celery Beat.

**Naming conventions:**
- handlers: handle_video_download, handle_bg_remove
- tasks: task_download_video, task_remove_bg
- callbacks: cb_quality_720p, cb_format_mp3

**Development order:** старт → HubBot → MediaBot → PixelBot → FunBot → ToolsBot → LifeBot → workers → deploy
