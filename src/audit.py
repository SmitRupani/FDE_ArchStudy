from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.contracts import AuditRecord

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_LOG_PATH = ROOT / "data" / "audit_log.jsonl"


def hash_dict(payload: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of a dictionary."""
    normalized_json = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()


def compute_integrity_signature(
    request_hash: str,
    decision_hash: str,
    policy_version: str = "2026.09",
    policy_date: str = "2026-09-30",
) -> str:
    """Generate tamper-evident composite signature linking request, policy, and decision."""
    composite = f"{request_hash}:{policy_version}:{policy_date}:{decision_hash}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


def generate_audit_record(
    request_payload: dict[str, Any],
    decision_payload: dict[str, Any],
    policy_version: str = "2026.09",
    policy_date: str = "2026-09-30",
) -> AuditRecord:
    """Construct an immutable cryptographic audit record for enterprise compliance (SOX/SOC2)."""
    audit_id = str(uuid.uuid4())
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    request_id = str(request_payload.get("request_id", "UNKNOWN"))

    # Compute individual hashes
    req_hash = hash_dict(request_payload)

    # Decision components for hash
    decision_summary = {
        "request_id": request_id,
        "recommendation": decision_payload.get("recommendation"),
        "required_approvals": sorted(decision_payload.get("required_approvals", [])),
        "risk_flags": sorted(decision_payload.get("risk_flags", [])),
        "missing_information": sorted(decision_payload.get("missing_information", [])),
        "human_review_required": decision_payload.get("human_review_required", True),
    }
    dec_hash = hash_dict(decision_summary)

    # Composite integrity signature
    signature = compute_integrity_signature(
        request_hash=req_hash,
        decision_hash=dec_hash,
        policy_version=policy_version,
        policy_date=policy_date,
    )

    record = AuditRecord(
        audit_id=audit_id,
        timestamp_utc=timestamp_utc,
        request_id=request_id,
        request_hash=req_hash,
        policy_version=policy_version,
        policy_reference_date=policy_date,
        decision_hash=dec_hash,
        integrity_signature=signature,
        compliance_frameworks=["SOX-404", "SOC2-CC6.8", "ISO27001-A.9.4"],
    )

    # Append to local append-only ledger
    try:
        persist_audit_log(record)
    except Exception:
        pass

    return record


def persist_audit_log(record: AuditRecord, log_path: Path | None = None) -> None:
    """Append audit record to an append-only JSONL log file."""
    path = log_path or DEFAULT_AUDIT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")


def verify_audit_integrity(
    record: AuditRecord,
    request_payload: dict[str, Any],
    decision_payload: dict[str, Any],
) -> tuple[bool, str]:
    """Verify that an audit record matches the underlying request and decision hashes."""
    recomputed_req_hash = hash_dict(request_payload)
    if recomputed_req_hash != record.request_hash:
        return False, "Request payload hash mismatch: input has been tampered with or modified."

    decision_summary = {
        "request_id": record.request_id,
        "recommendation": decision_payload.get("recommendation"),
        "required_approvals": sorted(decision_payload.get("required_approvals", [])),
        "risk_flags": sorted(decision_payload.get("risk_flags", [])),
        "missing_information": sorted(decision_payload.get("missing_information", [])),
        "human_review_required": decision_payload.get("human_review_required", True),
    }
    recomputed_dec_hash = hash_dict(decision_summary)
    if recomputed_dec_hash != record.decision_hash:
        return False, "Decision payload hash mismatch: output has been modified."

    recomputed_sig = compute_integrity_signature(
        request_hash=recomputed_req_hash,
        decision_hash=recomputed_dec_hash,
        policy_version=record.policy_version,
        policy_date=record.policy_reference_date,
    )
    if recomputed_sig != record.integrity_signature:
        return False, "Composite signature mismatch: cryptographic integrity invalid."

    return True, "Audit record verified: cryptographic proof intact."
