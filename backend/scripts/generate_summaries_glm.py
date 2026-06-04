"""Backfill entity-node summaries via the local GLM (SSH tunnel to .2.48).

For every entity node (optionally only those lacking a summary), gather the
text of the chunks it's MENTIONED_IN and ask GLM to write a 2–4 sentence
factual summary. Summaries are written in bulk via replace_state → one snapshot
save (not 441 journal appends).

Run with the backend STOPPED (it owns the in-memory repo + state.json); restart
it afterwards so it picks up the new snapshot.

    GLM tunnel:  ssh -L 18000:10.42.0.200:8000 user@192.168.2.48
    Usage:       uv run python scripts/generate_summaries_glm.py <variant_id> [--all] [--concurrency 8]
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from api.domain.graph import EdgeType, Layer
from api.llm.base import CompletionParams, Message
from api.llm.openai_compat import OpenAICompatClient
from api.runtime import get_repository

_SYSTEM = (
    "Ты пишешь краткие фактические summary для узлов графа знаний. Отвечай на "
    "языке исходных фрагментов. 2–4 предложения, без списков и без преамбулы "
    "вроде «Этот узел…»."
)


def _snippet(text: str, start: int, end: int, pad: int = 120) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return text[lo:hi].strip()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("variant_id")
    ap.add_argument("--all", action="store_true", help="Regenerate even nodes that already have a summary.")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--base-url", default="http://127.0.0.1:18000/v1")
    ap.add_argument("--model", default="glm-4.7-flash")
    ap.add_argument("--max-chunks", type=int, default=6)
    args = ap.parse_args()

    vid = UUID(args.variant_id)
    repo = get_repository()
    variant = await repo.get_variant(vid)
    state = await repo.load_state(vid)
    docs = {str(d.id): d for d in await repo.list_documents(variant.corpus_id)}
    nodes_by_id = {str(n.id): n for n in state.nodes}

    # entity -> chunk ids via MENTIONED_IN (either direction)
    chunks_of: dict[str, list[str]] = {}
    for e in state.edges:
        if e.type != EdgeType.MENTIONED_IN:
            continue
        s, t = str(e.source_node_id), str(e.target_node_id)
        for a, b in ((s, t), (t, s)):
            na = nodes_by_id.get(a)
            if na is not None and na.layer == Layer.ENTITY:
                chunks_of.setdefault(a, [])
                if b not in chunks_of[a]:
                    chunks_of[a].append(b)

    targets = [
        n
        for n in state.nodes
        if n.layer == Layer.ENTITY
        and (args.all or not n.summary)
        and chunks_of.get(str(n.id))
    ]
    print(f"variant {args.variant_id}: {len(targets)} entity nodes to summarize "
          f"(of {sum(1 for n in state.nodes if n.layer == Layer.ENTITY)} entities)")
    if not targets:
        return

    llm = OpenAICompatClient(api_key="EMPTY", base_url=args.base_url, default_model=args.model)
    params = CompletionParams(
        temperature=0.2,
        max_tokens=300,
        extra={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
    )
    sem = asyncio.Semaphore(args.concurrency)
    done = 0
    lock = asyncio.Lock()

    async def summarize(node) -> None:
        nonlocal done
        snippets: list[str] = []
        for cid in chunks_of.get(str(node.id), [])[: args.max_chunks]:
            ch = nodes_by_id.get(cid)
            prov = ch.provenance[0] if ch and ch.provenance else None
            doc = docs.get(str(prov.document_id)) if prov else None
            if doc and doc.text and prov:
                snippets.append(_snippet(doc.text, prov.span_start, prov.span_end))
        if not snippets:
            return
        user = (
            f"Сущность: {node.name}\nТип: {node.type}\n"
            "Фрагменты (через ---):\n\n" + "\n\n---\n\n".join(snippets) + "\n\nSummary:"
        )
        async with sem:
            try:
                res = await llm.complete(
                    [Message(role="system", content=_SYSTEM), Message(role="user", content=user)],
                    params,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {node.name}: {exc}")
                return
        text = (res.text or "").strip()
        if text:
            node.summary = text  # Node is mutable (frozen=False)
        async with lock:
            done += 1
            if done % 25 == 0:
                print(f"  …{done}/{len(targets)}")

    await asyncio.gather(*(summarize(n) for n in targets))
    await repo.replace_state(vid, state)
    filled = sum(1 for n in state.nodes if n.layer == Layer.ENTITY and n.summary)
    print(f"done: {done} summaries generated; {filled} entities now have a summary. Snapshot saved.")


if __name__ == "__main__":
    asyncio.run(main())
