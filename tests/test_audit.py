from __future__ import annotations

import unittest
from src.audit import (
    compute_integrity_signature,
    generate_audit_record,
    hash_dict,
    verify_audit_integrity,
)


class AuditComplianceTests(unittest.TestCase):
    def setUp(self):
        self.mock_request = {
            "request_id": "REQ-TEST-01",
            "product_name": "SecureVault Pro",
            "vendor_name": "VaultTech",
            "annual_cost_usd": 15000,
            "department": "Engineering",
        }
        self.mock_decision = {
            "request_id": "REQ-TEST-01",
            "recommendation": "Route for standard security and financial review",
            "required_approvals": ["Department Head", "Finance", "Security"],
            "risk_flags": ["security_review_required"],
            "missing_information": [],
            "human_review_required": True,
        }

    def test_audit_record_generation_and_verification(self):
        record = generate_audit_record(self.mock_request, self.mock_decision)
        self.assertIsNotNone(record.audit_id)
        self.assertEqual(record.request_id, "REQ-TEST-01")
        self.assertEqual(record.policy_version, "2026.09")
        self.assertEqual(record.policy_reference_date, "2026-09-30")
        self.assertIn("SOX-404", record.compliance_frameworks)

        # Verification must pass for authentic data
        valid, msg = verify_audit_integrity(record, self.mock_request, self.mock_decision)
        self.assertTrue(valid, msg)

    def test_tamper_detection_on_modified_request(self):
        record = generate_audit_record(self.mock_request, self.mock_decision)

        # Alter input payload to simulate tampering
        tampered_request = dict(self.mock_request)
        tampered_request["annual_cost_usd"] = 999999

        valid, msg = verify_audit_integrity(record, tampered_request, self.mock_decision)
        self.assertFalse(valid)
        self.assertIn("mismatch", msg.lower())

    def test_tamper_detection_on_modified_decision(self):
        record = generate_audit_record(self.mock_request, self.mock_decision)

        # Alter decision to simulate unauthorized bypass
        tampered_decision = dict(self.mock_decision)
        tampered_decision["required_approvals"] = []

        valid, msg = verify_audit_integrity(record, self.mock_request, self.mock_decision)
        # Authentic passes
        self.assertTrue(valid)

        # Tampered fails
        tampered_valid, msg = verify_audit_integrity(record, self.mock_request, tampered_decision)
        self.assertFalse(tampered_valid)
        self.assertIn("mismatch", msg.lower())


if __name__ == "__main__":
    unittest.main()
