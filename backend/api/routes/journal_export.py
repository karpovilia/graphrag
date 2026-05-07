"""Journal export endpoints (Phase 3.6).

Produces JSON or CSV streams of a variant's curation journal — needed
for the SIGIR paper's reproducible reporting story (each table in §4
should cite a journal export to reproduce the exact edit sequence).
"""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.domain.types import Id
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["journal_export"])


@router.get("/graphs/{variant_id}/journal/export")
async def export_journal(
    variant_id: Id,
    format: str = Query("json", pattern="^(json|csv)$"),
    repo: RepositoryProtocol = Depends(get_repository),
) -> StreamingResponse:
    try:
        entries = await repo.list_journal(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if format == "json":
        body = json.dumps(
            [json.loads(e.model_dump_json()) for e in entries],
            ensure_ascii=False,
            indent=2,
        )
        media_type = "application/json"
        suffix = "json"
    else:  # csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "graph_variant_id",
                "op",
                "actor",
                "parent_entry_id",
                "created_at",
                "payload",
            ]
        )
        for e in entries:
            writer.writerow(
                [
                    str(e.id),
                    str(e.graph_variant_id),
                    e.op.value,
                    e.actor,
                    str(e.parent_entry_id) if e.parent_entry_id else "",
                    e.created_at.isoformat(),
                    json.dumps(e.payload, ensure_ascii=False),
                ]
            )
        body = buf.getvalue()
        media_type = "text/csv"
        suffix = "csv"

    headers = {
        "Content-Disposition": f'attachment; filename="journal-{variant_id}.{suffix}"'
    }
    return StreamingResponse(
        iter([body.encode("utf-8")]),
        media_type=media_type,
        headers=headers,
    )
