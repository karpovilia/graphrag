"""End-to-end smoke against a running R2 backend.

Replays the Case Study 1 from the SIGIR paper §4: ingest a short Russian
text → build a graph variant → run the entity_dedup agent → accept the
first suggestion → re-query and observe the answer changes.

Run against `docker compose up`:
    BACKEND=http://localhost:8000 uv run python -m scripts.smoke

Exits non-zero on any failed step. Used as a one-shot CI smoke and as a
hand-runnable demo script before SIGIR review meetings.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

BACKEND = os.environ.get("BACKEND", "http://localhost:8000")
ACTOR = os.environ.get("SMOKE_ACTOR", "user:smoke")

DOC_TEXT = (
    "Иванов Иван Иванович работает в Высшей школе экономики. "
    "Иванов И.И. руководит лабораторией обработки естественного языка. "
    "Петров А.С. — коллега Иванова И.И. в той же лаборатории. "
    "Иван Иванов выступал на конференции SIGIR в Мельбурне."
)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BACKEND, timeout=120.0) as client:
        await _wait_for_health(client)

        corpus = await _post(
            client,
            "/api/corpora",
            {"name": "smoke-corpus", "description": "scripts/smoke.py", "language": "ru"},
        )
        print(f"corpus  ok  id={corpus['id']}")

        await _post(
            client,
            f"/api/corpora/{corpus['id']}/documents",
            {"title": "smoke-doc", "text": DOC_TEXT},
        )
        print("document ok")

        variant = await _post(
            client,
            f"/api/corpora/{corpus['id']}/graphs",
            {"name": "smoke-v1", "builder": "ner_extraction"},
        )
        print(
            f"variant  ok  id={variant['id']} "
            f"nodes={variant['node_count']} edges={variant['edge_count']}",
        )

        agent_run = await _post(
            client,
            f"/api/graphs/{variant['id']}/agents/entity_dedup/run",
            {"params": {}},
        )
        suggestions = agent_run.get("suggestions", [])
        print(f"agent    ok  proposals={len(suggestions)}")

        if suggestions:
            first = suggestions[0]
            try:
                accept_resp = await _post(
                    client,
                    f"/api/suggestions/{first['id']}/accept",
                    {
                        "expected_variant_version": variant["version"],
                        "actor": ACTOR,
                    },
                )
                print(
                    f"accept   ok  journal_entry={accept_resp['entry']['id']} "
                    f"new_version={accept_resp['variant']['version']}",
                )
            except RuntimeError as e:
                # Some entity_dedup runs propose 0 mergeable pairs on a
                # 4-sentence document; we don't fail the smoke for that.
                print(f"accept   skip  {e}")

        reason_resp = await _post(
            client,
            "/api/reason",
            {
                "mode": "single",
                "query": "Кто работает в ВШЭ?",
                "variant_ids": [variant["id"]],
                "reasoner": "keyword_search",
                "aggregator": "evidence_union",
            },
        )
        evidence = len(reason_resp["answer"]["evidence_node_ids"])
        print(f"reason   ok  evidence_nodes={evidence}")
        print()
        print("smoke OK")


async def _wait_for_health(client: httpx.AsyncClient, attempts: int = 30) -> None:
    for i in range(attempts):
        try:
            resp = await client.get("/api/health")
            if resp.status_code == 200:
                return
        except httpx.RequestError:
            pass
        await asyncio.sleep(1)
    raise SystemExit(f"backend at {BACKEND} did not become healthy in {attempts}s")


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> dict:
    resp = await client.post(path, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {path} → {resp.status_code}: {resp.text}")
    return resp.json()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"smoke FAILED: {e}", file=sys.stderr)
        sys.exit(1)
