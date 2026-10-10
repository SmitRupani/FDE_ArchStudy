from __future__ import annotations

from src.contracts import Architecture, ProcurementDecision


from src.agents import SingleProcurementAgent, StagedProcurementWorkflow

_single_agent = SingleProcurementAgent()
_staged_workflow = StagedProcurementWorkflow()


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter.

    Routes evaluation cases to Architecture A (single-agent baseline) or
    Architecture B (lightweight staged / 2-agent variant).
    """
    if architecture == "single":
        return _single_agent.run(request_id)
    elif architecture == "staged":
        return _staged_workflow.run(request_id)
    else:
        raise ValueError(f"Unsupported architecture: '{architecture}'. Choose 'single' or 'staged'.")
