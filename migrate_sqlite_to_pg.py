"""One-shot migration: SQLite durak.db → PostgreSQL."""
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
import asyncpg


def _coerce(value: object) -> object:
    """Convert SQLite string timestamps to datetime for asyncpg."""
    if not isinstance(value, str):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return value

SQLITE_PATH = Path(__file__).parent / "durak.db"
PG_URL = "postgresql://tools:password@localhost:5432/durak"

TABLES = [
    "users", "owned_cosmetics", "stats", "achievements",
    "friends", "user_packs", "user_pack_purchases", "clans", "clan_members",
]

# SQLite col → PG col overrides (type coercions handled at insert time)
PK_RESET = {"clans"}  # tables with BIGSERIAL — need to reset sequence after insert


async def main() -> None:
    if not SQLITE_PATH.exists():
        print(f"SQLite not found at {SQLITE_PATH}")
        return

    sqlite = sqlite3.connect(str(SQLITE_PATH))
    sqlite.row_factory = sqlite3.Row
    pg = await asyncpg.connect(PG_URL)

    for table in TABLES:
        cur = sqlite.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
        if not rows:
            print(f"  {table}: empty, skip")
            continue

        cols = rows[0].keys()
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        col_list = ", ".join(cols)

        # Determine ON CONFLICT strategy per table
        if table == "users":
            conflict = "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, username=EXCLUDED.username"
        elif table in ("owned_cosmetics", "achievements", "friends",
                       "user_pack_purchases", "clan_members", "stats"):
            conflict = "ON CONFLICT DO NOTHING"
        elif table == "clans":
            conflict = "ON CONFLICT (id) DO NOTHING"
        elif table == "user_packs":
            conflict = "ON CONFLICT (id) DO NOTHING"
        else:
            conflict = "ON CONFLICT DO NOTHING"

        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) {conflict}"

        inserted = 0
        for row in rows:
            values = [_coerce(row[c]) for c in cols]
            try:
                await pg.execute(sql, *values)
                inserted += 1
            except Exception as e:
                print(f"  {table} row error: {e} — {dict(zip(cols, values))}")

        print(f"  {table}: {inserted}/{len(rows)} rows")

        # Reset sequence for BIGSERIAL tables
        if table in PK_RESET:
            await pg.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), MAX(id)) FROM {table}")

    sqlite.close()
    await pg.close()
    print("Done.")


asyncio.run(main())
