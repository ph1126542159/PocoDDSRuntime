#!/usr/bin/env python3
"""Cross-platform process leases with durable owner metadata and fencing epochs."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEASE_PRODUCT = "PocoDDSRuntimeProcessFileLease"
EPOCH_PRODUCT = "PocoDDSRuntimeProcessFileLeaseEpoch"
STATUS_PRODUCT = "PocoDDSRuntimeProcessFileLeaseStatus"
LEASE_ID = re.compile(r"[0-9a-f]{32}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class LeaseBusyError(RuntimeError):
    """Raised when another process owns the operating-system lease."""


class LeaseFencedError(ValueError):
    """Raised when a newer lease epoch superseded the current writer."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_time(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("process lease timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("process lease timestamp is malformed") from error
    if parsed.tzinfo is None:
        raise ValueError("process lease timestamp lacks a timezone")


def _validate_details(details: Any) -> None:
    if (not isinstance(details, dict) or len(details) > 16
            or any(not NAME.fullmatch(str(key)) for key in details)
            or any(not isinstance(value, str) or not 1 <= len(value) <= 256
                   or "\r" in value or "\n" in value
                   for value in details.values())):
        raise ValueError("process lease owner details are malformed")


def _linklike(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _reject_link_path(path: Path) -> None:
    for candidate in (path, *path.parents):
        if _linklike(candidate):
            raise ValueError(f"process lease path contains a link: {candidate}")


def validate_epoch(document: Any) -> int:
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "epoch", "updatedAt"
        } or document.get("schemaVersion") != 1
            or document.get("product") != EPOCH_PRODUCT
            or type(document.get("epoch")) is not int or document["epoch"] < 1):
        raise ValueError("process lease epoch is malformed")
    _validate_time(document.get("updatedAt"))
    return document["epoch"]


def validate_owner(document: Any, lease_name: str | None = None) -> dict[str, Any]:
    fields = {
        "schemaVersion", "product", "leaseName", "leaseId", "epoch",
        "pid", "host", "acquiredAt", "details",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != LEASE_PRODUCT
            or not NAME.fullmatch(str(document.get("leaseName", "")))
            or (lease_name is not None and document["leaseName"] != lease_name)
            or not LEASE_ID.fullmatch(str(document.get("leaseId", "")))
            or type(document.get("epoch")) is not int or document["epoch"] < 1
            or type(document.get("pid")) is not int or document["pid"] < 1
            or not isinstance(document.get("host"), str)
            or not 1 <= len(document["host"]) <= 255
            or "\r" in document["host"] or "\n" in document["host"]):
        raise ValueError("process lease owner metadata is malformed")
    _validate_time(document.get("acquiredAt"))
    _validate_details(document.get("details"))
    return document


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is unavailable or is a link")
    try:
        document = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} is not an object")
    return document


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    content = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    descriptor: int | None = os.open(
        temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            parent = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _windows_kernel() -> Any:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFilePointer.argtypes = [
        wintypes.HANDLE, wintypes.LONG, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel.SetFilePointer.restype = wintypes.DWORD
    kernel.SetEndOfFile.argtypes = [wintypes.HANDLE]
    kernel.SetEndOfFile.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
        wintypes.LPDWORD, wintypes.LPVOID,
    ]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


class ProcessFileLease:
    """An OS-owned lease; the file remains as read-only last-owner evidence."""

    def __init__(self, lock_path: str | Path, epoch_path: str | Path,
                 lease_name: str, details: dict[str, str]) -> None:
        raw_lock = Path(lock_path)
        raw_epoch = Path(epoch_path)
        _reject_link_path(raw_lock)
        _reject_link_path(raw_epoch)
        self.lock_path = raw_lock.resolve()
        self.epoch_path = raw_epoch.resolve()
        self.lease_name = lease_name
        self.details = dict(details)
        if not NAME.fullmatch(lease_name):
            raise ValueError("process lease name is malformed")
        _validate_details(self.details)
        if self.lock_path == self.epoch_path:
            raise ValueError("process lease and epoch paths must differ")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        _reject_link_path(self.lock_path)
        _reject_link_path(self.epoch_path)
        self._descriptor: int | None = None
        self._handle: int | None = None
        self.owner: dict[str, Any] | None = None

    def _acquire_os_lock(self) -> None:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = _windows_kernel()
            create_file = kernel.CreateFileW
            handle = create_file(
                str(self.lock_path), 0xC0000000, 0x00000001, None, 4, 0x80, None
            )
            if handle == wintypes.HANDLE(-1).value:
                code = ctypes.get_last_error()
                if code in {32, 33}:
                    raise LeaseBusyError(
                        f"process lease {self.lease_name} is held by another process"
                    )
                raise ctypes.WinError(code)
            self._handle = int(handle)
            return
        import fcntl
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise LeaseBusyError(
                f"process lease {self.lease_name} is held by another process"
            ) from error
        self._descriptor = descriptor

    def _write_owner(self, content: bytes) -> None:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = _windows_kernel()
            ctypes.set_last_error(0)
            if kernel.SetFilePointer(self._handle, 0, None, 0) == 0xFFFFFFFF \
                    and ctypes.get_last_error() != 0:
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.SetEndOfFile(self._handle):
                raise ctypes.WinError(ctypes.get_last_error())
            written = wintypes.DWORD()
            buffer = ctypes.create_string_buffer(content)
            if (not kernel.WriteFile(self._handle, buffer, len(content),
                                     ctypes.byref(written), None)
                    or written.value != len(content)
                    or not kernel.FlushFileBuffers(self._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            return
        assert self._descriptor is not None
        os.ftruncate(self._descriptor, 0)
        os.lseek(self._descriptor, 0, os.SEEK_SET)
        offset = 0
        while offset < len(content):
            written = os.write(self._descriptor, content[offset:])
            if written <= 0:
                raise OSError("process lease owner metadata write made no progress")
            offset += written
        os.fsync(self._descriptor)

    def acquire(self) -> "ProcessFileLease":
        if self.owner is not None:
            raise RuntimeError("process lease is already acquired")
        self._acquire_os_lock()
        try:
            if self.epoch_path.exists():
                epoch = validate_epoch(_read_json(self.epoch_path, "process lease epoch")) + 1
            else:
                epoch = 1
            updated_at = utc_now()
            _atomic_json(self.epoch_path, {
                "schemaVersion": 1,
                "product": EPOCH_PRODUCT,
                "epoch": epoch,
                "updatedAt": updated_at,
            })
            self.owner = {
                "schemaVersion": 1,
                "product": LEASE_PRODUCT,
                "leaseName": self.lease_name,
                "leaseId": secrets.token_hex(16),
                "epoch": epoch,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquiredAt": updated_at,
                "details": self.details,
            }
            content = (json.dumps(
                self.owner, sort_keys=True, separators=(",", ":")
            ) + "\n").encode()
            self._write_owner(content)
            return self
        except Exception:
            self.release()
            raise

    @property
    def epoch(self) -> int:
        if self.owner is None:
            raise RuntimeError("process lease is not acquired")
        return self.owner["epoch"]

    def assert_current(self) -> None:
        if self.owner is None:
            raise LeaseFencedError("process lease is not acquired")
        current = validate_epoch(_read_json(self.epoch_path, "process lease epoch"))
        if current != self.owner["epoch"]:
            raise LeaseFencedError(
                f"process lease {self.lease_name} was fenced by epoch {current}"
            )

    def release(self) -> None:
        self.owner = None
        if os.name == "nt":
            if self._handle is not None:
                _windows_kernel().CloseHandle(self._handle)
                self._handle = None
            return
        if self._descriptor is not None:
            import fcntl
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self._descriptor)
                self._descriptor = None

    def __enter__(self) -> "ProcessFileLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


def _probe_active(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = _windows_kernel()
        create_file = kernel.CreateFileW
        handle = create_file(str(lock_path), 0xC0000000, 0x00000001,
                             None, 4, 0x80, None)
        if handle != wintypes.HANDLE(-1).value:
            kernel.CloseHandle(handle)
            return False
        code = ctypes.get_last_error()
        if code in {32, 33}:
            return True
        raise ctypes.WinError(code)
    import fcntl
    descriptor = os.open(
        lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def inspect_lease(lock_path: str | Path, epoch_path: str | Path,
                  lease_name: str) -> dict[str, Any]:
    if not NAME.fullmatch(lease_name):
        raise ValueError("process lease name is malformed")
    raw_lock = Path(lock_path)
    raw_epoch = Path(epoch_path)
    observed_at = utc_now()
    owner = None
    epoch = 0
    errors: list[str] = []
    path_safe = True
    try:
        _reject_link_path(raw_lock)
        _reject_link_path(raw_epoch)
        lock = raw_lock.resolve()
        epoch_file = raw_epoch.resolve()
    except ValueError as error:
        path_safe = False
        lock = raw_lock.absolute()
        epoch_file = raw_epoch.absolute()
        errors.append(str(error))
    if path_safe and epoch_file.exists():
        try:
            epoch = validate_epoch(_read_json(epoch_file, "process lease epoch"))
        except ValueError as error:
            errors.append(str(error))
    if path_safe and lock.exists():
        try:
            owner = validate_owner(_read_json(lock, "process lease owner"), lease_name)
            if owner["epoch"] != epoch:
                errors.append("lease owner epoch does not match durable epoch")
        except ValueError as error:
            errors.append(str(error))
    elif path_safe and epoch_file.exists():
        errors.append("durable lease epoch exists without owner evidence")
    if path_safe:
        try:
            active = _probe_active(lock)
        except OSError as error:
            active = False
            errors.append(f"lease activity probe failed: {error}")
    else:
        active = False
    if active and owner is None:
        errors.append("active lease lacks valid owner metadata")
    return {
        "schemaVersion": 1,
        "product": STATUS_PRODUCT,
        "leaseName": lease_name,
        "active": active,
        "healthy": not errors,
        "epoch": epoch,
        "owner": owner,
        "error": "; ".join(errors) if errors else None,
        "observedAt": observed_at,
    }


def status_command(args: argparse.Namespace) -> int:
    report = inspect_lease(args.lock, args.epoch, args.lease_name)
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(report_path, report)
    passed = report["healthy"] and (not args.require_free or not report["active"])
    marker = "PASS" if passed else "ERROR"
    stream = sys.stdout if passed else sys.stderr
    print(
        f"PDR_PROCESS_FILE_LEASE_STATUS_{marker} "
        f"name={report['leaseName']} active={str(report['active']).lower()} "
        f"healthy={str(report['healthy']).lower()} epoch={report['epoch']}",
        file=stream,
    )
    return 0 if passed else 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    status = commands.add_parser(
        "status", help="inspect one OS-owned process lease without acquiring it"
    )
    status.add_argument("--lock", required=True)
    status.add_argument("--epoch", required=True)
    status.add_argument("--lease-name", required=True)
    status.add_argument("--report")
    status.add_argument("--require-free", action="store_true")
    status.set_defaults(handler=status_command)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        return args.handler(args)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_PROCESS_FILE_LEASE_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
