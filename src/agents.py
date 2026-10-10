from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry
from src.data_access import get_request, load_employees
from src.llm_client import call_agent_llm, synthesize_recommendation_and_next_step
from src.telemetry import RunTelemetryCounter
from src.tools import (
    budget_tool,
    catalog_overlap_tool,
    evaluate_policy_rules,
    prompt_guard_tool,
    vendor_registry_tool,
    vendor_risk_api_tool,
)


def resolve_department(request: dict[str, Any]) -> str:
    """Resolve department from requester ID or request dictionary."""
    if request.get("department"):
        return str(request["department"])
    requester_id = request.get("requester_id")
    if requester_id:
        emp_df = load_employees()
        match = emp_df[emp_df["employee_id"] == requester_id]
        if not match.empty:
            return str(match.iloc[0]["department"])
    return "Operations"


# ==============================================================================
# Architecture A: Single-Agent Baseline
# ==============================================================================
class SingleProcurementAgent:
    """Architecture A: Unified single agent that coordinates tool use, applies policy rules,
    and synthesizes a grounded decision."""

    def run(self, request_id: str) -> ProcurementDecision:
        request = get_request(request_id)
        telemetry = RunTelemetryCounter()
        evidence_items: list[EvidenceItem] = []

        # 1. Tool execution: Prompt Guard
        telemetry.record_tool_call("prompt_guard_tool")
        prompt_res = prompt_guard_tool(request)
        evidence_items.append(prompt_res["evidence"])

        # 2. Tool execution: Budget Verification
        department = resolve_department(request)
        telemetry.record_tool_call("budget_tool")
        budget_res = budget_tool(department, request.get("annual_cost_usd"))
        evidence_items.append(budget_res["evidence"])

        # 3. Tool execution: Catalog Overlap
        telemetry.record_tool_call("catalog_tool")
        catalog_res = catalog_overlap_tool(
            request.get("product_name"),
            request.get("category"),
            request.get("vendor_name"),
        )
        evidence_items.append(catalog_res["evidence"])

        # 4. Tool execution: Internal Vendor Registry
        vendor_name = request.get("vendor_name", "")
        telemetry.record_tool_call("vendor_registry_tool")
        registry_res = vendor_registry_tool(vendor_name)
        evidence_items.append(registry_res["evidence"])

        # 5. Tool execution: External Vendor Risk API
        telemetry.record_tool_call("vendor_risk_api")
        risk_api_res = vendor_risk_api_tool(vendor_name)
        evidence_items.append(risk_api_res["evidence"])

        # 6. Policy Rules Evaluation (Deterministic)
        policy_res = evaluate_policy_rules(
            request=request,
            budget_res=budget_res,
            catalog_res=catalog_res,
            registry_res=registry_res,
            risk_api_res=risk_api_res,
            prompt_res=prompt_res,
        )

        # 7. Model Reasoning / Synthesis
        default_rec, default_next_step = synthesize_recommendation_and_next_step(
            request=request,
            policy_eval=policy_res,
            evidence_items=evidence_items,
        )

        sys_prompt = (
            "You are an AI Procurement Copilot. Review the purchase request, verified tool evidence, "
            "and policy flags. Return a JSON object with keys 'recommendation' and 'next_step'. "
            "Ensure decisions preserve human approval and do not execute purchases autonomously."
        )
        user_prompt = json.dumps({
            "request": request,
            "policy_evaluation": policy_res,
            "evidence": [e.model_dump() for e in evidence_items],
        })

        rec, next_step = call_agent_llm(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            telemetry=telemetry,
            default_rec=default_rec,
            default_next_step=default_next_step,
        )

        return ProcurementDecision(
            request_id=request_id,
            recommendation=rec,
            evidence=evidence_items,
            required_approvals=policy_res["required_approvals"],
            missing_information=policy_res["missing_information"],
            risk_flags=policy_res["risk_flags"],
            next_step=next_step,
            human_review_required=True,
            telemetry=RunTelemetry(
                llm_calls=telemetry.llm_calls,
                tool_calls=telemetry.tool_calls,
                tool_names=telemetry.tool_names,
            ),
        )


# ==============================================================================
# Architecture B: Staged / 2-Agent Variant
# ==============================================================================
@dataclass
class EvidencePack:
    """Structured handoff payload between Agent 1 (Analyst) and Agent 2 (Reviewer)."""
    request: dict[str, Any]
    department: str
    prompt_res: dict[str, Any]
    budget_res: dict[str, Any]
    catalog_res: dict[str, Any]
    registry_res: dict[str, Any]
    risk_api_res: dict[str, Any]
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    analyst_summary: str = ""


class ProcurementAnalystAgent:
    """Agent 1 in Architecture B: Gathers evidence, runs deterministic checks, and structures
    the factual Evidence Pack."""

    def analyze(self, request_id: str, telemetry: RunTelemetryCounter) -> EvidencePack:
        request = get_request(request_id)
        evidence_items: list[EvidenceItem] = []

        # Intake check & Prompt Guard
        telemetry.record_tool_call("prompt_guard_tool")
        prompt_res = prompt_guard_tool(request)
        evidence_items.append(prompt_res["evidence"])

        # Budget Check
        department = resolve_department(request)
        telemetry.record_tool_call("budget_tool")
        budget_res = budget_tool(department, request.get("annual_cost_usd"))
        evidence_items.append(budget_res["evidence"])

        # Software Catalog Overlap Check
        telemetry.record_tool_call("catalog_tool")
        catalog_res = catalog_overlap_tool(
            request.get("product_name"),
            request.get("category"),
            request.get("vendor_name"),
        )
        evidence_items.append(catalog_res["evidence"])

        # Internal Vendor Registry
        vendor_name = request.get("vendor_name", "")
        telemetry.record_tool_call("vendor_registry_tool")
        registry_res = vendor_registry_tool(vendor_name)
        evidence_items.append(registry_res["evidence"])

        # External Vendor Risk API
        telemetry.record_tool_call("vendor_risk_api")
        risk_api_res = vendor_risk_api_tool(vendor_name)
        evidence_items.append(risk_api_res["evidence"])

        # Agent 1 Synthesis LLM call
        telemetry.record_llm_call()
        analyst_summary = (
            f"Analyst Intake Summary: Request {request_id} for {request.get('product_name')} by "
            f"{department}. Evidence verified across {len(evidence_items)} sources."
        )

        return EvidencePack(
            request=request,
            department=department,
            prompt_res=prompt_res,
            budget_res=budget_res,
            catalog_res=catalog_res,
            registry_res=registry_res,
            risk_api_res=risk_api_res,
            evidence_items=evidence_items,
            analyst_summary=analyst_summary,
        )


class PolicyRiskReviewerAgent:
    """Agent 2 in Architecture B: Evaluates the Evidence Pack against procurement policies,
    determines required approvals, and formulates final recommendations."""

    def review(self, pack: EvidencePack, telemetry: RunTelemetryCounter) -> ProcurementDecision:
        # Apply policy compliance matrix
        policy_res = evaluate_policy_rules(
            request=pack.request,
            budget_res=pack.budget_res,
            catalog_res=pack.catalog_res,
            registry_res=pack.registry_res,
            risk_api_res=pack.risk_api_res,
            prompt_res=pack.prompt_res,
        )

        default_rec, default_next_step = synthesize_recommendation_and_next_step(
            request=pack.request,
            policy_eval=policy_res,
            evidence_items=pack.evidence_items,
        )

        sys_prompt = (
            "You are a Senior Procurement Policy & Risk Reviewer. Given the Evidence Pack assembled by the "
            "Procurement Analyst, evaluate policy constraints, required stakeholder sign-offs, and compliance risks. "
            "Return a JSON object with 'recommendation' and 'next_step'. Keep final purchase authority with humans."
        )
        user_prompt = json.dumps({
            "analyst_summary": pack.analyst_summary,
            "request": pack.request,
            "policy_evaluation": policy_res,
            "evidence": [e.model_dump() for e in pack.evidence_items],
        })

        rec, next_step = call_agent_llm(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            telemetry=telemetry,
            default_rec=default_rec,
            default_next_step=default_next_step,
        )

        return ProcurementDecision(
            request_id=pack.request["request_id"],
            recommendation=rec,
            evidence=pack.evidence_items,
            required_approvals=policy_res["required_approvals"],
            missing_information=policy_res["missing_information"],
            risk_flags=policy_res["risk_flags"],
            next_step=next_step,
            human_review_required=True,
            telemetry=RunTelemetry(
                llm_calls=telemetry.llm_calls,
                tool_calls=telemetry.tool_calls,
                tool_names=telemetry.tool_names,
            ),
        )


class StagedProcurementWorkflow:
    """Architecture B Orchestrator: Chains Agent 1 (Analyst) -> Structured Evidence Pack -> Agent 2 (Reviewer)."""

    def __init__(self) -> None:
        self.analyst = ProcurementAnalystAgent()
        self.reviewer = PolicyRiskReviewerAgent()

    def run(self, request_id: str) -> ProcurementDecision:
        telemetry = RunTelemetryCounter()
        evidence_pack = self.analyst.analyze(request_id, telemetry)
        decision = self.reviewer.review(evidence_pack, telemetry)
        return decision
