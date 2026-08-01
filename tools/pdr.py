#!/usr/bin/env python3
"""PocoDDSRuntime developer command line tools."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


KINDS = ("service", "device", "workflow")


def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_install_prefix(root: Path | None = None) -> Path:
    candidate = (root or tool_root()).resolve()
    installed_package = candidate / "lib" / "cmake" / "PocoDDSRuntime"
    return candidate if installed_package.is_dir() else candidate / "build" / "install"


def valid_name(value: str) -> str:
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", value):
        raise argparse.ArgumentTypeError(
            "name must be PascalCase and contain only ASCII letters and digits"
        )
    return value


def templates(kind: str, name: str) -> dict[str, str]:
    namespace = f"PocoDDS::Generated::{name}"
    common_cmake = f'''cmake_minimum_required(VERSION 3.24)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project({name} LANGUAGES CXX)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)
    include(CTest)
endif()

add_library({name} src/{name}.cpp)
target_include_directories({name} PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries({name} PUBLIC PocoDDS::SDK)

if(BUILD_TESTING)
    add_executable({name}Smoke tests/{name}Smoke.cpp)
    target_link_libraries({name}Smoke PRIVATE {name})
    add_test(NAME {name.lower()}-smoke COMMAND {name}Smoke)
endif()
'''
    if kind == "workflow":
        header = f'''#pragma once

#include <PocoDDS/Application/Application.h>

namespace {namespace}
{{
class {name} final : public PocoDDS::Application::IWorkflow
{{
public:
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>
        start(const PocoDDS::Application::CommandContext& context) override;
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>
        handle(const PocoDDS::Application::WorkflowEvent& event) override;
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>
        cancel(const PocoDDS::Application::CommandContext& context) override;
    [[nodiscard]] PocoDDS::Application::WorkflowState state() const noexcept override;

private:
    PocoDDS::Application::WorkflowState _state{{PocoDDS::Application::WorkflowState::idle}};
}};
}}
'''
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
using PocoDDS::Application::Result;
using PocoDDS::Application::WorkflowState;

Result<WorkflowState> {name}::start(const PocoDDS::Application::CommandContext& context)
{{
    if (context.expired())
        return Result<WorkflowState>::failure({{"deadline_exceeded", "workflow deadline expired", false}});
    _state = WorkflowState::succeeded;
    return Result<WorkflowState>::success(_state);
}}

Result<WorkflowState> {name}::handle(const PocoDDS::Application::WorkflowEvent&)
{{
    return Result<WorkflowState>::success(_state);
}}

Result<WorkflowState> {name}::cancel(const PocoDDS::Application::CommandContext&)
{{
    _state = WorkflowState::cancelled;
    return Result<WorkflowState>::success(_state);
}}

WorkflowState {name}::state() const noexcept {{ return _state; }}
}}
'''
        smoke_body = f'''{namespace}::{name} component;
    PocoDDS::Application::CommandContext context;
    return component.start(context) ? 0 : 1;'''
    elif kind == "device":
        header = f'''#pragma once

#include <PocoDDS/Devices/Device.h>

#include <mutex>
#include <string>

namespace {namespace}
{{
class {name} final : public PocoDDS::Devices::Device,
                     public PocoDDS::Devices::DiagnosticDevice
{{
public:
    explicit {name}(std::string id);

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    PocoDDS::Devices::DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;
    PocoDDS::Devices::DeviceDiagnostics diagnostics() const override;

private:
    PocoDDS::Devices::DeviceSnapshot snapshotUnlocked() const;

    std::string _id;
    std::string _type{{"{name}"}};
    mutable std::mutex _mutex;
    PocoDDS::Devices::DeviceState _state{{PocoDDS::Devices::DeviceState::offline}};
    std::uint64_t _sequence{{0}};
    SnapshotHandler _handler;
    PocoDDS::Devices::DeviceDiagnostics _diagnostics;
}};
}}
'''
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

#include <chrono>
#include <stdexcept>
#include <utility>

namespace {namespace}
{{
namespace
{{
std::int64_t nowMicroseconds()
{{
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}}
}}

{name}::{name}(std::string id) : _id(std::move(id))
{{
    if (_id.empty()) throw std::invalid_argument("device id must not be empty");
}}

const std::string& {name}::id() const noexcept {{ return _id; }}
const std::string& {name}::type() const noexcept {{ return _type; }}

void {name}::start()
{{
    SnapshotHandler handler;
    PocoDDS::Devices::DeviceSnapshot current;
    {{
        std::lock_guard lock(_mutex);
        _state = PocoDDS::Devices::DeviceState::ready;
        ++_sequence;
        current = snapshotUnlocked();
        handler = _handler;
    }}
    if (handler) handler(current);
}}

void {name}::stop() noexcept
{{
    std::lock_guard lock(_mutex);
    _state = PocoDDS::Devices::DeviceState::offline;
}}

PocoDDS::Devices::DeviceSnapshot {name}::snapshot() const
{{
    std::lock_guard lock(_mutex);
    return snapshotUnlocked();
}}

PocoDDS::Devices::DeviceSnapshot {name}::snapshotUnlocked() const
{{
    return {{_id, _type, _state, _sequence, nowMicroseconds(), "{{}}"}};
}}

std::string {name}::execute(const std::string& operation, const std::string& payload)
{{
    SnapshotHandler handler;
    PocoDDS::Devices::DeviceSnapshot current;
    std::string result;
    {{
        std::lock_guard lock(_mutex);
        if (_state != PocoDDS::Devices::DeviceState::ready)
            throw std::runtime_error("device is not ready");
        if (operation != "ping")
            throw std::invalid_argument("unsupported device operation: " + operation);
        result = payload.empty() ? "pong" : payload;
        ++_sequence;
        ++_diagnostics.successfulOperations;
        _diagnostics.consecutiveFailures = 0;
        _diagnostics.lastSuccessMicroseconds = nowMicroseconds();
        _diagnostics.lastError.clear();
        current = snapshotUnlocked();
        handler = _handler;
    }}
    if (handler) handler(current);
    return result;
}}

void {name}::setSnapshotHandler(SnapshotHandler handler)
{{
    std::lock_guard lock(_mutex);
    _handler = std::move(handler);
}}

PocoDDS::Devices::DeviceDiagnostics {name}::diagnostics() const
{{
    std::lock_guard lock(_mutex);
    return _diagnostics;
}}
}}
'''
        smoke_body = f'''{namespace}::{name} device("{name.lower()}-1");
    device.start();
    const auto snapshot = device.snapshot();
    const bool passed = snapshot.id == "{name.lower()}-1" &&
        snapshot.state == PocoDDS::Devices::DeviceState::ready &&
        device.execute("ping", "") == "pong" &&
        device.diagnostics().successfulOperations == 1;
    device.stop();
    return passed ? 0 : 1;'''
    else:
        header = f'''#pragma once

#include <string_view>

namespace {namespace}
{{
class {name}
{{
public:
    [[nodiscard]] std::string_view name() const noexcept;
    [[nodiscard]] bool ready() const noexcept;
}};
}}
'''
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
std::string_view {name}::name() const noexcept {{ return "{name}"; }}
bool {name}::ready() const noexcept {{ return true; }}
}}
'''
        smoke_body = f'''{namespace}::{name} component;
    return component.ready() ? 0 : 1;'''
    smoke = f'''#include <PocoDDS/Generated/{name}/{name}.h>

int main()
{{
    {smoke_body}
}}
'''
    device_notes = f'''\n## Runtime configuration

Register the adapter from an OSP bundle and use indexed configuration so multiple
instances can coexist:

```properties
pdr.{name.lower()}.count = 1
pdr.{name.lower()}.0.id = {name.lower()}-1
pdr.{name.lower()}.0.enabled = true
```
''' if kind == "device" else ""
    readme = f'''# {name}

Generated PocoDDSRuntime {kind} module.

## Integration

Add `add_subdirectory(<module-path>)` to the owning product CMake file. The module
uses only the public `PocoDDS::SDK` target and includes a smoke test.

Before integration, verify the module against an installed SDK in an isolated build:

```text
pdr verify . --prefix <install-prefix> --config Release
```

Add `--report verify-report.json` to retain configure, build and CTest evidence.
{device_notes}
'''
    return {
        "CMakeLists.txt": common_cmake,
        f"include/PocoDDS/Generated/{name}/{name}.h": header,
        f"src/{name}.cpp": source,
        f"tests/{name}Smoke.cpp": smoke,
        "README.md": readme,
    }


def create_module(args: argparse.Namespace) -> int:
    destination = Path(args.output).resolve() / args.name
    if destination.exists() and any(destination.iterdir()) and not args.force:
        print(f"error: destination is not empty: {destination}", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=True)
    for relative, content in templates(args.kind, args.name).items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.force:
            print(f"error: file already exists: {path}", file=sys.stderr)
            return 2
        path.write_text(content, encoding="utf-8", newline="\n")
    print(f"created {args.kind} module: {destination}")
    return 0


def doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else tool_root()
    prefix = Path(args.prefix).resolve() if args.prefix else default_install_prefix(root)
    checks: list[dict[str, object]] = []

    def add(identifier: str, passed: bool, detail: str, remedy: str = "") -> None:
        check: dict[str, object] = {"id": identifier, "passed": passed, "detail": detail}
        if remedy and not passed:
            check["remedy"] = remedy
        checks.append(check)

    source_layout = (root / "CMakeLists.txt").is_file() and (root / "application").is_dir()
    installed_layout = (prefix / "lib" / "cmake" / "PocoDDSRuntime").is_dir()
    layout = "source" if source_layout else "installed" if installed_layout else "unknown"
    add(
        "layout", source_layout or installed_layout, f"{layout}: root={root}; prefix={prefix}",
        "pass --root for a source tree or --prefix for an installed PocoDDSRuntime package",
    )
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    add("python", sys.version_info >= (3, 9), python_version, "install Python 3.9 or newer")
    try:
        cmake = executable(args.cmake, "cmake")
        version_result = subprocess.run(
            [cmake, "--version"], text=True, capture_output=True, check=False
        )
        match = re.search(r"cmake version (\d+)\.(\d+)\.(\d+)", version_result.stdout)
        version = tuple(int(part) for part in match.groups()) if match else (0, 0, 0)
        add(
            "cmake", version_result.returncode == 0 and version >= (3, 24, 0),
            f"{cmake} ({'.'.join(map(str, version))})",
            "install CMake 3.24 or newer or pass --cmake",
        )
    except (FileNotFoundError, OSError) as error:
        add("cmake", False, str(error), "install CMake 3.24 or newer or pass --cmake")
    try:
        ctest = executable(args.ctest, "ctest")
        add("ctest", True, ctest)
    except (FileNotFoundError, OSError) as error:
        add("ctest", False, str(error), "install CTest or pass --ctest")

    package_dir = prefix / "lib" / "cmake" / "PocoDDSRuntime"
    config = package_dir / "PocoDDSRuntimeConfig.cmake"
    targets = package_dir / "PocoDDSRuntimeTargets.cmake"
    poco = prefix / "cmake" / "PocoConfig.cmake"
    add(
        "sdk-package", config.is_file(), str(config),
        "install PocoDDSRuntime to the selected --prefix",
    )
    targets_content = targets.read_text(encoding="utf-8", errors="replace") if targets.is_file() else ""
    add(
        "sdk-target", "add_library(PocoDDS::SDK" in targets_content, str(targets),
        "reinstall an SDK package that exports PocoDDS::SDK",
    )
    add(
        "poco-package", poco.is_file(), str(poco),
        "install Poco dependencies to the selected --prefix",
    )

    for check in checks:
        print(f"[{'OK' if check['passed'] else 'FAIL'}] {check['id']}: {check['detail']}")
        if not check["passed"] and "remedy" in check:
            print(f"       fix: {check['remedy']}")
    failed = [str(check["id"]) for check in checks if not check["passed"]]
    report = {
        "schemaVersion": 1,
        "root": str(root),
        "prefix": str(prefix),
        "passed": not failed,
        "checks": checks,
    }
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    if failed:
        print("doctor found missing requirements: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def executable(value: str | None, name: str) -> str:
    if value:
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{name} executable not found: {path}")
        return str(path)
    discovered = shutil.which(name)
    if discovered:
        return discovered
    qt_candidate = Path(f"C:/Qt/Tools/CMake_64/bin/{name}.exe")
    if qt_candidate.is_file():
        return str(qt_candidate)
    raise FileNotFoundError(f"{name} executable not found; pass --{name}")


def run_stage(name: str, command: list[str]) -> dict[str, object]:
    started = datetime.now(timezone.utc)
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "startedAt": started.isoformat(),
        "command": command,
        "exitCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0,
    }


def verify_module(args: argparse.Namespace) -> int:
    module = Path(args.module).resolve()
    report_path = Path(args.report).resolve() if args.report else None
    report: dict[str, object] = {
        "schemaVersion": 1,
        "module": str(module),
        "configuration": args.config,
        "passed": False,
        "stages": [],
    }
    result = 1
    try:
        if not (module / "CMakeLists.txt").is_file():
            raise FileNotFoundError(f"module CMakeLists.txt not found: {module}")
        cmake = executable(args.cmake, "cmake")
        ctest = executable(args.ctest, "ctest")
        prefixes = [str(Path(item).resolve()) for item in args.prefix]
        if not prefixes:
            prefixes.append(str(default_install_prefix()))
        with tempfile.TemporaryDirectory(prefix="pdr-verify-") as temporary:
            build = Path(temporary) / "build"
            configure = [cmake, "-S", str(module), "-B", str(build)]
            if args.generator:
                configure.extend(["-G", args.generator])
            if args.platform:
                configure.extend(["-A", args.platform])
            if prefixes:
                configure.append("-DCMAKE_PREFIX_PATH=" + ";".join(prefixes))
            poco_dir = Path(args.poco_dir).resolve() if args.poco_dir else next(
                (Path(prefix) / "cmake" for prefix in prefixes
                 if (Path(prefix) / "cmake" / "PocoConfig.cmake").is_file()),
                None,
            )
            if poco_dir:
                configure.append("-DPoco_DIR=" + str(poco_dir))
                report["pocoDir"] = str(poco_dir)
            commands = [
                ("configure", configure),
                ("build", [cmake, "--build", str(build), "--config", args.config]),
                ("test", [ctest, "--test-dir", str(build), "-C", args.config,
                          "--output-on-failure"]),
            ]
            for stage_name, command in commands:
                stage = run_stage(stage_name, command)
                report["stages"].append(stage)  # type: ignore[union-attr]
                if not stage["passed"]:
                    print(stage["stdout"], end="", file=sys.stderr)
                    print(stage["stderr"], end="", file=sys.stderr)
                    print(f"verify failed during {stage_name}", file=sys.stderr)
                    result = 2
                    break
            else:
                report["passed"] = True
                result = 0
                print(f"verified module: {module}")
    except (FileNotFoundError, OSError) as error:
        report["error"] = str(error)
        print(f"verify failed: {error}", file=sys.stderr)
        result = 2
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return result


def validate_config(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix).resolve() if args.prefix else default_install_prefix()
    default_name = "pdr-config-check.exe" if sys.platform == "win32" else "pdr-config-check"
    checker = Path(args.executable).resolve() if args.executable else prefix / "bin" / default_name
    configurations = [Path(item).resolve() for item in args.configuration]
    report = {
        "schemaVersion": 1,
        "executable": str(checker),
        "configurationFiles": [str(item) for item in configurations],
        "passed": False,
    }
    result = 2
    if not checker.is_file():
        report["error"] = f"configuration checker not found: {checker}"
        print(f"config validation failed: {report['error']}", file=sys.stderr)
    else:
        completed = subprocess.run(
            [str(checker), *(str(item) for item in configurations)],
            text=True,
            capture_output=True,
            check=False,
        )
        report.update({
            "exitCode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "passed": completed.returncode == 0,
        })
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        result = completed.returncode
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="pdr", description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="create a framework module")
    new.add_argument("kind", choices=KINDS)
    new.add_argument("name", type=valid_name)
    new.add_argument("--output", default="generated")
    new.add_argument("--force", action="store_true")
    new.set_defaults(handler=create_module)
    check = commands.add_parser("doctor", help="check the local development environment")
    check.add_argument("--root")
    check.add_argument("--prefix", help="installed PocoDDSRuntime/dependency prefix")
    check.add_argument("--cmake")
    check.add_argument("--ctest")
    check.add_argument("--report")
    check.set_defaults(handler=doctor)
    verify = commands.add_parser("verify", help="configure, build and test a generated module")
    verify.add_argument("module")
    verify.add_argument("--prefix", action="append", default=[],
                        help="SDK/dependency install prefix; may be repeated")
    verify.add_argument("--poco-dir", help="directory containing PocoConfig.cmake")
    verify.add_argument("--config", default="Release")
    verify.add_argument("--generator")
    verify.add_argument("--platform")
    verify.add_argument("--cmake")
    verify.add_argument("--ctest")
    verify.add_argument("--report")
    verify.set_defaults(handler=verify_module)
    config_check = commands.add_parser(
        "validate-config", help="validate layered Runtime configuration without starting services"
    )
    config_check.add_argument("configuration", nargs="+")
    config_check.add_argument("--prefix", help="installed PocoDDSRuntime prefix")
    config_check.add_argument("--executable", help="pdr-config-check executable")
    config_check.add_argument("--report")
    config_check.set_defaults(handler=validate_config)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
