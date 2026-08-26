#!/usr/bin/env python3
"""Exercise file-backed management-token rotation in one live Runtime process."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_smoke import free_port, probe, stop_tree, write_overlay  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    token_file = report.with_name(report.stem + "-token.secret")
    overlay = report.with_name(report.stem + ".properties")
    audit = report.with_name(report.stem + "-audit.jsonl")
    log = report.with_name(report.stem + ".log")
    runtime_log = report.with_name(report.stem + "-runtime.log")
    old_token = secrets.token_urlsafe(48)
    new_token = secrets.token_urlsafe(48)
    port = free_port("127.0.0.1")
    process = None
    log_stream = None
    shutdown = None

    def replace_token(value: str) -> None:
        replacement = token_file.with_suffix(".new")
        replacement.write_text(value, encoding="utf-8", newline="\n")
        os.replace(replacement, token_file)

    def request(endpoint: str, token: str, method: str = "GET", request_id: str = ""):
        headers = {"Authorization": f"Bearer {token}"}
        if request_id:
            headers["X-PDR-Request-Id"] = request_id
        return probe(f"http://127.0.0.1:{port}{endpoint}", 2.0, method=method,
                     body="{}" if method == "POST" else None, extra_headers=headers)

    result = {"schemaVersion": 1, "passed": False, "port": port}
    try:
        replace_token(old_token + "\n")
        write_overlay(args.config.resolve(), overlay, "127.0.0.1", port, {
            "auth.simple.enable": "false",
            "osp.web.authServiceName": "pdr.auth.management",
            "osp.web.tokenValidatorName": "pdr.auth.management.tokens",
            "pdr.management.authentication.required": "true",
            "pdr.management.authentication.tokenEnvironment": "",
            "pdr.management.authentication.tokenFile": "",
            "pdr.management.authentication.principals.count": "1",
            "pdr.management.authentication.principals.0.id": "rotation-admin",
            "pdr.management.authentication.principals.0.tokenEnvironment": "",
            "pdr.management.authentication.principals.0.tokenFile": token_file.as_posix(),
            "pdr.management.authentication.principals.0.permissions": "*",
            "pdr.management.audit.path": audit.as_posix(),
            "pdr.management.idempotency.persistence.enabled": "false",
            "logging.channels.file.path": runtime_log.as_posix(),
        })
        environment = os.environ.copy()
        search = os.pathsep.join(str(Path(item).resolve()) for item in args.path)
        if search:
            environment["PATH"] = search + os.pathsep + environment.get("PATH", "")
        option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        log_stream = log.open("wb")
        process = subprocess.Popen(
            [str(args.executable.resolve()), option], cwd=args.working_directory.resolve(),
            env=environment, stdout=log_stream, stderr=subprocess.STDOUT,
            creationflags=creationflags, start_new_session=os.name != "nt")

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Runtime exited during startup: {process.returncode}")
            status, _ = request("/api/v1/identity", old_token)
            if status == 200:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("identity endpoint did not become ready")
        time.sleep(2.0)
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited while settling: {process.returncode}")

        old_status, old_body = request("/api/v1/identity", old_token)
        new_before_status, _ = request("/api/v1/identity", new_token)
        before = json.loads(old_body)
        if old_status != 200 or new_before_status != 401 or before["generation"] != 1:
            raise RuntimeError("initial identity snapshot authentication failed")
        if (before.get("fileBackedPrincipalCount") != 1 or
                before.get("environmentBackedPrincipalCount") != 0):
            raise RuntimeError("identity snapshot secret-source diagnostics are incorrect")

        def concurrent_probe(token: str, accepted_generations: set[int]):
            observations = []
            for _ in range(40):
                status, body = request("/api/v1/identity", token)
                generation = json.loads(body).get("generation") if status == 200 else None
                if status not in {200, 401}:
                    raise RuntimeError(f"concurrent identity probe returned HTTP {status}")
                if status == 200 and generation not in accepted_generations:
                    raise RuntimeError("token authenticated against a mismatched identity generation")
                observations.append(status)
                time.sleep(0.005)
            return observations

        replace_token(new_token + "\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # Authentication and the diagnostic snapshot read are separate
            # linearization points. An old-token request authenticated before
            # the swap may therefore return the generation-2 snapshot while it
            # drains; the post-reload probes below prove it cannot authenticate
            # after the transition has completed.
            old_futures = [executor.submit(concurrent_probe, old_token, {1, 2})
                           for _ in range(4)]
            new_futures = [executor.submit(concurrent_probe, new_token, {2})
                           for _ in range(4)]
            time.sleep(0.05)
            reload_status, reload_body = request(
                "/api/v1/identity", old_token, "POST", "identity-rotation-success")
            old_observations = [status for future in old_futures for status in future.result()]
            new_observations = [status for future in new_futures for status in future.result()]
        reloaded = json.loads(reload_body)
        old_after_status, _ = request("/api/v1/identity", old_token)
        new_after_status, new_after_body = request("/api/v1/identity", new_token)
        web_event_status, _ = request("/webevent", new_token)
        if (reload_status != 200 or reloaded.get("generationBefore") != 1 or
                reloaded.get("generation") != 2 or old_after_status != 401 or
                new_after_status != 200 or web_event_status != 400):
            raise RuntimeError("successful rotation did not update every authentication surface")
        if 200 not in old_observations or 401 not in old_observations:
            raise RuntimeError("concurrent old-token probes did not span the atomic transition")
        if 401 not in new_observations or 200 not in new_observations:
            raise RuntimeError("concurrent new-token probes did not span the atomic transition")

        replace_token("")
        failed_status, failed_body = request(
            "/api/v1/identity", new_token, "POST", "identity-rotation-failure")
        failed = json.loads(failed_body)
        retained_status, retained_body = request("/api/v1/identity", new_token)
        retained = json.loads(retained_body)
        if (failed_status != 400 or not failed.get("unchanged") or
                failed.get("generation") != 2 or retained_status != 200 or
                retained.get("generation") != 2):
            raise RuntimeError("failed reload did not preserve the previous snapshot")

        result.update({
            "passed": True,
            "initialGeneration": before["generation"],
            "rotatedGeneration": reloaded["generation"],
            "oldTokenAfterRotationStatus": old_after_status,
            "newTokenAfterRotationStatus": new_after_status,
            "webEventHandshakeStatus": web_event_status,
            "failedReloadStatus": failed_status,
            "failedReloadRetainedGeneration": retained["generation"],
            "principalCount": json.loads(new_after_body)["principalCount"],
            "filePermissionChecksComplete": before["filePermissionChecksComplete"],
            "insecureFileCount": before["insecureFileCount"],
            "concurrentOldToken": {"accepted": old_observations.count(200),
                                   "rejected": old_observations.count(401)},
            "concurrentNewToken": {"accepted": new_observations.count(200),
                                   "rejected": new_observations.count(401)},
        })
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process is not None:
            shutdown = stop_tree(process, 8.0)
            result["shutdown"] = shutdown
        if log_stream is not None:
            log_stream.close()
        evidence = ""
        for path in (log, runtime_log, audit):
            if path.exists():
                evidence += path.read_text(encoding="utf-8", errors="replace")
        leaks = [name for name, value in (("old", old_token), ("new", new_token))
                 if value in evidence]
        result["credentialsLeaked"] = bool(leaks)
        if leaks:
            result["passed"] = False
            result["error"] = "token value leaked into Runtime log or audit"
        if shutdown and not shutdown.get("clean"):
            result["passed"] = False
            result["error"] = "Runtime did not shut down cleanly"
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        token_file.unlink(missing_ok=True)
        overlay.unlink(missing_ok=True)

    if result["passed"]:
        print(f"RUNTIME_IDENTITY_ROTATION_PASS report={report}")
        return 0
    print(f"RUNTIME_IDENTITY_ROTATION_ERROR: {result.get('error')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
