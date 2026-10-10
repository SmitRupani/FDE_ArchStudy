# Architecture Decision Memo

**Maximum length: 500 words**

## Decision
We recommend shipping **Architecture A (Single Agent)** for the production MVP today.

## Evidence
Both architectures were evaluated against the exact same test harness across all six public evaluation cases (PUB-01 through PUB-06), testing low-value purchases, catalog alternatives, sensitive data/source-code access, budget shortfalls, prompt injection attempts, and upstream API outages.

| Metric | Single agent | Staged / 2-agent |
|---|---:|---:|
| Cases passing your quality criteria | 6 / 6 (100%) | 6 / 6 (100%) |
| Avg latency | 3,009 ms | 9,091 ms |
| Avg LLM calls | 1.0 | 2.0 |
| Avg tool calls | 5.0 | 5.0 |
| Notable policy/grounding failures | 0 | 0 |

## Trade-offs
- **Latency & Cost**: The single-agent baseline achieves a **3.01s average turnaround** compared to **9.09s for the staged variant** (a **3.02x latency penalty**). Calling a secondary reviewer agent doubled LLM token consumption and introduced an additional network round-trip.
- **Architectural Complexity**: The staged architecture introduces intermediate serialization overhead and handoff synchronization between the *Procurement Analyst* and the *Policy Reviewer*. In return, it offers isolated inspection of raw tool findings prior to compliance evaluation. However, because our deterministic policy engine already enforces threshold and compliance matrices in code, this secondary LLM stage produced identical policy decisions without improving gate accuracy.

## Risks / Limitations
Before deploying to organization-wide production:
1. **Clarification Loops**: We should validate interactive multi-turn Slack/email collection when requesters submit missing specifications.
2. **Contract Document Parsing**: Future phases must parse unstructured MSAs/SOWs using multimodal document understanding alongside structured vendor registry lookups.
3. **Resilience under Upstream Outages**: Extended vendor-risk API outages should fall back to cached historical assessments with explicit staleness warnings.

## Why This Is the Right MVP
The single-agent design adheres strictly to the client's design principle: **AI for context interpretation and user-facing synthesis, deterministic code for policy thresholds and tool validation, and humans for sensitive approvals and spend exceptions.**

By anchoring tool execution (budget checks, catalog overlap matching, vendor registry lookups, external risk queries, and prompt injection defense) in deterministic Python modules, the single agent consistently produces fully grounded evidence packages without hallucinations or rule bypasses. It delivers maximum reliability, 3x faster response times, and lower operating costs without unnecessary multi-agent orchestration overhead.
