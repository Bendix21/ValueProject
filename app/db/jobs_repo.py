import psycopg
from psycopg.rows import dict_row

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    target_url TEXT NOT NULL,
    max_scenarios INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

ADD_MAX_PAGES_COLUMN_SQL = "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS max_pages INTEGER"
ADD_TARGET_TYPE_COLUMN_SQL = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS target_type TEXT NOT NULL DEFAULT 'web_app'"
)


async def setup(db_url: str) -> None:
    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        await conn.execute(CREATE_TABLE_SQL)
        await conn.execute(ADD_MAX_PAGES_COLUMN_SQL)
        await conn.execute(ADD_TARGET_TYPE_COLUMN_SQL)
        await conn.commit()


async def insert_job(
    db_url: str,
    job_id: str,
    target_url: str,
    max_scenarios: int | None,
    max_pages: int | None,
    target_type: str = "web_app",
) -> None:
    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        await conn.execute(
            "INSERT INTO jobs (job_id, target_url, max_scenarios, max_pages, target_type) "
            "VALUES (%s, %s, %s, %s, %s)",
            (job_id, target_url, max_scenarios, max_pages, target_type),
        )
        await conn.commit()


async def list_jobs(db_url: str) -> list[dict]:
    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT job_id, target_url, max_scenarios, max_pages, target_type, created_at "
                "FROM jobs ORDER BY created_at DESC"
            )
            rows = await cur.fetchall()
    return [
        {
            "job_id": row["job_id"],
            "target_url": row["target_url"],
            "max_scenarios": row["max_scenarios"],
            "max_pages": row["max_pages"],
            "target_type": row["target_type"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
