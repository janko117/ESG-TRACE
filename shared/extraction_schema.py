"""Response schema for the target extraction.

Only the structure and the allowed values are defined here. What each field
means is explained in the prompt.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class FieldEvidence(BaseModel):
    field: Optional[str] = None
    page: Optional[int] = None
    source_type: Optional[Literal["text", "table", "chart"]] = None
    text: Optional[str] = None


class TargetInstance(BaseModel):
    metric: Optional[str] = None
    is_intensity_based: Optional[int] = None
    intensity_denominator: Optional[str] = None
    target_direction: Optional[Literal["reduction", "increase"]] = None
    relative_target_value: Optional[float] = None
    absolute_target_value: Optional[float] = None
    absolute_target_value_unit: Optional[str] = None
    target_year: Optional[int] = None
    base_year: Optional[int] = None
    base_value: Optional[float] = None
    base_value_unit: Optional[str] = None
    annual_change_rate: Optional[float] = None
    scope_of_application: Optional[str] = None
    scope_1: Optional[int] = None
    scope_2: Optional[int] = None
    scope_3: Optional[int] = None
    emission_character: Optional[Literal["gross", "net"]] = None
    current_value: Optional[float] = None
    current_value_unit: Optional[str] = None
    current_relative_change: Optional[float] = None
    achievement_rate: Optional[float] = None
    achievement_status: Optional[Literal["ongoing", "failed", "achieved"]] = None
    evidence: list[FieldEvidence] = Field(default_factory=list)

    # Sometimes the model doesn't stop after the year and keeps adding digits
    # (e.g. 20300000). In that case only the first four digits are kept.
    @field_validator("target_year", "base_year", mode="before")
    @classmethod
    def _repair_digit_run_year(cls, v, info):
        if v is None:
            return v
        s = str(v)
        if s.lstrip("-").isdigit() and len(s.lstrip("-")) > 4:
            prefix = s[:4]
            if prefix.isdigit() and 1900 <= int(prefix) <= 2100:
                print(f"WARNING: repaired degenerate {info.field_name} "
                      f"'{s[:60]}{'...' if len(s) > 60 else ''}' -> '{prefix}'")
                return int(prefix)
        return v


class ReportExtraction(BaseModel):
    targets: list[TargetInstance] = Field(default_factory=list)
