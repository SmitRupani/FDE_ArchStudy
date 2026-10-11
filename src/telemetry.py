from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunTelemetryCounter:
    """Enterprise observability and telemetry counter."""
    llm_calls: int = 0
    tool_calls: int = 0
    tool_names: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_latencies_ms: dict[str, float] = field(default_factory=dict)

    def record_llm_call(self) -> None:
        self.llm_calls += 1

    def record_tool_call(self, name: str, latency_ms: float | None = None) -> None:
        self.tool_calls += 1
        self.tool_names.append(name)
        if latency_ms is not None:
            self.tool_latencies_ms[name] = round(latency_ms, 2)

    def record_token_usage(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += max(0, prompt)
        self.completion_tokens += max(0, completion)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def calculate_estimated_cost_usd(self) -> float:
        """Estimate inference cost in USD based on $0.15/1M input and $0.60/1M output tokens."""
        input_cost = (self.prompt_tokens / 1_000_000.0) * 0.150
        output_cost = (self.completion_tokens / 1_000_000.0) * 0.600
        return round(input_cost + output_cost, 6)
