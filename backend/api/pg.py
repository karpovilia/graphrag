import sys

from asyncpg.pool import (
    Pool,
    create_pool,
)
from loguru import logger
from settings import settings


class DataBase:
    pool: Pool | None = None


db = DataBase()


async def connect():
    logger.info('msg="Initializing PostgreSQL connection"')

    try:
        db.pool = await create_pool(
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
            host=settings.PG_HOST,
            port=settings.PG_PORT,
            database=settings.PG_DATABASE,
            min_size=1,
            max_size=10,
            max_inactive_connection_lifetime=60,
        )

    except Exception as exc:
        logger.error('msg="Failed connect to PostgreSQL"')
        logger.error(str(exc))
        sys.exit(1)

    logger.success('msg="Successfully initialized PostgreSQL connection"')


async def disconnect():
    logger.info('msg="Closing PostgreSQL connection"')
    if db.pool is None:
        logger.warning('msg="No connection pool"')
        return
    await db.pool.close()


def get_connection_pool() -> Pool:
    if db.pool is None:
        logger.error('msg="No connection pool"')
        sys.exit(1)

    return db.pool


async def check_historical_prompt_response(
    pg: Pool, text: str, nodes: list[str] | None = None
) -> str | None:
    async with pg.acquire() as conn:
        async with conn.transaction():
            if not nodes:
                nodes = []

            rows = await conn.fetch(
                """
                SELECT
                    ph.prompt,
                    ph.response,
                    COALESCE(array_agg(psn.node) FILTER (WHERE psn.node IS NOT NULL), '{}') AS nodes
                FROM prompt_histories ph
                LEFT JOIN prompt_selected_nodes psn ON psn.prompt_id = ph.id
                WHERE ph.prompt = $1
                GROUP BY ph.id
                ORDER BY ph.id DESC;
                """,
                text,
            )

            for row in rows:
                row_nodes = row["nodes"]
                if sorted(row_nodes) == sorted(nodes):
                    return row["response"]

            return None


async def save_prompt_response(
    pg: Pool, prompt: str, response: str, selected_nodes: list[str] | None, graph: str
) -> None:
    async with pg.acquire() as conn:
        async with conn.transaction():
            prompt_id = await conn.fetchrow(
                "INSERT INTO prompt_histories (prompt, response, graph) VALUES ($1, $2, $3) RETURNING id",
                prompt,
                response,
                graph,
            )
            if prompt_id:
                prompt_id = prompt_id[0]
            else:
                logger.error(
                    'msg="Smth goes wrong while saving prompt. Prompt_id None"'
                )
                return

            if selected_nodes and prompt_id:
                await conn.executemany(
                    "INSERT INTO prompt_selected_nodes (prompt_id, node) VALUES ($1, $2)",
                    [(prompt_id, node) for node in selected_nodes],
                )


async def get_prompts_history(pg: Pool, graph: str) -> list[dict]:
    async with pg.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT
                    ph.prompt,
                    COALESCE(array_agg(psn.node) FILTER (WHERE psn.node IS NOT NULL), '{}') AS nodes
                FROM prompt_histories ph
                LEFT JOIN prompt_selected_nodes psn ON psn.prompt_id = ph.id
                WHERE ph.graph = $1
                GROUP BY ph.id
                ORDER BY ph.id DESC;
                """,
                graph,
            )

            return [{"prompt": row["prompt"], "nodes": row["nodes"]} for row in rows]
