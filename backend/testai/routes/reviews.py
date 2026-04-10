"""Reviews API: /api/reviews/*, /api/hitl/*, /api/labels/*."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from testai import state

router = APIRouter()


class ReviewApproveRequest(BaseModel):
    reviewer: str = ""
    note: str = ""


class ReviewCorrectRequest(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    feature: Optional[str] = None
    tags: Optional[List[str]] = None
    reviewer: str = ""
    note: str = ""


class BatchApproveRequest(BaseModel):
    journey_ids: List[str]
    reviewer: str = ""


class HITLConfigUpdate(BaseModel):
    auto_approve_threshold: Optional[float] = None


@router.get("/api/reviews")
async def list_reviews(
    status: Optional[str] = None,
    domain: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
):
    return state.db.get_review_queue(
        status=status,
        domain=domain,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        limit=limit,
        offset=offset,
    )


@router.get("/api/reviews/stats")
async def review_stats():
    return state.db.get_review_stats()


@router.patch("/api/reviews/{journey_id}/approve")
async def approve_journey(journey_id: str, req: ReviewApproveRequest):
    ok = state.review_manager.approve(journey_id, req.reviewer, req.note)
    if not ok:
        raise HTTPException(status_code=404, detail="Journey not found")
    return {"ok": True, "status": "approved"}


@router.patch("/api/reviews/{journey_id}/reject")
async def reject_journey(journey_id: str, req: ReviewApproveRequest):
    ok = state.review_manager.reject(journey_id, req.reviewer, req.note)
    if not ok:
        raise HTTPException(status_code=404, detail="Journey not found")
    return {"ok": True, "status": "rejected"}


@router.patch("/api/reviews/{journey_id}/correct")
async def correct_journey(journey_id: str, req: ReviewCorrectRequest):
    corrections = {}
    if req.name is not None:
        corrections["name"] = req.name
    if req.domain is not None:
        corrections["domain"] = req.domain
    if req.feature is not None:
        corrections["feature"] = req.feature
    if req.tags is not None:
        corrections["tags"] = req.tags
    if not corrections:
        raise HTTPException(status_code=400, detail="No corrections provided")
    result = state.review_manager.correct_and_approve(
        journey_id, corrections, req.reviewer, req.note
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    return {"ok": True, "journey": result}


@router.post("/api/reviews/batch-approve")
async def batch_approve(req: BatchApproveRequest):
    if not req.journey_ids:
        raise HTTPException(status_code=400, detail="No journey IDs provided")
    count = state.review_manager.batch_approve(req.journey_ids, req.reviewer)
    return {"ok": True, "approved_count": count}


@router.get("/api/reviews/{journey_id}/history")
async def review_history(journey_id: str, limit: int = 50):
    return state.db.get_review_actions(journey_id, limit=limit)


@router.get("/api/hitl/config")
async def get_hitl_config():
    return state.db.get_hitl_config()


@router.patch("/api/hitl/config")
async def update_hitl_config(req: HITLConfigUpdate):
    if req.auto_approve_threshold is not None:
        if not (0.0 <= req.auto_approve_threshold <= 1.0):
            raise HTTPException(status_code=400, detail="Threshold must be between 0.0 and 1.0")
        state.db.set_hitl_config("auto_approve_threshold", str(req.auto_approve_threshold))
        state.review_manager.reload_threshold()
    return state.db.get_hitl_config()


@router.get("/api/labels/corrections")
async def get_label_corrections():
    return state.db.get_label_corrections()


@router.get("/api/labels/vocabulary")
async def get_label_vocabulary():
    return state.db.get_domain_vocabulary()


@router.get("/api/labels/patterns")
async def get_label_patterns(limit: int = 20):
    return state.db.get_correction_patterns(limit=limit)


@router.get("/api/labels/accuracy")
async def get_label_accuracy(days: int = 30):
    return state.label_learner.get_correction_analytics()
