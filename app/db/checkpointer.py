from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import Settings


@asynccontextmanager
async def get_checkpointer(settings: Settings):
    async with AsyncPostgresSaver.from_conn_string(settings.db_url) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
