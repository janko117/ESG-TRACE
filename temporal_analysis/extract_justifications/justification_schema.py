"""Response schema for the justification search (stage 3)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class JustificationResult(BaseModel):
    """Result of one justification search in one report."""

    found: bool = Field(
        description="True if the report states a justification for the change.")
    justification: Optional[str] = Field(
        default=None,
        description="The verbatim quote from the report, or null if none.")
    evidence_page: Optional[int] = Field(
        default=None,
        description="1-based page number where the quote appears, or null.")