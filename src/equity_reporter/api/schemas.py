from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "equity-research-reporter-api"


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=120)
    riskProfile: Literal["defensive", "balanced", "aggressive"] = "balanced"

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty.")
        return cleaned


class RiskProfilesResponse(BaseModel):
    riskProfiles: list[str]
    defaultRiskProfile: str


class ApiErrorResponse(BaseModel):
    detail: str
    requestId: str | None = None
