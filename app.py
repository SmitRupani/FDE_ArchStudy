from __future__ import annotations

import json
import os
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.contracts import ProcurementDecision
from src.llm_client import get_model_name, is_llm_configured
from src.solution import handle_request

ROOT = Path(__file__).resolve().parent
REQUESTS = json.loads((ROOT / "data" / "requests.json").read_text(encoding="utf-8"))
BY_ID = {r["request_id"]: r for r in REQUESTS}

# Streamlit Page Setup
st.set_page_config(
    page_title="AI Procurement Request Copilot",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .metric-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .badge-approval {
        display: inline-block;
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        margin: 2px 4px 2px 0;
    }
    .badge-risk {
        display: inline-block;
        background-color: #fee2e2;
        color: #b91c1c;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        margin: 2px 4px 2px 0;
    }
    .badge-info {
        display: inline-block;
        background-color: #fef3c7;
        color: #92400e;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        margin: 2px 4px 2px 0;
    }
    .recommendation-box {
        background-color: #f0fdf4;
        border-left: 5px solid #22c55e;
        padding: 16px;
        border-radius: 6px;
        margin-bottom: 16px;
    }
    .caution-box {
        background-color: #fffbeb;
        border-left: 5px solid #f59e0b;
        padding: 16px;
        border-radius: 6px;
        margin-bottom: 16px;
    }
    .action-box {
        background-color: #eff6ff;
        border-left: 5px solid #3b82f6;
        padding: 14px;
        border-radius: 6px;
        margin-top: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Sidebar Configuration
st.sidebar.title("🛡️ Procurement Copilot")
st.sidebar.caption("Intelligent Software Intake & Compliance Engine")

request_id = st.sidebar.selectbox(
    "Select Purchase Request",
    list(BY_ID.keys()),
    format_func=lambda rid: f"{rid}: {BY_ID[rid]['product_name']} ({BY_ID[rid]['vendor_name']})",
)

architecture = st.sidebar.radio(
    "Agent Architecture",
    options=["single", "staged"],
    format_func=lambda x: "Architecture A: Single-Agent Baseline" if x == "single" else "Architecture B: Staged / 2-Agent Variant",
    index=0,
)

st.sidebar.markdown("---")
# LLM Status Indicator
llm_active = is_llm_configured()
model_name = get_model_name()
if llm_active:
    st.sidebar.success(f"🟢 LLM Connected\n`{model_name}`")
else:
    st.sidebar.info("🔵 Engine: Local Reasoner\n(Add OPENROUTER_API_KEY in `.env` for cloud LLM)")

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    **Policy Reference Snapshot:**  
    📅 `2026-09-30`  
    *(Deterministic baseline per policy)*
    """
)

# Header
st.title("AI Procurement Request Copilot")
st.markdown(
    "Analyze enterprise software requests, verify budget, inspect catalog overlap, "
    "audit vendor risk, and route cross-functional approvals while keeping authority with humans."
)

req = BY_ID[request_id]

# Two Column Layout: Request on Left, Copilot on Right
col_left, col_right = st.columns([1.0, 1.2], gap="large")

with col_left:
    st.subheader("📋 Purchase Request Details")
    
    # Request Metric Cards
    c1, c2, c3 = st.columns(3)
    annual_cost = req.get("annual_cost_usd")
    cost_str = f"${annual_cost:,.2f}" if annual_cost is not None else "⚠️ Unspecified"
    c1.metric("Annual Cost", cost_str)
    
    user_cnt = req.get("user_count")
    user_str = f"{user_cnt} users" if user_cnt is not None else "⚠️ Unspecified"
    c2.metric("License Seats", user_str)
    
    urgency = str(req.get("urgency", "normal")).upper()
    c3.metric("Urgency", urgency)

    # Detailed Request Attributes
    with st.container():
        st.markdown(f"**Product Name:** `{req.get('product_name')}`")
        st.markdown(f"**Vendor Name:** `{req.get('vendor_name')}`")
        st.markdown(f"**Category:** `{req.get('category')}`")
        st.markdown(f"**Requester ID:** `{req.get('requester_id')}`")
        st.markdown(f"**Data Access Level:** `{req.get('data_access_level')}`")
        
        integrations = req.get("requested_integrations", [])
        int_str = ", ".join(integrations) if integrations else "None"
        st.markdown(f"**Requested Integrations:** `{int_str}`")

        st.markdown("**Business Justification:**")
        st.info(req.get("business_justification", "None provided"))

    with st.expander("🔍 View Raw Request JSON", expanded=False):
        st.json(req)

with col_right:
    st.subheader("🤖 Copilot Analysis & Human Routing")
    
    run_btn = st.button("🚀 Run Copilot Analysis", type="primary", use_container_width=True)
    
    if run_btn or f"res_{request_id}_{architecture}" in st.session_state:
        if run_btn:
            t0 = time.perf_counter()
            with st.spinner(f"Executing {architecture.title()} Agent workflow..."):
                try:
                    result = handle_request(request_id, architecture=architecture)
                    latency_ms = (time.perf_counter() - t0) * 1000
                    st.session_state[f"res_{request_id}_{architecture}"] = (result, latency_ms)
                except Exception as exc:
                    st.error(f"Analysis failed: {exc}")
                    st.stop()
                    
        result, latency_ms = st.session_state[f"res_{request_id}_{architecture}"]
        
        # Recommendation Banner
        has_risks = len(result.risk_flags) > 0 or len(result.missing_information) > 0
        box_class = "caution-box" if has_risks else "recommendation-box"
        icon = "⚠️" if has_risks else "✅"
        
        st.markdown(
            f"""
            <div class="{box_class}">
                <h4 style="margin:0 0 6px 0;">{icon} Copilot Recommendation</h4>
                <p style="margin:0; font-size:1.05rem; font-weight:500;">{result.recommendation}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Required Approvals
        st.markdown("##### 👥 Required Approvals")
        if result.required_approvals:
            badges_html = " ".join([f'<span class="badge-approval">{a}</span>' for a in result.required_approvals])
            st.markdown(badges_html, unsafe_allow_html=True)
        else:
            st.write("No specific approvals assigned yet.")
            
        # Risk Flags
        if result.risk_flags:
            st.markdown("##### 🚩 Risk & Compliance Flags")
            flags_html = " ".join([f'<span class="badge-risk">⚠️ {flag}</span>' for flag in result.risk_flags])
            st.markdown(flags_html, unsafe_allow_html=True)

        # Missing Information
        if result.missing_information:
            st.markdown("##### ❓ Missing Required Information")
            for item in result.missing_information:
                st.markdown(f"- ⚠️ **Missing:** `{item}`")

        # Next Step & Human Action
        st.markdown(
            f"""
            <div class="action-box">
                <h5 style="margin:0 0 4px 0;">📌 Next Action</h5>
                <p style="margin:0;">{result.next_step}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Grounded Evidence Panel
        st.markdown("---")
        st.markdown("##### 📑 Grounded Evidence & Tool Verification")
        for i, ev in enumerate(result.evidence, 1):
            with st.expander(f"Evidence #{i} — [{ev.source}]", expanded=True):
                st.write(ev.finding)
                if ev.reference:
                    st.caption(f"Reference: `{ev.reference}`")
                    
        # Telemetry & Execution Specs
        st.markdown("---")
        st.markdown("##### ⏱️ Observability & Telemetry")
        tel = result.telemetry
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("End-to-End Latency", f"{latency_ms:.0f} ms")
        m2.metric("LLM Invocations", tel.llm_calls if tel else 0)
        m3.metric("Tool Invocations", tel.tool_calls if tel else 0)
        cost_str = f"${tel.estimated_cost_usd:.6f}" if tel and tel.estimated_cost_usd is not None else "$0.0000"
        m4.metric("Est. Inference Cost", cost_str)

        if tel and tel.total_tokens:
            t_col1, t_col2, t_col3 = st.columns(3)
            t_col1.caption(f"📥 **Prompt Tokens:** {tel.prompt_tokens:,}")
            t_col2.caption(f"📤 **Completion Tokens:** {tel.completion_tokens:,}")
            t_col3.caption(f"📊 **Total Tokens:** {tel.total_tokens:,}")

        if tel and tel.tool_latencies_ms:
            with st.expander("⏱️ Tool Execution Latencies Breakdown", expanded=False):
                for t_name, t_ms in tel.tool_latencies_ms.items():
                    st.write(f"- `{t_name}`: **{t_ms:.1f} ms**")

        # Enterprise Auditability & Compliance Verification (SOX / SOC 2)
        st.markdown("---")
        st.markdown("##### 🛡️ Enterprise Audit & Compliance Ledger")
        audit = result.audit_trail
        if audit:
            st.success(f"🔒 **Cryptographic Audit Record Generated**: `{audit.audit_id[:13]}...`")
            framework_html = " ".join([f'<span class="badge-approval">📋 {fw}</span>' for fw in audit.compliance_frameworks])
            st.markdown(framework_html, unsafe_allow_html=True)
            
            with st.expander("📜 View Audit Verification Details (SOX / SOC 2 / ISO 27001)", expanded=False):
                st.markdown(f"**Audit UUID:** `{audit.audit_id}`")
                st.markdown(f"**Timestamp (UTC):** `{audit.timestamp_utc}`")
                st.markdown(f"**Policy Version & Baseline:** `{audit.policy_version}` (Date: `{audit.policy_reference_date}`)")
                st.markdown(f"**Request SHA-256 Hash:** `{audit.request_hash}`")
                st.markdown(f"**Decision SHA-256 Hash:** `{audit.decision_hash}`")
                st.markdown(f"**Tamper-Evident Composite Signature:** `{audit.integrity_signature}`")
                
                from src.audit import verify_audit_integrity
                is_valid, msg = verify_audit_integrity(audit, req, result.model_dump())
                if is_valid:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
        else:
            st.info("No audit record generated for this session.")

        # Human Review Gate Check
        st.markdown("---")
        st.markdown("##### ✍️ Human Decision Checkpoint")
        human_decision = st.radio(
            "Human Reviewer Action",
            [
                "Pending Review",
                "Approve Request & Dispatch to Assigned Approvers",
                "Request Missing Clarification from Requester",
                "Reject Request (Duplicate / Policy Non-compliant)",
            ],
            key=f"human_decision_{request_id}",
        )
        if human_decision != "Pending Review":
            st.success(f"Action Recorded: {human_decision}")

    else:
        st.info("👈 Click **Run Copilot Analysis** to evaluate this purchase request.")

st.divider()
st.caption("🔒 Architecture Compliance: Final approval authority remains strictly with designated human reviewers per Procurement Policy Section 11.")
