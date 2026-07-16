import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from groq import Groq

from ..dependencies import get_connection
from ..schemas import CompanySignalResponse, DealWithArticleResponse, PaginatedResponse
from ...db import queries
from ...db.queries import Neo4jConnection
from ...processor.company_signal import CompanySignalScorer, empty_signal_snapshot

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/search/deals", response_model=PaginatedResponse[DealWithArticleResponse])
def search_deals_by_company_name(
    name: str = Query(..., min_length=1, description="Partial company name to search for"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    offset = (page - 1) * page_size
    total, items = queries.get_deals_by_company_name(conn, name, offset=offset, limit=page_size)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{company_id}/deals", response_model=PaginatedResponse[DealWithArticleResponse])
def get_company_deals(
    company_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    if not queries.get_company(conn, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    offset = (page - 1) * page_size
    total, items = queries.get_deals_by_company(conn, company_id, offset=offset, limit=page_size)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{company_id}/signals/latest", response_model=CompanySignalResponse)
def get_latest_company_signal(
    company_id: UUID,
    conn: Neo4jConnection = Depends(get_connection),
):
    if not queries.get_company(conn, company_id):
        raise HTTPException(status_code=404, detail="Company not found")

    signal = queries.get_latest_company_signal(conn, company_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Company signal not found")
    return signal


@router.post("/{company_id}/signals/generate", response_model=CompanySignalResponse)
def generate_company_signal(
    company_id: UUID,
    request: Request,
    horizon_days: int = Query(30, ge=1, le=90),
    conn: Neo4jConnection = Depends(get_connection),
):
    company, articles, deal_history = queries.get_company_signal_context(
        conn,
        company_id,
        horizon_days=horizon_days,
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = company["name"]
    if not articles:
        snapshot = empty_signal_snapshot(str(company_id), company_name, horizon_days)
        return queries.save_company_signal_snapshot(conn, snapshot)

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is required to generate company signals from news",
        )

    settings = getattr(request.app.state, "settings", {})
    groq_cfg = settings.get("groq", {})
    scorer = CompanySignalScorer(
        client=Groq(api_key=groq_api_key),
        model=groq_cfg.get("model", "llama-3.3-70b-versatile"),
        temperature=groq_cfg.get("temperature", 0.1),
    )
    try:
        snapshot = scorer.generate(
            company_id=str(company_id),
            company_name=company_name,
            articles=articles,
            deal_history=deal_history,
            horizon_days=horizon_days,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Company signal LLM call failed") from exc

    return queries.save_company_signal_snapshot(conn, snapshot)
