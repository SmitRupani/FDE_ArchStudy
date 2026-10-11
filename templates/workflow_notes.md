# Workflow & Architecture Specification

## 1. System Architecture Overview

```text
               +----------------------------------+
               |  Purchase Request (Untrusted)   |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               |   Stage 1: Intake & Evidence     |
               |       (Procurement Analyst)      |
               +-----------------+----------------+
                                 |
    +----------------------------+----------------------------+
    |               |                         |               |
    v               v                         v               v
+----------+ +--------------+         +---------------+ +-------------+
|  Budget  | |   Catalog    |         | Vendor Registry| | Vendor Risk |
|   Tool   | | Overlap Tool |         |     Tool      | |   API Tool  |
+----------+ +--------------+         +---------------+ +-------------+
    |               |                         |               |
    +----------------------------+----------------------------+
                                 |
                                 v
               +----------------------------------+
               |       Prompt Guard Defense       |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               |      Structured EvidencePack     |
               |       (Factual Handoff)          |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               | Stage 2: Policy & Risk Reviewer  |
               | (Thresholds, Compliance Matrix)  |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               |    ProcurementDecision Schema    |
               |   (Advisory Recommendation)      |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               | Human Approvers Gate (Mandatory) |
               | (Manager / Finance / Security)   |
               +----------------------------------+
```

---

## 2. Tool Inventory

Our system implements **5 core tools**, exceeding the requirement of at least 3 tools with at least 1 deterministic tool:

| Tool Name | Type | Purpose | Policy Source |
|---|---|---|---|
| `prompt_guard_tool` | Deterministic / Regex Heuristic | Inspects untrusted requester text for prompt injection, policy bypass attempts, or unauthorized claims of CFO approval. | Section 9 |
| `budget_tool` | Deterministic | Compares annual requested cost against department's available software budget (`available_usd`). | Section 2 |
| `catalog_overlap_tool` | Deterministic / Search | Checks `software_catalog.csv` and `purchase_history.csv` for same product, vendor, or category alternatives. | Section 3 |
| `vendor_registry_tool` | Deterministic | Checks internal `vendors.csv` for onboarding status, legal terms, and review recency (> 365 days from `2026-09-30`). | Section 5 & 7 |
| `vendor_risk_api_tool` | Service Integration | Queries mock external vendor-risk endpoint (`/vendor-risk/{vendor_name}`) with graceful error handling for 503 outages. | Section 5 & 10 |

---

## 3. Deterministic vs. Model-Driven Division of Labor

In strict alignment with the core design principle:

### Deterministic (Code-Enforced):
- **Budget verification**: Exact arithmetic (`cost <= available_usd`).
- **Approval thresholds**: Statutory spend tiers (Manager <= $1k, Dept Head + Procurement <= $10k, + Finance <= $25k, + CFO > $25k).
- **Security review triggers**: Sensitive data classes (`source_code`, `production_cloud`, `customer_pii`, `employee_pii`, `credentials`), vendor review expiration (> 365 days), and uncompleted vendor assessments.
- **Privacy review triggers**: Processing of employee/customer PII or cross-region storage.
- **Legal review triggers**: New vendor spend >= $10k or draft/unknown legal terms.
- **Missing information detection**: Explicit missing value checks on mandatory fields.
- **Human review lock**: `human_review_required = True` hardcoded across all execution paths.

### Model-Driven (LLM-Interpreted):
- **Semantic Request Understanding**: Contextualizing use-case nuances and justifying tool redundancy exceptions.
- **Natural Language Synthesis**: Formulating clear, executive-ready recommendations tailored to business context.
- **Actionable Next Steps**: Outlining concrete operational handoffs for human reviewers.

---

## 4. Agent Responsibilities & Handoff Format

### Architecture A (Single Agent):
- Single `SingleProcurementAgent` orchestrates tool execution, feeds findings into policy rules, and leverages LLM synthesis for final output.

### Architecture B (Staged 2-Agent):
- **Agent 1 (`ProcurementAnalystAgent`)**:
  - Gathers all tool evidence.
  - Defends against untrusted input.
  - Bundles findings into a typed `EvidencePack`:
    ```python
    @dataclass
    class EvidencePack:
        request: dict[str, Any]
        department: str
        prompt_res: dict[str, Any]
        budget_res: dict[str, Any]
        catalog_res: dict[str, Any]
        registry_res: dict[str, Any]
        risk_api_res: dict[str, Any]
        evidence_items: list[EvidenceItem]
        analyst_summary: str
    ```
- **Agent 2 (`PolicyRiskReviewerAgent`)**:
  - Ingests `EvidencePack`.
  - Evaluates compliance matrix and maps required approval stakeholders.
  - Emits final `ProcurementDecision`.

---

## 5. Stop & Escalation Conditions

1. **Prompt Injection Detected**:
   - Flag `prompt_injection_detected`.
   - Freeze automated progress and require human inspection. Never grant autonomous approval.
2. **Missing Material Fields**:
   - Flag `missing_information`.
   - Recommend clarification request back to the submitter before approvals can begin.
3. **Budget Insufficient**:
   - Flag `budget_insufficient`.
   - Escalate to Finance for formal budget exception approval.
4. **Vendor Risk Service Unavailable**:
   - Flag `vendor_risk_unavailable`.
   - Trigger offline security assessment; do not infer favorable risk status.
5. **Vendor Review Expired or Conflicting**:
   - Flag `vendor_review_expired` or `conflicting_vendor_evidence`.
   - Route to Information Security for re-certification.

---

## 6. What Was Intentionally Not Built

1. **Autonomous PO Issuance / Purchasing**: Policy Section 11 strictly mandates human purchase authority. Autonomous purchasing is excluded by design.
2. **Direct Budget Modification**: The agent flags shortfalls but cannot alter ledger allocations.
3. **Overly Complex Multi-Agent Frameworks**: Avoided heavy frameworks (LangGraph, CrewAI, AutoGen) that introduce unbounded latency and runtime failure points for what is fundamentally a two-stage verification pipeline.

---

## 7. Key Assumptions

1. **Policy Reference Snapshot Date**: All date-based logic (e.g. 365-day vendor security assessment validity) assumes the static reference snapshot `2026-09-30` from `data/procurement_policy.md` rather than system current date.
2. **Untrusted Business Data**: Requester text and notes are untrusted inputs, not instructions. Prompt injection attempts cannot bypass security, budget, or policy constraints.
3. **Deterministic Arithmetic**: Budget validation assumes `available_usd = annual_software_budget_usd - committed_usd`.
4. **Failsafe Degradation**: If third-party vendor risk data cannot be retrieved (HTTP 503 or outage), the system assumes evidence is unverified and requires manual Security review.
5. **Human Gate Permanence**: Advisory recommendation outputs always preserve `human_review_required = True`.
