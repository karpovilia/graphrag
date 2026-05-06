"""POST /api/eda — exploratory analysis over an in-flight upload.

Wizard step 3 calls this with the freshly uploaded documents (already
written to staging by step 1). Returns the rule-based recommendation
that pre-fills the rest of the wizard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.types import DomainModel, Id, new_id
from api.eda import EdaReport, EdaService
from api.eda.ner import NerProtocol
from api.runtime import get_ner
from api.strategies.registry import builders, cleaners, clusterers

router = APIRouter(prefix="/api", tags=["eda"])


class EdaDocument(DomainModel):
    id: Id = Field(default_factory=new_id)
    text: str = Field(min_length=1)


class EdaRequest(DomainModel):
    corpus_id: Id = Field(default_factory=new_id)
    documents: list[EdaDocument]


@router.post("/eda", response_model=EdaReport)
def analyze_corpus(
    request: EdaRequest,
    ner: NerProtocol = Depends(get_ner),
) -> EdaReport:
    if not request.documents:
        raise HTTPException(status_code=400, detail="documents must be non-empty")

    service = EdaService(ner=ner)
    report = service.analyze(
        corpus_id=request.corpus_id,
        documents=[(d.id, d.text) for d in request.documents],
    )

    # Phase 1.7: validate the recommended strategy names against the
    # registry. If a recommendation is stale (e.g. a renamed plugin),
    # surface it instead of letting the wizard pre-fill garbage.
    rec = report.recommendation
    missing: list[str] = []
    if not builders.has(rec.builder):
        missing.append(f"builder:{rec.builder}")
    for name in rec.cleaner_chain:
        if not cleaners.has(name):
            missing.append(f"cleaner:{name}")
    if rec.clusterer and not clusterers.has(rec.clusterer):
        missing.append(f"clusterer:{rec.clusterer}")
    if missing:
        # Don't error — degrade gracefully so the wizard still loads.
        # Append the heads-up to the rationale; UI can flag in red.
        warning = "ВНИМАНИЕ: следующие стратегии не зарегистрированы и будут заменены: " + ", ".join(
            missing
        )
        report = report.model_copy(
            update={
                "recommendation": rec.model_copy(
                    update={"rationale": rec.rationale + "\n" + warning}
                )
            }
        )
    return report
