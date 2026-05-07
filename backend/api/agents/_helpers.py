from __future__ import annotations

from typing import Iterable

from api.domain.graph import Layer, Node


def lemma_key(node: Node) -> str:
    """Stable bucket key for the node's "name root" in lowercase.

    Prefers the lemma that NerExtractionBuilder stuffs into
    `node.attributes['lemma']`. Falls back to the lowercased first
    whitespace-separated token of `node.name`. Empty string if the
    name is empty (caller should skip those).
    """

    lemma = node.attributes.get("lemma") if node.attributes else None
    if lemma:
        return str(lemma).lower()
    if not node.name or not node.name.strip():
        return ""
    return node.name.strip().split()[0].lower()


def entity_nodes(nodes: Iterable[Node]) -> list[Node]:
    return [n for n in nodes if n.layer == Layer.ENTITY]
