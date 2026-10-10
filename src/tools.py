from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.contracts import EvidenceItem
from src.data_access import (
    load_budgets,
    load_employees,
    load_purchase_history,
    load_software_catalog,
    load_vendors,
)
from src.vendor_client import get_vendor_risk

# Policy snapshot reference date as specified in procurement_policy.md
REFERENCE_DATE = datetime.date(2026, 9, 30)


# ==============================================================================
# Tool 1: Budget Verification Tool (Deterministic)
# ==============================================================================
def budget_tool(department: str, annual_cost_usd: float | int | None) -> dict[str, Any]:
    """Check annual cost against the requesting department's available software budget."""
    budgets_df = load_budgets()
    match = budgets_df[budgets_df["department"].str.lower() == department.strip().lower()]
    
    if match.empty:
        return {
            "department": department,
            "found": False,
            "available_usd": 0,
            "is_sufficient": False,
            "evidence": EvidenceItem(
                source="budget_tool",
                finding=f"Department '{department}' not found in budget registry.",
                reference="department_budgets.csv",
            ),
        }
    
    row = match.iloc[0]
    total_budget = int(row["annual_software_budget_usd"])
    committed = int(row["committed_usd"])
    available = int(row["available_usd"])
    
    if annual_cost_usd is None:
        return {
            "department": department,
            "found": True,
            "annual_budget_usd": total_budget,
            "committed_usd": committed,
            "available_usd": available,
            "is_sufficient": None,
            "evidence": EvidenceItem(
                source="budget_tool",
                finding=f"Department '{department}' has ${available:,} available budget, but request cost is unspecified.",
                reference=f"department_budgets.csv: {department}",
            ),
        }
    
    cost = float(annual_cost_usd)
    is_sufficient = cost <= available
    diff = abs(available - cost)
    
    if is_sufficient:
        finding = (
            f"Department '{department}' has ${available:,} available software budget "
            f"(Total: ${total_budget:,}, Committed: ${committed:,}). Requested cost ${cost:,.0f} is within budget."
        )
    else:
        finding = (
            f"Department '{department}' has ${available:,} available budget. "
            f"Requested cost ${cost:,.0f} exceeds available budget by ${diff:,.0f}."
        )
        
    return {
        "department": department,
        "found": True,
        "annual_budget_usd": total_budget,
        "committed_usd": committed,
        "available_usd": available,
        "requested_cost_usd": cost,
        "is_sufficient": is_sufficient,
        "budget_shortfall_usd": diff if not is_sufficient else 0,
        "evidence": EvidenceItem(
            source="budget_tool",
            finding=finding,
            reference=f"department_budgets.csv: {department}",
        ),
    }


# ==============================================================================
# Tool 2: Catalog & Overlap Tool (Deterministic / Retrieval)
# ==============================================================================
def catalog_overlap_tool(
    product_name: str | None,
    category: str | None,
    vendor_name: str | None,
) -> dict[str, Any]:
    """Check approved software catalog and purchase history for existing alternative tools or overlap."""
    catalog_df = load_software_catalog()
    history_df = load_purchase_history()
    
    overlaps: list[dict[str, Any]] = []
    
    # Check exact/partial product or vendor matches
    for _, row in catalog_df.iterrows():
        cat_match = category and str(row["category"]).strip().lower() == category.strip().lower()
        vend_match = vendor_name and str(row["vendor_name"]).strip().lower() == vendor_name.strip().lower()
        name_match = product_name and (
            str(row["product_name"]).strip().lower() in product_name.strip().lower()
            or product_name.strip().lower() in str(row["product_name"]).strip().lower()
        )
        
        if cat_match or vend_match or name_match:
            overlaps.append({
                "software_id": row["software_id"],
                "product_name": row["product_name"],
                "category": row["category"],
                "vendor_name": row["vendor_name"],
                "status": row["status"],
                "licensed_seats": int(row["licensed_seats"]),
                "scope": row["scope"],
                "annual_cost_usd": int(row["annual_cost_usd"]),
                "match_reason": "category_match" if cat_match else ("vendor_match" if vend_match else "name_match"),
            })
            
    overlap_found = len(overlaps) > 0
    if overlap_found:
        names = [f"{o['product_name']} ({o['vendor_name']}, scope: {o['scope']})" for o in overlaps]
        finding = (
            f"Existing catalog overlap identified: {'; '.join(names)}. "
            f"Review potential redundancy or seat expansion before new procurement."
        )
    else:
        finding = f"No active overlap found in software catalog for category '{category}'."
        
    return {
        "overlap_found": overlap_found,
        "overlapping_tools": overlaps,
        "evidence": EvidenceItem(
            source="catalog_tool",
            finding=finding,
            reference="software_catalog.csv",
        ),
    }


# ==============================================================================
# Tool 3: Internal Vendor Registry Tool (Deterministic)
# ==============================================================================
def vendor_registry_tool(vendor_name: str) -> dict[str, Any]:
    """Lookup vendor in internal procurement registry (vendors.csv)."""
    vendors_df = load_vendors()
    match = vendors_df[vendors_df["vendor_name"].str.lower() == vendor_name.strip().lower()]
    
    if match.empty:
        return {
            "vendor_name": vendor_name,
            "found": False,
            "procurement_status": "Unknown",
            "security_status": "Unknown",
            "legal_terms_status": "Unknown",
            "is_expired": False,
            "evidence": EvidenceItem(
                source="vendor_registry_tool",
                finding=f"Vendor '{vendor_name}' is not in the internal vendor registry (new vendor).",
                reference="vendors.csv",
            ),
        }
        
    row = match.iloc[0]
    proc_status = str(row["procurement_status"])
    sec_status = str(row["security_status"])
    legal_status = str(row["legal_terms_status"])
    review_date_str = str(row["security_review_date"]) if pd.notna(row["security_review_date"]) else ""
    notes = str(row["notes"]) if pd.notna(row["notes"]) else ""
    
    is_expired = False
    days_old = None
    if review_date_str:
        review_date = datetime.date.fromisoformat(review_date_str)
        days_old = (REFERENCE_DATE - review_date).days
        if days_old > 365:
            is_expired = True
    elif proc_status.lower() == "approved":
        # Missing date on approved vendor
        is_expired = True

    finding = (
        f"Internal registry: procurement='{proc_status}', security='{sec_status}', legal='{legal_status}'"
    )
    if review_date_str:
        finding += f", review_date={review_date_str} ({days_old} days prior to policy reference date)"
    if is_expired:
        finding += " [SECURITY REVIEW EXPIRED > 365 days]"
    if notes:
        finding += f". Notes: {notes}"

    return {
        "vendor_name": vendor_name,
        "found": True,
        "procurement_status": proc_status,
        "security_status": sec_status,
        "security_review_date": review_date_str,
        "days_old": days_old,
        "is_expired": is_expired,
        "legal_terms_status": legal_status,
        "notes": notes,
        "evidence": EvidenceItem(
            source="vendor_registry_tool",
            finding=finding,
            reference=f"vendors.csv: {vendor_name}",
        ),
    }


# ==============================================================================
# Tool 4: External Vendor Risk API Tool (Service Integration + Fault Tolerance)
# ==============================================================================
def vendor_risk_api_tool(vendor_name: str) -> dict[str, Any]:
    """Query external vendor-risk API (/vendor-risk/{vendor_name}) with graceful error handling."""
    try:
        data = get_vendor_risk(vendor_name)
        risk_level = data.get("risk_level", "unknown")
        sec_status = data.get("security_review_status", "unknown")
        last_date = data.get("last_review_date")
        personal_data = bool(data.get("processes_personal_data", False))
        outside_region = bool(data.get("stores_data_outside_region", False))
        notes = data.get("notes", "")

        is_expired = False
        if last_date:
            try:
                dt = datetime.date.fromisoformat(last_date)
                if (REFERENCE_DATE - dt).days > 365:
                    is_expired = True
            except Exception:
                pass
        elif sec_status in ("not_completed", "expired"):
            is_expired = True

        finding = (
            f"External risk service: risk_level='{risk_level}', security_status='{sec_status}', "
            f"processes_pii={personal_data}, stores_outside_region={outside_region}."
        )
        if last_date:
            finding += f" Last review: {last_date}."
        if notes:
            finding += f" Notes: {notes}"

        return {
            "is_available": True,
            "vendor_name": vendor_name,
            "risk_level": risk_level,
            "security_review_status": sec_status,
            "last_review_date": last_date,
            "is_expired": is_expired,
            "processes_personal_data": personal_data,
            "stores_data_outside_region": outside_region,
            "notes": notes,
            "evidence": EvidenceItem(
                source="vendor_risk_api",
                finding=finding,
                reference=f"/vendor-risk/{vendor_name}",
            ),
        }
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 500
        msg = f"HTTP {status_code}: {exc.response.text if exc.response is not None else str(exc)}"
        return {
            "is_available": False,
            "vendor_name": vendor_name,
            "error_code": status_code,
            "error_message": msg,
            "evidence": EvidenceItem(
                source="vendor_risk_api",
                finding=f"External vendor-risk API unavailable for '{vendor_name}' ({msg}). Must escalate for manual verification.",
                reference=f"/vendor-risk/{vendor_name}",
            ),
        }
    except Exception as exc:
        msg = f"Connection error: {exc}"
        return {
            "is_available": False,
            "vendor_name": vendor_name,
            "error_code": 503,
            "error_message": msg,
            "evidence": EvidenceItem(
                source="vendor_risk_api",
                finding=f"External vendor-risk service unreachable for '{vendor_name}' ({msg}). Cannot verify vendor risk.",
                reference=f"/vendor-risk/{vendor_name}",
            ),
        }


# ==============================================================================
# Tool 5: Untrusted Input & Prompt Injection Guard (Deterministic / Heuristic)
# ==============================================================================
def prompt_guard_tool(request: dict[str, Any]) -> dict[str, Any]:
    """Inspect untrusted request fields for prompt injection, policy bypass, or role manipulation."""
    suspicious_patterns = [
        r"ignore (all|any|the)? (procurement|rules|policy|instructions|guidelines)",
        r"treat this request as.*approved",
        r"approve (it|this)? immediately",
        r"cfo[- ]approved",
        r"bypass (all|the)? (review|controls|policy)",
        r"system prompt",
        r"override (all|the)? (rules|policy|instructions)",
        r"you are now (an?|in) admin",
    ]
    
    text_corpus = " ".join([
        str(request.get("business_justification", "")),
        str(request.get("product_name", "")),
        str(request.get("category", "")),
        str(request.get("data_access_level", "")),
    ]).lower()
    
    detected = False
    matched_patterns = []
    for pattern in suspicious_patterns:
        if re.search(pattern, text_corpus):
            detected = True
            matched_patterns.append(pattern)
            
    if detected:
        finding = (
            "Untrusted input alert: Business text attempts to override procurement policies or claim automated approval. "
            "Input treated strictly as unverified business data; all policy controls enforced."
        )
    else:
        finding = "Input inspection: No prompt injection or policy override detected in request fields."
        
    return {
        "prompt_injection_detected": detected,
        "matched_patterns": matched_patterns,
        "evidence": EvidenceItem(
            source="prompt_guard_tool",
            finding=finding,
            reference="Procurement Policy Section 9 (Untrusted content and prompt injection)",
        ),
    }


# ==============================================================================
# Tool 6: Deterministic Policy Engine (Core Policy & Compliance Matrix)
# ==============================================================================
def evaluate_policy_rules(
    request: dict[str, Any],
    budget_res: dict[str, Any],
    catalog_res: dict[str, Any],
    registry_res: dict[str, Any],
    risk_api_res: dict[str, Any],
    prompt_res: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate full procurement policy deterministically according to procurement_policy.md."""
    missing_info: list[str] = []
    risk_flags: list[str] = []
    required_approvals: list[str] = []
    
    # --------------------------------------------------------------------------
    # 1. Required request information check (Section 1)
    # --------------------------------------------------------------------------
    cost = request.get("annual_cost_usd")
    user_count = request.get("user_count")
    data_access = str(request.get("data_access_level", "")).strip().lower()
    justification = str(request.get("business_justification", "")).strip()
    
    if cost is None:
        missing_info.append("annual cost or estimated annual pricing")
    if user_count is None:
        missing_info.append("number of users or license seat count")
    if not data_access or data_access == "unknown":
        missing_info.append("intended data access level")
    if not justification:
        missing_info.append("business purpose / justification")
        
    if missing_info:
        risk_flags.append("missing_information")
        
    # --------------------------------------------------------------------------
    # 2. Prompt injection check (Section 9)
    # --------------------------------------------------------------------------
    if prompt_res.get("prompt_injection_detected"):
        risk_flags.append("prompt_injection_detected")
        
    # --------------------------------------------------------------------------
    # 3. Financial approval thresholds (Section 4)
    # --------------------------------------------------------------------------
    if cost is not None:
        annual_val = float(cost)
        if annual_val <= 1000.0:
            required_approvals.append("Manager")
        elif annual_val <= 10000.0:
            required_approvals.extend(["Department Head", "Procurement"])
        elif annual_val <= 25000.0:
            required_approvals.extend(["Department Head", "Finance", "Procurement"])
        else:
            required_approvals.extend(["Department Head", "Finance", "CFO", "Procurement"])
            
    # --------------------------------------------------------------------------
    # 4. Budget check (Section 2)
    # --------------------------------------------------------------------------
    if budget_res.get("found"):
        if budget_res.get("is_sufficient") is False:
            risk_flags.append("budget_insufficient")
            if "Finance" not in required_approvals:
                required_approvals.append("Finance")
                
    # --------------------------------------------------------------------------
    # 5. Existing software overlap (Section 3)
    # --------------------------------------------------------------------------
    if catalog_res.get("overlap_found"):
        risk_flags.append("existing_tool_overlap")
        
    # --------------------------------------------------------------------------
    # 6. Vendor-risk API availability (Section 10)
    # --------------------------------------------------------------------------
    api_available = risk_api_res.get("is_available", True)
    if not api_available:
        risk_flags.append("vendor_risk_unavailable")
        if "Security" not in required_approvals:
            required_approvals.append("Security")
            
    # --------------------------------------------------------------------------
    # 7. Vendor Review Expiration & Registry Conflicts (Section 5)
    # --------------------------------------------------------------------------
    registry_expired = registry_res.get("is_expired", False)
    api_expired = risk_api_res.get("is_expired", False) if api_available else False
    if registry_expired or api_expired:
        risk_flags.append("vendor_review_expired")
        
    # Check conflicting evidence between registry and API
    if registry_res.get("found") and api_available:
        reg_sec = registry_res.get("security_status", "").lower()
        api_sec = risk_api_res.get("security_review_status", "").lower()
        if reg_sec and api_sec and reg_sec != api_sec and not (reg_sec == "approved" and api_sec == "approved"):
            risk_flags.append("conflicting_vendor_evidence")
            
    # --------------------------------------------------------------------------
    # 8. Security Review Requirements (Section 5 & 8)
    # --------------------------------------------------------------------------
    sensitive_data_classes = {
        "source_code",
        "production_telemetry",
        "production_cloud",
        "confidential_documents",
        "employee_pii",
        "customer_pii",
        "credentials",
        "secrets",
    }
    integrations = [str(x).lower() for x in request.get("requested_integrations", [])]
    has_prod_integration = any("prod" in i or "cloud" in i or "git" in i or "repo" in i for i in integrations)
    
    sec_status_reg = registry_res.get("security_status", "").lower()
    sec_status_api = risk_api_res.get("security_review_status", "").lower() if api_available else ""
    
    vendor_security_incomplete = (
        not registry_res.get("found")
        or sec_status_reg in ("pending", "not_completed", "unknown", "")
        or (api_available and sec_status_api in ("pending", "not_completed", "unknown", "expired"))
        or registry_expired
        or not api_available
    )
    
    if (
        data_access in sensitive_data_classes
        or has_prod_integration
        or vendor_security_incomplete
    ):
        if "security_review_required" not in risk_flags:
            risk_flags.append("security_review_required")
        if "Security" not in required_approvals:
            required_approvals.append("Security")

    # --------------------------------------------------------------------------
    # 9. Privacy Review Requirements (Section 6)
    # --------------------------------------------------------------------------
    processes_pii = (
        data_access in {"employee_pii", "customer_pii"}
        or (api_available and risk_api_res.get("processes_personal_data", False))
    )
    cross_region = api_available and risk_api_res.get("stores_data_outside_region", False)
    
    if (data_access in {"employee_pii", "customer_pii"}) or (processes_pii and (data_access != "internal_marketing" and data_access != "internal_documents" and data_access != "none")) or cross_region:
        if "privacy_review_required" not in risk_flags:
            risk_flags.append("privacy_review_required")
        if "Privacy" not in required_approvals:
            required_approvals.append("Privacy")
            
    # --------------------------------------------------------------------------
    # 10. Legal Review Requirements (Section 7)
    # --------------------------------------------------------------------------
    is_new_vendor = (not registry_res.get("found")) or (registry_res.get("procurement_status", "").lower() == "new")
    legal_terms = registry_res.get("legal_terms_status", "").lower()
    
    annual_spend = float(cost) if cost is not None else 0.0
    
    if (
        (is_new_vendor and annual_spend >= 10000.0)
        or (legal_terms in ("draft", "unknown", "pending", ""))
        or cross_region
    ):
        if "legal_review_required" not in risk_flags:
            risk_flags.append("legal_review_required")
        if "Legal" not in required_approvals:
            required_approvals.append("Legal")
            
    # Ensure consistent ordering
    approval_order = ["Manager", "Department Head", "Procurement", "Finance", "CFO", "Security", "Privacy", "Legal"]
    sorted_approvals = [a for a in approval_order if a in required_approvals]
    
    return {
        "missing_information": missing_info,
        "risk_flags": risk_flags,
        "required_approvals": sorted_approvals,
    }
