#!/usr/bin/env python3
"""Focused portable-config recovery acceptance for certifier trust state."""

from __future__ import annotations

import unittest

try:
    from .test_team_contract_adapter_certifier_trust_state_store import \
        TrustStateStoreTest
except ImportError:
    from test_team_contract_adapter_certifier_trust_state_store import \
        TrustStateStoreTest


if __name__ == "__main__":
    suite = unittest.TestSuite([
        TrustStateStoreTest(
            "test_pointer_v2_resolves_same_refs_to_different_host_paths"
        )
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PDR_ADAPTER_CERTIFIER_TRUST_PORTABILITY_PASS pointerV2=1 "
              "logicalRefs=1 hostPaths=3 resolverPin=1 revision=1 scope=1 "
              "v1Compatible=1")
    raise SystemExit(0 if result.wasSuccessful() else 1)
