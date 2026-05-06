from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.corpus import Corpus, Document
from api.domain.types import DomainModel, Id, new_id
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["corpora"])


class CreateCorpusRequest(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    language: str = "ru"


class CreateDocumentRequest(DomainModel):
    title: str = Field(min_length=1, max_length=1024)
    text: str = Field(min_length=1)
    """Plain text body. The repo records sha256 + char_length; raw text
    is held by callers for now (Phase 0.4 storage layout).
    """

    source_uri: str | None = None
    language: str = "ru"


# ---- corpora ----


@router.post("/corpora", response_model=Corpus, status_code=201)
async def create_corpus(
    body: CreateCorpusRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Corpus:
    corpus = Corpus(
        name=body.name,
        description=body.description,
        language=body.language,
    )
    return await repo.create_corpus(corpus)


@router.get("/corpora", response_model=list[Corpus])
async def list_corpora(
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[Corpus]:
    return await repo.list_corpora()


@router.get("/corpora/{corpus_id}", response_model=Corpus)
async def get_corpus(
    corpus_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Corpus:
    try:
        return await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---- documents ----


@router.post(
    "/corpora/{corpus_id}/documents",
    response_model=Document,
    status_code=201,
)
async def create_document(
    corpus_id: Id,
    body: CreateDocumentRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Document:
    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    import hashlib

    sha256 = hashlib.sha256(body.text.encode("utf-8")).hexdigest()
    doc = Document(
        id=new_id(),
        corpus_id=corpus_id,
        title=body.title,
        source_uri=body.source_uri,
        language=body.language,
        char_length=len(body.text),
        sha256=sha256,
        metadata={"raw_text": body.text},
    )
    return await repo.create_document(doc)


@router.get(
    "/corpora/{corpus_id}/documents",
    response_model=list[Document],
)
async def list_documents(
    corpus_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[Document]:
    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await repo.list_documents(corpus_id)
