#!/usr/bin/env python3
"""Collect and enforce protocol-gateway evidence from /api/v1/protocols."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Any


COUNTERS = (
    "successfulOperations", "failedOperations", "reconnectAttempts",
    "sentMessages", "receivedMessages", "sentBytes", "receivedBytes",
    "timeouts", "handlerFailures",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--protocol-id", required=True)
    parser.add_argument("--protocol-type")
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--authorization-environment")
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--client-certificate", type=Path)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--private-key-password-environment")
    parser.add_argument("--minimum-success-delta", type=int, default=0)
    parser.add_argument("--minimum-reconnect-delta", type=int, default=0)
    parser.add_argument("--minimum-sent-message-delta", type=int, default=0)
    parser.add_argument("--minimum-received-message-delta", type=int, default=0)
    parser.add_argument("--minimum-sent-byte-delta", type=int, default=0)
    parser.add_argument("--minimum-received-byte-delta", type=int, default=0)
    parser.add_argument("--maximum-failed-delta", type=int, default=0)
    parser.add_argument("--maximum-timeout-delta", type=int, default=0)
    parser.add_argument("--maximum-handler-failure-delta", type=int, default=0)
    parser.add_argument("--maximum-probe-errors", type=int, default=0)
    parser.add_argument("--maximum-consecutive-closed-samples", type=int, default=0)
    parser.add_argument("--allow-final-closed", action="store_true")
    parser.add_argument("--allow-final-desired-closed", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def fetch(url: str, timeout: float, context: ssl.SSLContext | None,
          authorization: str | None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        if response.status != 200:
            raise RuntimeError(f"protocol inventory returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("protocol inventory is not a JSON object")
    return payload


def select_protocol(inventory: dict[str, Any], protocol_id: str,
                    protocol_type: str | None) -> dict[str, Any]:
    for protocol in inventory.get("protocols", []):
        if protocol.get("id") != protocol_id:
            continue
        if protocol_type and protocol.get("type") != protocol_type:
            raise RuntimeError(
                f"protocol {protocol_id} type {protocol.get('type')!r} "
                f"is not {protocol_type!r}")
        if not isinstance(protocol.get("diagnostics"), dict):
            raise RuntimeError(f"protocol {protocol_id} does not expose diagnostics")
        return protocol
    raise RuntimeError(f"protocol not found: {protocol_id}")


def counter(protocol: dict[str, Any], name: str) -> int:
    value = protocol["diagnostics"].get(name, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"invalid diagnostics counter {name}: {value!r}")
    return value


def maximum_consecutive_closed(samples: list[dict[str, Any]]) -> int:
    current = maximum = 0
    for sample in samples:
        current = 0 if sample["open"] else current + 1
        maximum = max(maximum, current)
    return maximum


def main() -> int:
    args = parse_args()
    threshold_names = (
        "minimum_success_delta", "minimum_reconnect_delta",
        "minimum_sent_message_delta", "minimum_received_message_delta",
        "minimum_sent_byte_delta", "minimum_received_byte_delta",
        "maximum_failed_delta", "maximum_timeout_delta",
        "maximum_handler_failure_delta", "maximum_probe_errors",
        "maximum_consecutive_closed_samples",
    )
    if args.duration <= 0 or args.interval <= 0 or args.timeout <= 0:
        raise SystemExit("duration, interval and timeout must be positive")
    if any(getattr(args, name) < 0 for name in threshold_names):
        raise SystemExit("acceptance thresholds must be non-negative")
    if bool(args.client_certificate) != bool(args.private_key):
        raise SystemExit("client-certificate and private-key must be configured together")
    if args.private_key_password_environment and not args.private_key:
        raise SystemExit("private-key is required with private-key-password-environment")

    def environment_secret(name: str | None) -> str | None:
        if not name:
            return None
        value = os.environ.get(name)
        if not value:
            raise SystemExit(f"required environment variable is missing or empty: {name}")
        return value

    authorization = environment_secret(args.authorization_environment)
    private_key_password = environment_secret(args.private_key_password_environment)
    tls_context: ssl.SSLContext | None = None
    if args.url.lower().startswith("https://"):
        tls_context = ssl.create_default_context(
            cafile=str(args.ca_file) if args.ca_file else None)
        if args.client_certificate:
            tls_context.load_cert_chain(
                args.client_certificate, args.private_key, private_key_password)
    elif args.ca_file or args.client_certificate or args.private_key:
        raise SystemExit("TLS material requires an https URL")

    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    while True:
        try:
            protocol = select_protocol(
                fetch(args.url, args.timeout, tls_context, authorization),
                args.protocol_id, args.protocol_type)
            samples.append({
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "type": protocol.get("type"),
                "required": protocol.get("required"),
                "open": protocol.get("open") is True,
                "desiredOpen": protocol.get("desiredOpen") is True,
                "diagnostics": protocol["diagnostics"],
            })
        except Exception as error:  # Every failed probe belongs in the evidence.
            errors.append(str(error))
        elapsed = time.monotonic() - started
        if elapsed >= args.duration:
            break
        time.sleep(min(args.interval, args.duration - elapsed))

    failures: list[str] = []
    deltas: dict[str, int] = {}
    closed_run = maximum_consecutive_closed(samples)
    if len(errors) > args.maximum_probe_errors:
        failures.append("probe error count above maximum")
    if samples:
        first, last = samples[0], samples[-1]
        for name in COUNTERS:
            deltas[name] = counter(last, name) - counter(first, name)
            if deltas[name] < 0:
                failures.append(f"diagnostics counter decreased: {name}")
        minimums = {
            "successfulOperations": args.minimum_success_delta,
            "reconnectAttempts": args.minimum_reconnect_delta,
            "sentMessages": args.minimum_sent_message_delta,
            "receivedMessages": args.minimum_received_message_delta,
            "sentBytes": args.minimum_sent_byte_delta,
            "receivedBytes": args.minimum_received_byte_delta,
        }
        maximums = {
            "failedOperations": args.maximum_failed_delta,
            "timeouts": args.maximum_timeout_delta,
            "handlerFailures": args.maximum_handler_failure_delta,
        }
        for name, required in minimums.items():
            if deltas[name] < required:
                failures.append(f"{name} delta below minimum")
        for name, allowed in maximums.items():
            if deltas[name] > allowed:
                failures.append(f"{name} delta above maximum")
        if closed_run > args.maximum_consecutive_closed_samples:
            failures.append("consecutive closed sample count above maximum")
        if not args.allow_final_closed and not last["open"]:
            failures.append("protocol is closed in final sample")
        if not args.allow_final_desired_closed and not last["desiredOpen"]:
            failures.append("protocol desiredOpen is false in final sample")
    else:
        failures.append("no valid protocol samples collected")

    evidence = {
        "schemaVersion": 1,
        "protocolId": args.protocol_id,
        "protocolType": args.protocol_type,
        "url": args.url,
        "durationSeconds": round(time.monotonic() - started, 3),
        "thresholds": {
            "minimumSuccessDelta": args.minimum_success_delta,
            "minimumReconnectDelta": args.minimum_reconnect_delta,
            "minimumSentMessageDelta": args.minimum_sent_message_delta,
            "minimumReceivedMessageDelta": args.minimum_received_message_delta,
            "minimumSentByteDelta": args.minimum_sent_byte_delta,
            "minimumReceivedByteDelta": args.minimum_received_byte_delta,
            "maximumFailedDelta": args.maximum_failed_delta,
            "maximumTimeoutDelta": args.maximum_timeout_delta,
            "maximumHandlerFailureDelta": args.maximum_handler_failure_delta,
            "maximumProbeErrors": args.maximum_probe_errors,
            "maximumConsecutiveClosedSamples": args.maximum_consecutive_closed_samples,
            "requireFinalOpen": not args.allow_final_closed,
            "requireFinalDesiredOpen": not args.allow_final_desired_closed,
        },
        "transportSecurity": {
            "https": args.url.lower().startswith("https://"),
            "customCA": bool(args.ca_file),
            "mutualTLS": bool(args.client_certificate),
            "authorizationEnvironment": args.authorization_environment,
            "privateKeyPasswordEnvironment": args.private_key_password_environment,
        },
        "deltas": deltas,
        "maximumConsecutiveClosedSamplesObserved": closed_run,
        "samples": samples,
        "probeErrors": errors,
        "failures": failures,
        "passed": not failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("PROTOCOL_ACCEPTANCE_PASS" if not failures else "PROTOCOL_ACCEPTANCE_FAIL",
          f"protocol={args.protocol_id} samples={len(samples)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
