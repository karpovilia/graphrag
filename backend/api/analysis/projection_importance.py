"""Projection importance — which latent two-mode projection matters.

Given a built graph whose ``multiprojection`` projector materialized one or
more latent projections as ``DERIVED`` edges (grouped by
``attributes.projection``), this ranks the projections by how much
*non-redundant* structure each one carries. A projection that merely
restates what others already say is redundant; one that is distinct is
"important".

Two signals are reported:

* **Structural reducibility (De Domenico et al., *Structural reducibility
  of multilayer networks*, Nat. Commun. 2015).** Each projection is a
  weighted graph; its density matrix is ρ = L / tr(L) (L the combinatorial
  Laplacian). The von Neumann entropy H(ρ) = −Σ λ log λ and the quantum
  Jensen–Shannon divergence JSD(ρᵢ,ρⱼ) = H((ρᵢ+ρⱼ)/2) − ½(H(ρᵢ)+H(ρⱼ))
  give a redundancy matrix; a projection's distinctiveness is its mean JSD
  to the others. Low-JSD pairs are merge candidates. (Computed when the
  union node set is small enough; otherwise omitted.)
* **Structural overlap (always computed, cheap).** Cosine distance between
  projections over their shared node-pair weight vectors, plus each
  projection's fraction of node-pairs unique to it.

Output is a ranking; the top projection is the most distinct.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from api.domain.graph import EdgeType
from api.domain.types import DomainModel, Id
from api.strategies.state import GraphBuildState

_MAX_NODES_FOR_SPECTRAL = 1500  # eigendecomposition is O(n^3); cap it.


class ProjectionStat(DomainModel):
    name: str
    n_nodes: int
    n_pairs: int
    total_weight: float
    unique_pair_fraction: float
    """Fraction of this projection's node-pairs present in no other projection."""
    distinctiveness_overlap: float
    """Mean cosine distance (1 − cos) to the other projections' pair-weight vectors."""
    von_neumann_entropy: float | None = None
    distinctiveness_jsd: float | None = None
    """Mean quantum Jensen–Shannon divergence to the other projections (reducibility)."""


class ProjectionImportanceResult(DomainModel):
    variant_id: Id
    projections: list[ProjectionStat]
    """Ranked: most distinct first (by JSD when available, else overlap)."""
    most_redundant_pair: list[str] | None = None
    """The two projection names with the lowest pairwise JSD — merge candidates."""
    spectral_computed: bool
    note: str | None = None


def _pair(a: Id, b: Id) -> tuple[Id, Id]:
    return (a, b) if str(a) < str(b) else (b, a)


def _collect_projections(
    state: GraphBuildState, *, include_direct: bool
) -> dict[str, dict[tuple[Id, Id], float]]:
    """Group edges into named projections → {pair: weight}."""
    out: dict[str, dict[tuple[Id, Id], float]] = defaultdict(dict)
    for e in state.edges:
        if e.source_node_id == e.target_node_id:
            continue
        if e.type == EdgeType.DERIVED:
            name = str((e.attributes or {}).get("projection") or "derived")
            w = float(e.weight) if e.weight is not None else 1.0
        elif include_direct and e.type == EdgeType.ENTITY_RELATION:
            name = "direct:entity_relation"
            w = float(e.weight) if e.weight is not None else 1.0
        else:
            continue
        key = _pair(e.source_node_id, e.target_node_id)
        # keep the stronger weight if a pair appears twice within a projection
        prev = out[name].get(key)
        out[name][key] = w if prev is None else max(prev, w)
    return dict(out)


def compute_projection_importance(
    state: GraphBuildState,
    variant_id: Id,
    *,
    include_direct: bool = True,
    max_nodes_for_spectral: int = _MAX_NODES_FOR_SPECTRAL,
) -> ProjectionImportanceResult:
    projections = _collect_projections(state, include_direct=include_direct)

    if not projections:
        return ProjectionImportanceResult(
            variant_id=variant_id,
            projections=[],
            spectral_computed=False,
            note="no DERIVED projections found — run the multiprojection projector first",
        )

    names = sorted(projections)

    # ---- cheap structural overlap (always) ----
    all_pairs = sorted({p for pairs in projections.values() for p in pairs}, key=str)
    pair_idx = {p: i for i, p in enumerate(all_pairs)}
    vecs: dict[str, np.ndarray] = {}
    for name in names:
        v = np.zeros(len(all_pairs))
        for p, w in projections[name].items():
            v[pair_idx[p]] = w
        vecs[name] = v

    pair_membership: dict[tuple[Id, Id], int] = defaultdict(int)
    for name in names:
        for p in projections[name]:
            pair_membership[p] += 1

    def cos_dist(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if na == 0 or nb == 0:
            return 1.0
        return 1.0 - float(np.dot(a, b) / (na * nb))

    overlap_dist: dict[str, float] = {}
    for name in names:
        others = [m for m in names if m != name]
        overlap_dist[name] = (
            float(np.mean([cos_dist(vecs[name], vecs[m]) for m in others]))
            if others
            else 0.0
        )

    unique_frac: dict[str, float] = {}
    for name in names:
        pairs = projections[name]
        if not pairs:
            unique_frac[name] = 0.0
            continue
        uniq = sum(1 for p in pairs if pair_membership[p] == 1)
        unique_frac[name] = uniq / len(pairs)

    # ---- spectral reducibility (von Neumann + quantum JSD) ----
    union_nodes = sorted(
        {n for pairs in projections.values() for pr in pairs for n in pr}, key=str
    )
    spectral = len(union_nodes) <= max_nodes_for_spectral and len(union_nodes) >= 2
    entropy: dict[str, float] = {}
    jsd_dist: dict[str, float] = {}
    most_redundant: list[str] | None = None
    note: str | None = None

    if spectral:
        nidx = {n: i for i, n in enumerate(union_nodes)}
        N = len(union_nodes)
        rho: dict[str, np.ndarray] = {}
        for name in names:
            W = np.zeros((N, N))
            for (a, b), w in projections[name].items():
                ia, ib = nidx[a], nidx[b]
                W[ia, ib] = w
                W[ib, ia] = w
            deg = W.sum(axis=1)
            L = np.diag(deg) - W
            tr = float(np.trace(L))
            rho[name] = L / tr if tr > 0 else L
            entropy[name] = _von_neumann_entropy(rho[name])

        jmat: dict[tuple[str, str], float] = {}
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                j = _quantum_jsd(rho[a], rho[b], entropy[a], entropy[b])
                jmat[(a, b)] = j
                jmat[(b, a)] = j
        for name in names:
            others = [m for m in names if m != name]
            jsd_dist[name] = (
                float(np.mean([jmat[(name, m)] for m in others])) if others else 0.0
            )
        if len(names) >= 2:
            pair_min = min(
                ((a, b) for i, a in enumerate(names) for b in names[i + 1 :]),
                key=lambda ab: jmat[ab],
            )
            most_redundant = list(pair_min)
    else:
        note = (
            f"spectral reducibility skipped: union node set "
            f"({len(union_nodes)}) outside [2, {max_nodes_for_spectral}]"
        )

    stats = [
        ProjectionStat(
            name=name,
            n_nodes=len({n for pr in projections[name] for n in pr}),
            n_pairs=len(projections[name]),
            total_weight=float(sum(projections[name].values())),
            unique_pair_fraction=round(unique_frac[name], 4),
            distinctiveness_overlap=round(overlap_dist[name], 4),
            von_neumann_entropy=round(entropy[name], 4) if name in entropy else None,
            distinctiveness_jsd=round(jsd_dist[name], 6) if name in jsd_dist else None,
        )
        for name in names
    ]
    stats.sort(
        key=lambda s: (
            s.distinctiveness_jsd if s.distinctiveness_jsd is not None else -1.0,
            s.distinctiveness_overlap,
        ),
        reverse=True,
    )

    return ProjectionImportanceResult(
        variant_id=variant_id,
        projections=stats,
        most_redundant_pair=most_redundant,
        spectral_computed=spectral,
        note=note,
    )


def _von_neumann_entropy(rho: np.ndarray) -> float:
    """H(ρ) = −Σ λ log λ over eigenvalues of the (symmetric, PSD) ρ."""
    vals = np.linalg.eigvalsh(rho)
    vals = vals[vals > 1e-12]
    if vals.size == 0:
        return 0.0
    return float(-np.sum(vals * np.log(vals)))


def _quantum_jsd(
    rho_a: np.ndarray, rho_b: np.ndarray, h_a: float, h_b: float
) -> float:
    """Quantum Jensen–Shannon divergence between two density matrices."""
    mix = 0.5 * (rho_a + rho_b)
    h_mix = _von_neumann_entropy(mix)
    val = h_mix - 0.5 * (h_a + h_b)
    return max(0.0, val)


__all__ = ["compute_projection_importance", "ProjectionImportanceResult", "ProjectionStat"]
