#!/usr/bin/env python3
"""Run the packaged Runtime against a local Modbus TCP connection endpoint."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import threading
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--path", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stop = threading.Event()
    accepted = threading.Event()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.2)
    port = listener.getsockname()[1]

    def serve() -> None:
        connection: socket.socket | None = None
        try:
            while not stop.is_set() and connection is None:
                try:
                    connection, _ = listener.accept()
                    accepted.set()
                except TimeoutError:
                    continue
            while connection is not None and not stop.wait(0.1):
                pass
        finally:
            if connection is not None:
                connection.close()
            listener.close()

    peer = threading.Thread(target=serve, name="modbus-runtime-peer", daemon=True)
    peer.start()
    command = [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", "20", "--stability-window", "2", "--clear-code-cache",
        "--endpoint", "/api/v1/devices",
        "--set", "pdr.modbus.enabled=true",
        "--set", "pdr.modbus.id=modbus-reference",
        "--set", "pdr.modbus.host=127.0.0.1",
        "--set", f"pdr.modbus.port={port}",
        "--require-body", "modbus-reference",
        "--require-body", '"type":"modbus.registers"',
        "--require-body", '"diagnostics":',
        "--require-body", '"reconnectAttempts":0',
        "--require-log", r"started with 2 device\(s\)",
        "--report", str(args.report),
    ]
    for path in args.path:
        command.extend(["--path", path])
    try:
        completed = subprocess.run(command, check=False)
        if completed.returncode == 0 and not accepted.is_set():
            print("MODBUS_RUNTIME_SMOKE_FAIL runtime never connected to peer", file=sys.stderr)
            return 2
        return completed.returncode
    finally:
        stop.set()
        peer.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
