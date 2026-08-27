#!/usr/bin/env python3
"""Focused Fleet v7 signed Adapter conformance recovery acceptance."""

from __future__ import annotations

import unittest

try:
    from .test_team_contract_adapter_conformance_admission import AdmissionTest
except ImportError:
    from test_team_contract_adapter_conformance_admission import AdmissionTest


if __name__ == "__main__":
    suite = unittest.TestSuite([
        AdmissionTest(
            "test_signed_admission_enforces_signature_revocation_and_rotation"
        )
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
