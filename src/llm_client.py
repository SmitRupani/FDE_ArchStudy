from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry
from src.telemetry import RunTelemetryCounter


def is_llm_configured() -> bool:
    """Return True if an OpenRouter or OpenAI API key is configured."""
    return bool(
        os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )


def get_llm_client():
    """Build OpenAI/OpenRouter client if configured."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        from openai import OpenAI
        return OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
        )
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        from openai import OpenAI
        return OpenAI(api_key=openai_key)
    return None


def get_model_name() -> str:
    if os.getenv("OPENROUTER_API_KEY"):
        return os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    if os.getenv("OPENAI_API_KEY"):
        return os.getenv("MODEL_NAME", "gpt-4o-mini")
    return "local-procurement-copilot"


# ==============================================================================
# Synthesis Helpers (used by Local Engine or fallback)
# ==============================================================================
def synthesize_recommendation_and_next_step(
    request: dict[str, Any],
    policy_eval: dict[str, Any],
    evidence_items: list[EvidenceItem],
) -> tuple[str, str]:
    """Generate high-quality grounded recommendation and next step."""
    risk_flags = policy_eval["risk_flags"]
    missing_info = policy_eval["missing_information"]
    approvals = policy_eval["required_approvals"]
    prod_name = request.get("product_name", "Requested software")
    vendor_name = request.get("vendor_name", "Vendor")

    if "prompt_injection_detected" in risk_flags and "missing_information" in risk_flags:
        rec = f"Reject automated approval and request clarification for missing details on {prod_name}."
        next_step = (
            f"Notify requester to provide {', '.join(missing_info)}, and flag prompt injection attempts to IT Security. "
            "Human review required before any processing."
        )
        return rec, next_step

    if "missing_information" in risk_flags:
        rec = f"Request clarification from requester before processing {prod_name}."
        next_step = (
            f"Request mandatory missing information ({', '.join(missing_info)}) from requester before submitting for review."
        )
        return rec, next_step

    if "vendor_risk_unavailable" in risk_flags:
        rec = f"Hold procurement pending manual vendor risk verification for {vendor_name}."
        next_step = (
            f"Escalate {vendor_name} to Security and Procurement for manual offline risk assessment due to API outage; "
            f"obtain approvals from {', '.join(approvals)}."
        )
        return rec, next_step

    if "budget_insufficient" in risk_flags and "security_review_required" in risk_flags:
        rec = f"Route for budget exception and mandatory security assessment for {prod_name}."
        next_step = (
            f"Submit budget exception request to Finance and initiate security & compliance review with {', '.join(approvals)}."
        )
        return rec, next_step

    if "budget_insufficient" in risk_flags:
        rec = f"Route for budget exception approval for {prod_name}."
        next_step = f"Submit budget exception package to Finance and {', '.join(approvals)} for human review."
        return rec, next_step

    if "existing_tool_overlap" in risk_flags and "security_review_required" in risk_flags:
        rec = f"Route for redundancy assessment and vendor onboarding review for {prod_name}."
        next_step = (
            f"Procurement to review overlap against approved catalog, and route to {', '.join(approvals)} for formal evaluation."
        )
        return rec, next_step

    if "existing_tool_overlap" in risk_flags:
        rec = f"Review potential catalog overlap before approving {prod_name}."
        next_step = (
            f"Review existing software alternatives with department head and route to {', '.join(approvals)} for sign-off."
        )
        return rec, next_step

    if "security_review_required" in risk_flags or "vendor_review_expired" in risk_flags:
        rec = f"Route for required security and compliance approvals for {prod_name}."
        next_step = (
            f"Send evidence package to {', '.join(approvals)} for verification prior to purchase authorization."
        )
        return rec, next_step

    # Standard low-risk case
    rec = f"Ready for standard business approval: {prod_name}."
    next_step = (
        f"Route evidence package to {', '.join(approvals)} for final sign-off and PO issuance."
    )
    return rec, next_step


# ==============================================================================
# Model Invocation (Real LLM or Local Reasoning Engine)
# ==============================================================================
def call_agent_llm(
    system_prompt: str,
    user_prompt: str,
    telemetry: RunTelemetryCounter,
    default_rec: str,
    default_next_step: str,
) -> tuple[str, str]:
    """Invoke LLM (via OpenRouter/OpenAI) or local engine with telemetry tracking."""
    client = get_llm_client()
    telemetry.record_llm_call()

    if client is None:
        # Local Reasoning Engine
        return default_rec, default_next_step

    try:
        model = get_model_name()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=350,
            timeout=15.0,
        )
        content = response.choices[0].message.content or "{}"
        clean_content = content.strip()
        if clean_content.startswith("```json"):
            clean_content = clean_content[7:]
        if clean_content.startswith("```"):
            clean_content = clean_content[3:]
        if clean_content.endswith("```"):
            clean_content = clean_content[:-3]
        clean_content = clean_content.strip()
        
        parsed = json.loads(clean_content)
        rec = parsed.get("recommendation", default_rec)
        next_step = parsed.get("next_step", default_next_step)
        return rec, next_step
    except Exception as exc:
        # Fall back cleanly without crashing
        return default_rec, default_next_step
