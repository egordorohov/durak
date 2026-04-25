# Graph Report - /root/durak  (2026-04-25)

## Corpus Check
- 54 files · ~111,318 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 438 nodes · 1107 edges · 22 communities detected
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 267 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Frontend UI & Animations|Frontend UI & Animations]]
- [[_COMMUNITY_Bot AI & Game Logic|Bot AI & Game Logic]]
- [[_COMMUNITY_WebSocket Connection & Auth|WebSocket Connection & Auth]]
- [[_COMMUNITY_Database & Social|Database & Social]]
- [[_COMMUNITY_Architecture & Fake Players|Architecture & Fake Players]]
- [[_COMMUNITY_Fake Players & Rooms|Fake Players & Rooms]]
- [[_COMMUNITY_Pavel Durov Sticker Pack|Pavel Durov Sticker Pack]]
- [[_COMMUNITY_UI Screens & UX|UI Screens & UX]]
- [[_COMMUNITY_Auth & Redis Cache|Auth & Redis Cache]]
- [[_COMMUNITY_App Startup & Infra|App Startup & Infra]]
- [[_COMMUNITY_Meme Sticker Packs|Meme Sticker Packs]]
- [[_COMMUNITY_Telegram Bot|Telegram Bot]]
- [[_COMMUNITY_App State & Lobby|App State & Lobby]]
- [[_COMMUNITY_Legacy HTML (v0)|Legacy HTML (v0)]]
- [[_COMMUNITY_Cosmetics & Shop|Cosmetics & Shop]]
- [[_COMMUNITY_Profile & Avatars|Profile & Avatars]]
- [[_COMMUNITY_Clans & Friends|Clans & Friends]]
- [[_COMMUNITY_Bot Player Module|Bot Player Module]]
- [[_COMMUNITY_Hub Leave Logic|Hub Leave Logic]]
- [[_COMMUNITY_Fake Profiles List|Fake Profiles List]]
- [[_COMMUNITY_Redis URL Config|Redis URL Config]]
- [[_COMMUNITY_Uvicorn Dependency|Uvicorn Dependency]]

## God Nodes (most connected - your core abstractions)
1. `handle()` - 76 edges
2. `$()` - 58 edges
3. `Hub` - 42 edges
4. `_pool_get()` - 40 edges
5. `ws_endpoint()` - 36 edges
6. `dispatch()` - 34 edges
7. `RoomSettings` - 18 edges
8. `Room` - 18 edges
9. `run_bot()` - 17 edges
10. `send_state()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `GRAPH_REPORT.md — 18 communities: Bot Logic, DB Ops, Hub & Room Mgmt, Auth & Redis, Frontend, Card Logic, etc.` --references--> `Hub`  [EXTRACTED]
  graphify-out/GRAPH_REPORT.md → /root/durak/server/rooms.py
- `aiogram==3.13.1` --references--> `_bot_runner()`  [EXTRACTED]
  requirements.txt → /root/durak/server/main.py
- `God nodes — handle() 68 edges, $() 52, connect() 40, dispatch() 33, Hub 31, ws_endpoint() 24` --references--> `ws_endpoint()`  [EXTRACTED]
  graphify-out/GRAPH_REPORT.md → /root/durak/server/main.py
- `redis>=5.0.0` --references--> `get_redis()`  [EXTRACTED]
  requirements.txt → /root/durak/server/redis_client.py
- `fastapi==0.115.0` --references--> `FastAPI app — lifespan: init_db, room cleanup, pub/sub listener, fake players, bot runner`  [EXTRACTED]
  requirements.txt → server/main.py

## Hyperedges (group relationships)
- **Cross-Worker Matchmaking Pipeline — Redis queue + pub/sub + Hub** — rooms_queue_redis, rooms_pubsub_match, rooms_quick_play, main_pubsub_listener, rooms_hub [EXTRACTED 0.95]
- **Game Lifecycle — new_game → mark_ready → playing → FINISHED → _apply_result** — rooms_mark_ready, game_new_game, game_gamestate, game_phase, main_apply_result, rooms_broadcast [EXTRACTED 0.95]
- **AI Bot Pipeline — Hub.start_bot_task → run_bot → choose_attack/_best_defence/_should_take → game actions** — rooms_start_bot_task, bot_player_run_bot, bot_player_choose_attack, bot_player_best_defence, bot_player_should_take, game_attack, game_defend, game_take [EXTRACTED 1.00]
- **Auth & Redis Session Cache — Telegram initData → HMAC verify → Redis cache with TTL** — auth_verify_cached, auth_verify_signature, auth_cache_key, auth_session_ttl, redis_client_get_redis [EXTRACTED 1.00]
- **Cosmetics Economy — CATALOG → buy_cosmetic/buy_user_pack → adjust_coins → owned_cosmetics** — cosmetics_catalog, cosmetics_card_skins, cosmetics_emoji_packs, db_buy_cosmetic, db_buy_user_pack, db_adjust_coins, db_coin_constants [INFERRED 0.90]
- **Multi-Worker Architecture — primary lock, fake players on all workers, bot only on primary** — main_primary_worker, fake_players_start, main_bot_runner, redis_client_get_redis, rooms_pubsub_match [EXTRACTED 0.95]

## Communities

### Community 0 - "Frontend UI & Animations"
Cohesion: 0.06
Nodes (86): $(), animateDeal(), animateDone(), animateTake(), applyAvatar(), applySkins(), applyState(), autoAct() (+78 more)

### Community 1 - "Bot AI & Game Logic"
Cohesion: 0.08
Nodes (54): RANK_VALUE / RANK_VALUE_52 — client-side card rank lookup mirroring server constants, _best_defence(), _choose_attack(), _human_unacted(), _lowest_non_trump(), Simple AI opponent for single-player testing., True if a human eligible player hasn't thrown or passed yet this round., run_bot() (+46 more)

### Community 2 - "WebSocket Connection & Auth"
Cohesion: 0.07
Nodes (40): connect(), make_avatar(), Cosmetics catalog — card backs, table skins., _check_end(), God nodes — handle() 68 edges, $() 52, connect() 40, dispatch() 33, Hub 31, ws_endpoint() 24, _bot_runner(), _check_achievements(), _db_timer() (+32 more)

### Community 3 - "Database & Social"
Cohesion: 0.11
Nodes (49): accept_friend(), add_friend_request(), adjust_coins(), admin_set_coins(), admin_set_games(), admin_set_stat(), buy_cosmetic(), buy_user_pack() (+41 more)

### Community 4 - "Architecture & Fake Players"
Cohesion: 0.1
Nodes (13): BOT_IDS — sentinel pids -1, -2, -3 for AI bots, FAKE_IDS — set of negative pids (-1001…) for fake/decoy players, GRAPH_REPORT.md — 18 communities: Bot Logic, DB Ops, Hub & Room Mgmt, Auth & Redis, Frontend, Card Logic, etc., Knowledge Gaps — 47 isolated nodes; thin communities: SQLite DB, Telegram Bot, Redis Cache, get_redis(), redis>=5.0.0, Hub.cleanup_empty_rooms() — delete rooms with no real players idle > 300s, Hub (+5 more)

### Community 5 - "Fake Players & Rooms"
Cohesion: 0.16
Nodes (25): Exception, FakeWS, init_fake_players(), _play_one_game(), _player_loop(), Background fake players that populate lobbies and play real games., Seed bot profiles once. Uses Redis lock so only one worker runs this., Keeps one open 2-player room in the lobby.     Only goes ready when a real playe (+17 more)

### Community 6 - "Pavel Durov Sticker Pack"
Cohesion: 0.11
Nodes (26): Sticker pack 064f4a0c — Pavel Durov themed pack: portraits, stage, fan-head surreal meme, Sticker: Pavel Durov portrait in city setting — clean photo, recognizable Telegram founder face, Sticker: Surreal meme — businessman with electric fan as head against apocalyptic storm background, Sticker: Pavel Durov on stage in black outfit, 'TOKEN M2' branding visible — Telegram/TON event photo, Sticker: Pavel Durov looking sideways, outdoor nature background — candid/casual portrait, Sticker: Long-haired chubby man smirking on green screen background — reaction/meme sticker, Sticker: Young man biting finger/thumb — pensive or nervous expression, meme reaction style, Sticker pack 3328d12a — meme/reaction pack featuring Durov, bodybuilder, overweight man (+18 more)

### Community 7 - "UI Screens & UX"
Cohesion: 0.14
Nodes (18): Achievements Screen 13/58 (photo_8), Create Game Screen with Game Mode Selection (photo_3), Credits / In-App Currency Shop (photo_7), Friends List Screen (photo_6), Open Games Lobby with Filter Bar (photo_5), Private Games Lobby List (photo_4), Profile/Main Menu Screen (photo_1), Achievements List — 13/58 unlocked, credit-win milestones + league goals (+10 more)

### Community 8 - "Auth & Redis Cache"
Cohesion: 0.2
Nodes (10): durak:auth:{sha256} — Redis key pattern for verified auth sessions, Telegram WebApp initData verification with Redis token cache., Synchronous verification (used at startup). Returns user dict or None., Verify initData with Redis caching. Extends session TTL on each use., SESSION_TTL=3600 / MAX_AGE_SECONDS=86400 — Redis cache TTL and max token age, verify_init_data_cached() — verify initData with Redis caching; extends session TTL on each use, verify_init_data(), verify_init_data_cached() (+2 more)

### Community 9 - "App Startup & Infra"
Cohesion: 0.18
Nodes (11): init_db(), asyncpg connection pool — min_size=4 max_size=30, DATABASE_URL env, start_fake_players() — background task populating hub with fake lobby rooms on all workers, FastAPI app — lifespan: init_db, room cleanup, pub/sub listener, fake players, bot runner, _is_primary_worker() — Redis SET NX lock so only one worker runs Telegram bot polling, _coerce() — convert SQLite string timestamps to datetime for asyncpg, main() — one-shot SQLite→PostgreSQL migration, PK_RESET — tables with BIGSERIAL needing sequence reset after insert (clans) (+3 more)

### Community 10 - "Meme Sticker Packs"
Cohesion: 0.18
Nodes (11): Sticker Pack 3328d12a frame 0 — two people in blue and yellow bird costumes, Sticker Pack 3328d12a frame 1 — selfie meme with bald man, Sticker Pack 3328d12a frame 2 — Putin meme 'ЛАЙК — 1 ГОД ПРАВЛЕНИЯ', Sticker Pack ade46d95 frame 0 — meme text 'SEX СКОТИНА', Sticker Pack ade46d95 frame 1 — 'Boykisser energy' cat meme, Sticker Pack ade46d95 frame 2 — anime girl meme with Russian caption, Sticker Pack ade46d95 frame 3 — orange flower/decoration photo, Sticker Pack ade46d95 frame 4 — road sign parody meme with Russian text (+3 more)

### Community 11 - "Telegram Bot"
Cohesion: 0.7
Nodes (3): build_dispatcher(), Aiogram bot — entry point with WebApp button and invite links., run_bot()

### Community 12 - "App State & Lobby"
Cohesion: 0.4
Nodes (5): connect() — establish WebSocket to /ws, send initData auth, handle all server messages, app.js global state — ws, state, selected, prevTable, myCoins, myCardSkin, myId, myStats, myRank, Telegram WebApp initData — block direct browser access; only available inside Telegram client, Lobby tab system — profile, rooms (open+private), create room, leaderboard, clan, index.html — SPA screens: lobby (5 tabs), waiting, ready-check, game, end-screen, achievements, shop, friends, clan

### Community 13 - "Legacy HTML (v0)"
Cohesion: 0.5
Nodes (4): index_v0.html — Previous version of Durak Mini App, v0 Bottom nav — 6 tabs (profile/open/private/create/leaderboard/clan), v0 Tab: Open Rooms (div#tab-open) — separate tab, v0 Tab: Private Rooms (div#tab-private) — separate tab

### Community 14 - "Cosmetics & Shop"
Cohesion: 0.5
Nodes (4): CARD_SKINS — 10 card back skins: classic(free), dots/red(500), blue(750), cross/checkers/diamonds/waves(500-1000), dark/gold(1500), CATALOG — combined card_skins/table_skins/emoji_packs for shop API response, EMOJI_PACKS — 5 packs: classic(free), villain(500), winner(750), animals(1000), space(1500), FREE_IDS — set of cosmetic IDs with price=0 (auto-granted)

### Community 15 - "Profile & Avatars"
Cohesion: 0.67
Nodes (3): Profile Stats Popup with Animal Avatars (photo_2), Animal Avatar / Icon System in Profile Popup (bear x3, horse x1, lion x1), Player Stats Popup — season vs all-time stars, credits, trophies

### Community 16 - "Clans & Friends"
Cohesion: 1.0
Nodes (2): clans + clan_members tables — create_clan/join_clan/leave_clan/get_my_clan/get_clan_leaderboard, friends table + get_friends/add_friend_request/accept_friend/remove_friend — bidirectional friendship with pending/accepted status

### Community 18 - "Bot Player Module"
Cohesion: 1.0
Nodes (1): bot_player.py — Simple AI opponent for single-player testing

### Community 19 - "Hub Leave Logic"
Cohesion: 1.0
Nodes (1): Hub.leave() — remove player, cancel bot tasks, mark game FINISHED with survivor as winner

### Community 20 - "Fake Profiles List"
Cohesion: 1.0
Nodes (1): FAKE_PROFILES — 64 fake player profiles with realistic Russian names and win/loss stats for lobby population

### Community 21 - "Redis URL Config"
Cohesion: 1.0
Nodes (1): REDIS_URL env — default redis://localhost:6379/0

### Community 22 - "Uvicorn Dependency"
Cohesion: 1.0
Nodes (1): uvicorn[standard]==0.30.6

## Knowledge Gaps
- **85 isolated node(s):** `One-shot migration: SQLite durak.db → PostgreSQL.`, `Convert SQLite string timestamps to datetime for asyncpg.`, `Simple AI opponent for single-player testing.`, `True if a human eligible player hasn't thrown or passed yet this round.`, `Telegram WebApp initData verification with Redis token cache.` (+80 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Clans & Friends`** (2 nodes): `clans + clan_members tables — create_clan/join_clan/leave_clan/get_my_clan/get_clan_leaderboard`, `friends table + get_friends/add_friend_request/accept_friend/remove_friend — bidirectional friendship with pending/accepted status`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bot Player Module`** (1 nodes): `bot_player.py — Simple AI opponent for single-player testing`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Hub Leave Logic`** (1 nodes): `Hub.leave() — remove player, cancel bot tasks, mark game FINISHED with survivor as winner`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Fake Profiles List`** (1 nodes): `FAKE_PROFILES — 64 fake player profiles with realistic Russian names and win/loss stats for lobby population`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Redis URL Config`** (1 nodes): `REDIS_URL env — default redis://localhost:6379/0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Uvicorn Dependency`** (1 nodes): `uvicorn[standard]==0.30.6`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `handle()` connect `Database & Social` to `Frontend UI & Animations`, `Bot AI & Game Logic`, `WebSocket Connection & Auth`, `Architecture & Fake Players`, `Fake Players & Rooms`?**
  _High betweenness centrality (0.216) - this node is a cross-community bridge._
- **Why does `ws_endpoint()` connect `WebSocket Connection & Auth` to `Bot AI & Game Logic`, `Database & Social`, `Architecture & Fake Players`, `Fake Players & Rooms`, `Auth & Redis Cache`, `App State & Lobby`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `dispatch()` connect `Frontend UI & Animations` to `WebSocket Connection & Auth`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Are the 67 inferred relationships involving `handle()` (e.g. with `.get()` and `.vs_bot()`) actually correct?**
  _`handle()` has 67 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `_pool_get()` (e.g. with `init_fake_players()` and `ws_endpoint()`) actually correct?**
  _`_pool_get()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `ws_endpoint()` (e.g. with `.get()` and `send_error()`) actually correct?**
  _`ws_endpoint()` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `One-shot migration: SQLite durak.db → PostgreSQL.`, `Convert SQLite string timestamps to datetime for asyncpg.`, `Simple AI opponent for single-player testing.` to the rest of the system?**
  _85 weakly-connected nodes found - possible documentation gaps or missing edges._