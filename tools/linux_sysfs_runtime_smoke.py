#!/usr/bin/env python3
"""Run the packaged Runtime against disposable GPIO and LED sysfs fixtures."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdr-sysfs-") as temporary:
        root = Path(temporary)
        gpio = root / "gpio17"
        led = root / "led"
        gpio.mkdir()
        led.mkdir()
        (gpio / "direction").write_text("in", encoding="ascii")
        (gpio / "value").write_text("1", encoding="ascii")
        (led / "max_brightness").write_text("255", encoding="ascii")
        (led / "brightness").write_text("128", encoding="ascii")

        command = [
            sys.executable,
            str(args.runtime_smoke),
            "--executable", str(args.executable),
            "--working-directory", str(args.working_directory),
            "--config", str(args.config),
            "--timeout", "20",
            "--stability-window", "2",
            "--clear-code-cache",
            "--endpoint", "/api/v1/devices",
            "--set", "pdr.gpio.count=1",
            "--set", "pdr.gpio.0.id=gpio-reference",
            "--set", "pdr.gpio.0.pin=17",
            "--set", "pdr.gpio.0.direction=out",
            "--set", f"pdr.gpio.0.sysfsRoot={root.as_posix()}",
            "--set", "pdr.gpio.0.manageExport=false",
            "--set", "pdr.led.count=1",
            "--set", "pdr.led.0.id=led-reference",
            "--set", f"pdr.led.0.path={led.as_posix()}",
            "--require-log", "started with 3 device",
            "--require-body", "gpio-reference",
            "--require-body", "led-reference",
            "--require-body", '"type":"gpio.sysfs"',
            "--require-body", '"type":"led.sysfs"',
            "--require-body", '"state":"ready"',
            "--require-body", '"diagnostics":',
            "--report", str(args.report),
        ]
        for item in args.path:
            command.extend(["--path", item])
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
        if (gpio / "direction").read_text(encoding="ascii") != "out":
            print("LINUX_SYSFS_RUNTIME_FAIL GPIO direction was not configured", file=sys.stderr)
            return 1
    print(f"LINUX_SYSFS_RUNTIME_PASS report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
