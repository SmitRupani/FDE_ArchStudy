from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source: str = Field(description="Tool/data source name")
    finding: str = Field(description="Concise factual finding")
    reference: str | None = Field(default=None, description="Optional record ID / policy section / endpoint")


class AuditRecord(BaseModel):
    audit_id: str = Field(description="Unique UUID for audit record")
    timestamp_utc: str = Field(description="ISO 8601 UTC timestamp")
    request_id: str
    request_hash: str = Field(description="SHA-256 cryptographic digest of raw request payload")
    policy_version: str = Field(default="2026.09", description="Procurement policy version")
    policy_reference_date: str = Field(default="2026-09-30", description="Policy snapshot baseline date")
    decision_hash: str = Field(description="SHA-256 digest of recommendation, approvals, and risk flags")
    integrity_signature: str = Field(description="Tamper-evident composite SHA-256 signature")
    compliance_frameworks: list[str] = Field(
        default_factory=lambda: ["SOX-404", "SOC2-CC6.8", "ISO27001-A.9.4"]
    )


class RunTelemetry(BaseModel):
    llm_calls: int | None = None
    tool_calls: int | None = None
    tool_names: list[str] = Field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    tool_latencies_ms: dict[str, float] = Field(default_factory=dict)


class ProcurementDecision(BaseModel):
    request_id: str
    recommendation: str = Field(description="Short recommendation label or sentence")
    evidence: list[EvidenceItem] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    next_step: str
    human_review_required: bool = True
    telemetry: RunTelemetry | None = None
    audit_trail: AuditRecord | None = None


Architecture = Literal["single", "staged"]

# Suggested approval names for consistency in evaluation:
# Manager, Department Head, Procurement, Finance, CFO, Security, Privacy, Legal
#
# Suggested risk-flag taxonomy (you may add others):
# existing_tool_overlap
# budget_insufficient
# security_review_required
# privacy_review_required
# legal_review_required
# vendor_review_expired
# conflicting_vendor_evidence
# vendor_risk_unavailable
# prompt_injection_detected
# missing_information
