#!/usr/bin/env python3
"""Exercise native and pdr identity policy checks with real file permissions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], expected: int) -> dict:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != expected:
        raise RuntimeError(
            f"command returned {completed.returncode}, expected {expected}: {completed.stdout} {completed.stderr}"
        )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise RuntimeError("identity command did not return a JSON object")
    return result


def restrict(path: Path) -> None:
    if os.name == "nt":
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(["icacls", str(path), "/inheritance:r"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["icacls", str(path), "/grant:r", f"{account}:F"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["icacls", str(path), "/grant:r", "*S-1-5-18:F"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["icacls", str(path), "/grant:r", "*S-1-5-32-544:F"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        path.chmod(0o600)


def broaden(path: Path) -> None:
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:R"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        path.chmod(0o644)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checker", type=Path, required=True)
    parser.add_argument("--pdr", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    secret_value = "identity-check-secret-never-log"
    with tempfile.TemporaryDirectory(prefix="pdr-identity-check-") as directory:
        root = Path(directory)
        secret = root / "operator.token"
        secret.write_text(secret_value + "\n", encoding="utf-8")
        restrict(secret)
        configuration = root / "identity.properties"
        configuration.write_text(
            "pdr.management.authentication.required = true\n"
            "pdr.management.authentication.principals.count = 1\n"
            "pdr.management.authentication.principals.0.id = operator\n"
            f"pdr.management.authentication.principals.0.tokenFile = {secret.as_posix()}\n"
            "pdr.management.authentication.principals.0.permissions = identity.manage\n",
            encoding="utf-8",
        )
        secure = run([str(args.checker), "--strict", str(configuration)], 0)
        wrapped = run([str(args.python), str(args.pdr), "identity", "check",
                       str(configuration), "--executable", str(args.checker)], 0)
        if secure.get("insecureFileCount") != 0 or not secure.get("filePermissionChecksComplete"):
            raise RuntimeError("restricted token file did not pass permission inspection")
        if wrapped.get("evidence", {}).get("fileBackedPrincipalCount") != 1:
            raise RuntimeError("pdr identity wrapper lost native evidence")
        broaden(secret)
        insecure = run([str(args.checker), "--strict", str(configuration)], 1)
        if "TOKEN_FILE_ACCESS_TOO_BROAD" not in insecure.get("denialReasons", []):
            raise RuntimeError("broad token-file access did not fail production policy")
        evidence = json.dumps({"secure": secure, "wrapped": wrapped, "insecure": insecure})
        if secret_value in evidence:
            raise RuntimeError("identity checker leaked the token value")
    print("IDENTITY_CHECK_INTEGRATION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
