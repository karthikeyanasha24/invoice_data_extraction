"""Pydantic schemas for AI Ops API (Phase 9)."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class AiOpsHealthResponse(BaseModel):
    enabled: bool
    env: str
    message: str


class AiAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(200, ge=1, le=500)
    authorize_cross_workspace: bool = False
    workspace_ids: List[str] = Field(default_factory=list)


class AiCompareRequest(BaseModel):
    workspace_ids: List[str] = Field(..., min_length=1)
    authorize_cross_workspace: bool = True
    limit: int = Field(100, ge=1, le=500)
