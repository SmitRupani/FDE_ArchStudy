# AI Procurement Request Copilot

An enterprise AI procurement copilot built to inspect software and service purchase requests, gather grounded evidence using deterministic and API-backed tools, enforce corporate procurement policy thresholds, defend against untrusted prompt injections, and route recommendations to human approvers.

---

## 1. Quick Start & Setup

### Prerequisites
- Python 3.11, 3.12, or 3.13
- Internet access for package installation and model provider calls

### Installation

```bash
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Pre-flight Verification
Run the automated preflight check to confirm environment, dataset integrity, and API health:
```bash
python verify_setup.py
```
Expected output: `PRE-FLIGHT PASSED`.

### Environment Configuration
Copy the template and configure your model provider credentials:
```bash
# Windows
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```
Inside `.env`, set:
```env
VENDOR_RISK_BASE_URL=http://127.0.0.1:8001
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openai/gpt-4o-mini
```
*(Note: If no API key is set, the system automatically runs using its high-fidelity deterministic Local Reasoner, ensuring complete offline reproducibility).*

### Launch Services (One-Command Start)
```bash
python run_local.py
```
This automatically starts:
- **Mock Vendor Risk API**: `http://127.0.0.1:8001`
- **Interactive Streamlit Copilot UI**: `http://127.0.0.1:8501`

---

## 2. Product Workflow & Design Principles

The application implements a strict separation of concerns:

```text
Request (Untrusted Data)
       │
       ▼
Intake & Prompt Defense (prompt_guard_tool)
       │
       ▼
Evidence Gathering (Budget, Catalog Overlap, Vendor Registry, External Risk API)
       │
       ▼
Deterministic Policy Engine (Spend thresholds, Compliance rules, Missing field checks)
       │
       ▼
Model Synthesis (Grounded recommendation + Action plan)
       │
       ▼
Human Review Gate (Advisory recommendation only; sensitive decisions kept with humans)
```

### Core Design Principles
1. **AI**: Interprets business context, synthesizes evidence into plain language, and drafts actionable next steps.
2. **Code**: Deterministically evaluates numerical spend thresholds, budget sufficiency arithmetic, security risk triggers, and policy reference dates.
3. **Human**: Retains exclusive authority over purchase approvals, budget exceptions, and legal terms acceptance per Procurement Policy Section 11.

---

## 3. Architecture Comparison: Single-Agent vs. Staged

We built and evaluated two distinct architectures:

### Architecture A: Single-Agent Baseline
- **Orchestrator**: `SingleProcurementAgent` in `src/agents.py`.
- **Workflow**: A unified agent inspects the request, calls all 5 tools, feeds factual findings into the deterministic policy engine, and uses the LLM to synthesize the final `ProcurementDecision`.
- **Telemetry**: 1 LLM call, 5 tool calls.

### Architecture B: Staged / 2-Agent Variant
- **Agent 1 (Procurement Analyst)**: Validates request completeness, detects prompt injections, executes tool suite, and compiles a typed `EvidencePack`.
- **Agent 2 (Policy & Risk Reviewer)**: Ingests the `EvidencePack`, applies compliance matrices, maps cross-functional stakeholder approvals, and issues the `ProcurementDecision`.
- **Telemetry**: 2 LLM calls, 5 tool calls.

---

## 4. Tool Inventory

| Tool | Type | Description |
|---|---|---|
| `prompt_guard_tool` | Deterministic / Heuristic | Scans untrusted requester text for prompt injection, policy bypass, or fake approval claims. |
| `budget_tool` | Deterministic | Compares annual request spend with available department budget. |
| `catalog_overlap_tool` | Deterministic / Search | Discovers duplicate or alternative software in `software_catalog.csv` and `purchase_history.csv`. |
| `vendor_registry_tool` | Deterministic | Audits `vendors.csv` for onboarding status, draft legal terms, and review expiration (> 365 days from `2026-09-30`). |
| `vendor_risk_api_tool` | API Client | Queries external `/vendor-risk/{vendor_name}` endpoint with graceful fault handling for 503 outages. |

---

## 5. Evaluation & Empirical Results

Run the automated evaluation harness on both architectures:
```bash
python evals/run_public_evals.py --architecture single
python evals/run_public_evals.py --architecture staged
```

### Evaluation Summary Table

| Metric | Architecture A (Single Agent) | Architecture B (Staged 2-Agent) |
|---|---:|---:|
| **Cases Passing Quality Criteria** | **6 / 6 (100%)** | **6 / 6 (100%)** |
| **Average Latency** | **3,009 ms (~3.0s)** | **9,091 ms (~9.1s)** |
| **Average LLM Calls** | **1.0** | **2.0** |
| **Average Tool Calls** | **5.0** | **5.0** |
| **Policy / Grounding Failures** | **0** | **0** |

Both architectures passed all 6 public evaluation test cases:
1. `PUB-01`: Low-value approved vendor ($800 -> Manager approval, no missing info).
2. `PUB-02`: Catalog overlap + new vendor onboarding (BrandBoard -> Dept Head, Finance, Procurement, Security, Legal).
3. `PUB-03`: Sensitive source-code access (CodeMate Teams -> Security review required).
4. `PUB-04`: Budget shortfall + new sensitive vendor (GrowthForge -> Budget insufficient, Finance, Security, Privacy, Legal).
5. `PUB-05`: Incomplete request + prompt injection (NeuralDesk -> Prompt injection detected, missing cost/seats/data access).
6. `PUB-06`: External API outage (NimbusAI -> Vendor-risk unavailable, graceful fallback to manual security review).

Detailed results are saved in `evals/results_single.csv` and `evals/results_staged.csv`.

---

## 6. Architecture Decision

**Decision**: We choose to ship **Architecture A (Single Agent)** as the production MVP.

**Rationale**:
- **3.0x Lower Latency**: Turnaround is ~3.0s versus ~9.1s for the staged pipeline.
- **50% Lower Token Cost**: Requires only 1 LLM call per request instead of 2.
- **Equal Compliance Accuracy**: Because deterministic policy checks are enforced in code, the second agent added latency without changing the outcome.
- **Lower Operational Complexity**: Eliminates intermediate state serialization and multi-agent coordination failure modes.

See full 500-word memo in `templates/architecture_decision.md`.

---

## 7. Known Limitations & Production Roadmap

1. **Clarification Interactivity**: Currently flags missing fields statically; production should trigger interactive Slack / email clarification threads.
2. **Contract Document Understanding**: Expand vendor onboarding to parse uploaded PDF master services agreements (MSAs) using multimodal parsing.
3. **Resilience & Outage Caching**: Add caching with time-to-live (TTL) and explicit staleness alerts during prolonged external API downtime.
