#!/usr/bin/env python3
"""PocoDDSRuntime developer command line tools."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


KINDS = ("service", "device", "workflow")


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
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED)
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
    root = Path(args.root).resolve()
    checks = [
        ("repository", (root / "CMakeLists.txt").is_file() and (root / "application").is_dir()),
        ("cmake", shutil.which("cmake") is not None or (Path("C:/Qt/Tools/CMake_64/bin/cmake.exe")).is_file()),
        ("python", sys.version_info >= (3, 9)),
        ("dependency-prefix", (root / "build/install/cmake/PocoConfig.cmake").is_file()),
        ("sdk-package", (root / "build/PocoDDSRuntimeConfig.cmake").is_file()),
    ]
    for label, passed in checks:
        print(f"[{'OK' if passed else 'FAIL'}] {label}")
    failed = [label for label, passed in checks if not passed]
    if failed:
        print("doctor found missing requirements: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


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
    check.add_argument("--root", default=Path(__file__).resolve().parents[1])
    check.set_defaults(handler=doctor)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
