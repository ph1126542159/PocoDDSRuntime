#!/usr/bin/env python3
"""Version and transactionally upgrade generated component scaffolding."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable

import project_template


TEMPLATE_ID = "pdr-component"
CURRENT_TEMPLATE_VERSION = 9
SUPPORTED_TEMPLATE_VERSIONS = {1, 2, 3, 4, 5, 6, 7, 8, 9}
COMPONENT_KINDS = {
    "module", "service", "device", "workflow", "bundle", "plugin", "subprocess",
    "robot-module", "robot-hardware-adapter", "robot-simulation-adapter",
    "robot-process", "ros2-node",
}
COMPONENT_NAME = re.compile(r"[A-Z][A-Za-z0-9]*")
STATE_PATH = Path(".pdr-component.json")
COLLABORATION_CONTRACT_PATH = Path("pdr-component.json")
BaseRenderer = Callable[[str, str], dict[str, str]]


def component_slug(name: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "-", name).replace("_", "-").lower()
    return re.sub(r"[^a-z0-9-]+", "-", value).strip("-")


def component_contract(kind: str, name: str) -> dict[str, Any]:
    slug = component_slug(name)
    target_by_kind = {
        "module": f"pdr_generated_module_{slug.replace('-', '_')}",
        "service": f"pdr_generated_service_{slug.replace('-', '_')}",
        "device": f"pdr_generated_device_{slug.replace('-', '_')}",
        "workflow": f"pdr_generated_workflow_{slug.replace('-', '_')}",
        "bundle": f"pdr_generated_bundle_{slug.replace('-', '_')}_core",
        "plugin": f"pdr_generated_plugin_{slug.replace('-', '_')}_core",
        "subprocess": f"pdr_generated_subprocess_{slug.replace('-', '_')}",
        "robot-module": f"pdr_robot_module_{slug.replace('-', '_')}_core",
        "robot-hardware-adapter": f"pdr_robot_hardware_adapter_{slug.replace('-', '_')}",
        "robot-simulation-adapter": f"pdr_robot_simulation_adapter_{slug.replace('-', '_')}",
        "robot-process": f"pdr_robot_process_{slug.replace('-', '_')}",
        "ros2-node": f"{slug.replace('-', '_')}_node",
    }
    plane_by_kind = {
        "module": "application", "service": "application",
        "device": "management", "workflow": "management",
        "bundle": "management", "plugin": "management",
        "subprocess": "isolated",
        "robot-module": "robotics", "robot-hardware-adapter": "robotics",
        "robot-simulation-adapter": "robotics", "robot-process": "isolated",
        "ros2-node": "external",
    }
    isolation_by_kind = {
        "bundle": "bundle", "plugin": "bundle",
        "subprocess": "subprocess", "robot-process": "subprocess",
        "ros2-node": "external-process",
    }
    return {
        "schemaVersion": 1,
        "id": slug,
        "name": name,
        "kind": kind,
        "plane": plane_by_kind[kind],
        "target": target_by_kind[kind],
        "owner": "project",
        "isolation": isolation_by_kind.get(kind, "in-process"),
        "requires": [],
    }


def default_base_renderer(kind: str, name: str) -> dict[str, str]:
    """Load the sibling CLI's frozen v1 renderer without relying on PYTHONPATH."""
    path = Path(__file__).resolve().with_name("pdr.py")
    spec = importlib.util.spec_from_file_location("pdr_component_frozen_renderer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen component renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.templates(kind, name)


def managed_path(path: str) -> bool:
    candidate = Path(path)
    return (
        candidate.name in {"CMakeLists.txt", "README.md", "package.xml"}
        or candidate.suffix == ".bndlspec"
    )


def render_component_template(kind: str, name: str, base_renderer: BaseRenderer,
                              version: int) -> dict[str, str]:
    if version not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported component template version: {version}")
    rendered = dict(base_renderer(kind, name))
    if version == 1:
        return rendered
    for path, content in list(rendered.items()):
        if Path(path).name != "CMakeLists.txt":
            continue
        lines = content.splitlines(keepends=True)
        if not lines or not lines[0].startswith("cmake_minimum_required("):
            raise ValueError(f"component template CMake entry has no minimum version: {path}")
        lines.insert(1, f"set(PDR_COMPONENT_TEMPLATE_VERSION {version})\n")
        rendered[path] = "".join(lines)
    if version >= 3 and kind in {"module", "service"}:
        cmake = rendered["CMakeLists.txt"]
        legacy_package = "find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)"
        if legacy_package not in cmake or "PocoDDS::SDK" not in cmake:
            raise ValueError(f"{kind} scaffold no longer matches the version-3 migration")
        rendered["CMakeLists.txt"] = cmake.replace(
            legacy_package, "find_package(PDRRuntimeCore 0.1 CONFIG REQUIRED)"
        ).replace("PocoDDS::SDK", "PocoDDS::RuntimeCore")
    if version >= 4:
        rendered["pdr-component.json"] = (
            json.dumps(component_contract(kind, name), indent=2, ensure_ascii=False) + "\n"
        )
    if "README.md" in rendered:
        rendered["README.md"] = rendered["README.md"].rstrip() + f'''

## Component template lifecycle

This component uses `{TEMPLATE_ID}` version {version}. Framework-owned build metadata can
be checked with `pdr component status . --check` and upgraded with
`pdr component upgrade .`. Files under `src/`, `include/`, `tests/`, `launch/` and
`config/` remain product-owned and are never overwritten by template upgrades.
'''
    if version >= 3 and kind in {"module", "service"}:
        rendered["README.md"] = rendered["README.md"].replace(
            "uses only the public `PocoDDS::SDK` target",
            "uses only the transport-neutral `PocoDDS::RuntimeCore` target",
        ).replace(
            "installed SDK in an isolated build",
            "installed RuntimeCore package in an isolated build",
        )
    if version >= 4:
        rendered["README.md"] = rendered["README.md"].rstrip() + '''

## Collaboration contract

`pdr-component.json` is the product-owned component boundary. Keep `id`, `kind`,
`target`, `plane`, `isolation`, `owner` and `requires` accurate. Project validation
rejects duplicate IDs/targets, dependency cycles, undeclared component links and
dependencies that cross the allowed Module/Service/Bundle/Subprocess direction.
'''
    if version >= 5 and kind == "device":
        slug = component_slug(name)
        snake = slug.replace("-", "_")
        target = f"pdr_generated_device_{snake}"
        package = "find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)"
        if package not in rendered["CMakeLists.txt"]:
            raise ValueError("device scaffold no longer matches the version-5 migration")
        rendered["CMakeLists.txt"] = rendered["CMakeLists.txt"].replace(
            package,
            "find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK Plugins)",
        ) + f'''\n# Product-owned registration Bundle. It starts before DeviceGateway and
# publishes a DeviceFactoryService; the Gateway owns runtime lifecycle.
pdr_add_osp_bundle({target}_factory_bundle
    SYMBOLIC_NAME pdr.device.factory.{slug}
    BUNDLE_SPEC ${{CMAKE_CURRENT_SOURCE_DIR}}/{name}Factory.bndlspec
    SOURCES ${{CMAKE_CURRENT_SOURCE_DIR}}/src/FactoryBundleActivator.cpp
    LINK_LIBS {target} PocoDDS::GatewayAPI
    INCLUDE_DIRS ${{CMAKE_CURRENT_SOURCE_DIR}}/include)

install(DIRECTORY "${{{target}_factory_bundle_BUNDLE_DIRECTORY}}/"
    DESTINATION bin/bundles FILES_MATCHING PATTERN "*.bndl")
'''
        rendered["src/FactoryBundleActivator.cpp"] = f'''#include <PocoDDS/Generated/{name}/{name}.h>
#include <PocoDDS/Gateways/FactoryService.h>

#include <Poco/ClassLibrary.h>
#include <Poco/AutoPtr.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

#include <memory>

namespace PocoDDS::Generated::{name}
{{
class Factory final : public PocoDDS::Gateways::DeviceFactoryService
{{
public:
    PocoDDS::Gateways::FactoryDescriptor descriptor() const override
    {{
        return {{"{slug}", "pdr.{name.lower()}", "{slug}", false, 0}};
    }}

    std::unique_ptr<PocoDDS::Devices::Device> create(
        const Poco::Util::AbstractConfiguration&,
        const PocoDDS::Gateways::FactoryInstance& instance) const override
    {{
        return std::make_unique<{name}>(instance.id);
    }}
}};

class FactoryBundleActivator final : public Poco::OSP::BundleActivator
{{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {{
        _factory = new Factory;
        Poco::OSP::Properties properties;
        properties.set(PocoDDS::Gateways::DeviceFactoryService::PROPERTY_KIND,
                       PocoDDS::Gateways::DeviceFactoryService::FACTORY_KIND);
        properties.set(PocoDDS::Gateways::DeviceFactoryService::PROPERTY_TYPE,
                       "{slug}");
        _reference = context->registry().registerService(
            "pdr.deviceFactory.{slug}", _factory, properties);
    }}

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {{
        if (_reference) context->registry().unregisterService(_reference);
        _reference.reset();
        _factory.reset();
    }}

private:
    Poco::AutoPtr<Factory> _factory;
    Poco::OSP::ServiceRef::Ptr _reference;
}};
}}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Generated::{name}::FactoryBundleActivator)
POCO_END_MANIFEST
'''
        rendered[f"{name}Factory.bndlspec"] = f'''<?xml version="1.0"?>
<bundlespec>
  <manifest>
    <name>{name} Device Factory</name>
    <symbolicName>pdr.device.factory.{slug}</symbolicName>
    <version>1.0.0</version>
    <vendor>Generated with PocoDDSRuntime</vendor>
    <pluginApi>${{pdrPluginApi}}</pluginApi>
    <pluginAbi>${{pdrPluginAbi}}</pluginAbi>
    <pluginAbiFingerprint>${{pdrPluginAbiFingerprint}}</pluginAbiFingerprint>
    <runtimeVersion>${{pdrRuntimeRange}}</runtimeVersion>
    <activator>
      <class>PocoDDS::Generated::{name}::FactoryBundleActivator</class>
      <library>pdr.device.factory.{slug}</library>
    </activator>
    <lazyStart>false</lazyStart>
    <runLevel>090</runLevel>
    <requiredBundles>
      <bundle><symbolicName>osp.core</symbolicName><version>[1.0.0,2.0.0)</version></bundle>
    </requiredBundles>
  </manifest>
  <code>
    ${{bin}}/*.dll,
    ${{bin}}/*.pdb,
    bin/${{osName}}/${{osArch}}/*.so,
    bin/${{osName}}/${{osArch}}/*.dylib
  </code>
</bundlespec>
'''
        rendered["README.md"] += f'''\n## Factory Bundle

The generated `pdr.device.factory.{slug}` Bundle registers this implementation at
run level 090. `pdr.device.gateway` discovers it at run level 100, so adding this
device does not require editing framework Gateway sources. Keep the provider
Bundle active for the complete lifetime of every created device instance.
'''
    if version >= 6 and kind == "workflow":
        slug = component_slug(name)
        snake = slug.replace("-", "_")
        target = f"pdr_generated_workflow_{snake}"
        package = "find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)"
        if package not in rendered["CMakeLists.txt"]:
            raise ValueError("workflow scaffold no longer matches the version-6 migration")
        rendered["CMakeLists.txt"] = rendered["CMakeLists.txt"].replace(
            package,
            "find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK Plugins WorkflowAPI)",
        ).replace(
            f"target_link_libraries({target} PUBLIC PocoDDS::SDK)",
            f"target_link_libraries({target} PUBLIC PocoDDS::SDK PocoDDS::WorkflowAPI)\n"
            f"set_target_properties({target} PROPERTIES POSITION_INDEPENDENT_CODE ON)",
        ) + f'''\n# Product-owned definition provider. WorkflowRuntime discovers this Bundle
# through registry properties; no framework source registration is required.
pdr_add_osp_bundle({target}_provider_bundle
    SYMBOLIC_NAME pdr.workflow.definition.{slug}
    BUNDLE_SPEC ${{CMAKE_CURRENT_SOURCE_DIR}}/{name}Workflow.bndlspec
    SOURCES ${{CMAKE_CURRENT_SOURCE_DIR}}/src/WorkflowBundleActivator.cpp
    LINK_LIBS {target} PocoDDS::WorkflowAPI
    INCLUDE_DIRS ${{CMAKE_CURRENT_SOURCE_DIR}}/include)

install(DIRECTORY "${{{target}_provider_bundle_BUNDLE_DIRECTORY}}/"
    DESTINATION bin/bundles FILES_MATCHING PATTERN "*.bndl")
'''
        rendered["src/WorkflowBundleActivator.cpp"] = f'''#include <PocoDDS/Generated/{name}/{name}.h>
#include <PocoDDS/Workflow/WorkflowDefinitionService.h>

#include <Poco/ClassLibrary.h>
#include <Poco/AutoPtr.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

#include <chrono>

namespace PocoDDS::Generated::{name}
{{
class Definition final : public PocoDDS::Workflow::WorkflowDefinitionService
{{
public:
    PocoDDS::Workflow::DefinitionDescriptor descriptor() const override
    {{
        return {{"{slug}", "1.0.0", {{"execute"}}, 3}};
    }}

    PocoDDS::Workflow::StepResult execute(
        const std::string& step,
        const PocoDDS::Workflow::StepContext& context) override
    {{
        if (step != "execute")
            return PocoDDS::Workflow::StepResult::failed(
                "unknown-step", "unsupported workflow step: " + step);
        PocoDDS::Application::CommandContext command;
        command.requestId = context.instanceId;
        auto result = {name}().start(command);
        if (result) return PocoDDS::Workflow::StepResult::completed();
        const auto& error = result.error();
        return error.retryable
            ? PocoDDS::Workflow::StepResult::retryAfter(
                  std::chrono::seconds(1), error.code, error.message)
            : PocoDDS::Workflow::StepResult::failed(error.code, error.message);
    }}

    void compensate(const std::string& step,
                    const PocoDDS::Workflow::StepContext& context) override
    {{
        if (step != "execute") return;
        PocoDDS::Application::CommandContext command;
        command.requestId = context.instanceId;
        static_cast<void>({name}().cancel(command));
    }}
}};

class WorkflowBundleActivator final : public Poco::OSP::BundleActivator
{{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {{
        _definition = new Definition;
        Poco::OSP::Properties properties;
        properties.set(PocoDDS::Workflow::WorkflowDefinitionService::PROPERTY_KIND,
                       PocoDDS::Workflow::WorkflowDefinitionService::PROVIDER_KIND);
        properties.set(PocoDDS::Workflow::WorkflowDefinitionService::PROPERTY_TYPE,
                       "{slug}");
        _reference = context->registry().registerService(
            "pdr.workflow.definition.{slug}", _definition, properties);
    }}

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {{
        if (_reference) context->registry().unregisterService(_reference);
        _reference.reset();
        _definition.reset();
    }}

private:
    Poco::AutoPtr<Definition> _definition;
    Poco::OSP::ServiceRef::Ptr _reference;
}};
}} // namespace PocoDDS::Generated::{name}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Generated::{name}::WorkflowBundleActivator)
POCO_END_MANIFEST
'''
        rendered[f"{name}Workflow.bndlspec"] = f'''<?xml version="1.0"?>
<bundlespec>
  <manifest>
    <name>{name} Workflow Definition</name>
    <symbolicName>pdr.workflow.definition.{slug}</symbolicName>
    <version>1.0.0</version>
    <vendor>Generated with PocoDDSRuntime</vendor>
    <pluginApi>${{pdrPluginApi}}</pluginApi>
    <pluginAbi>${{pdrPluginAbi}}</pluginAbi>
    <pluginAbiFingerprint>${{pdrPluginAbiFingerprint}}</pluginAbiFingerprint>
    <runtimeVersion>${{pdrRuntimeRange}}</runtimeVersion>
    <activator>
      <class>PocoDDS::Generated::{name}::WorkflowBundleActivator</class>
      <library>pdr.workflow.definition.{slug}</library>
    </activator>
    <lazyStart>false</lazyStart>
    <runLevel>110</runLevel>
    <requiredBundles>
      <bundle><symbolicName>osp.core</symbolicName><version>[1.0.0,2.0.0)</version></bundle>
    </requiredBundles>
  </manifest>
  <code>
    ${{bin}}/*.dll,
    ${{bin}}/*.pdb,
    bin/${{osName}}/${{osArch}}/*.so,
    bin/${{osName}}/${{osArch}}/*.dylib
  </code>
</bundlespec>
'''
        rendered["README.md"] += f'''\n## Persistent provider Bundle

The generated `pdr.workflow.definition.{slug}` Bundle registers this Application
workflow through `WorkflowDefinitionService` at run level 110. The independent
Workflow Runtime discovers it dynamically and owns persistence, business-key
idempotency, retry, recovery and compensation checkpoints. No framework source
registration is required.

The compatibility adapter exposes the existing Application workflow as one durable
`execute` step. For a multi-step process, evolve `Definition::descriptor`, `execute`
and `compensate` in `src/WorkflowBundleActivator.cpp`; keep external side effects
idempotent because recovery provides at-least-once callback delivery.
'''
    if version >= 7 and kind in {"bundle", "plugin"}:
        slug = component_slug(name)
        symbolic = f"pdr.plugin.{name.lower()}"
        target_stem = f"pdr_generated_{kind}_{slug.replace('-', '_')}"
        cmake_test = (
            f"    add_test(NAME {kind}-{name.lower()}-smoke "
            f"COMMAND {target_stem}_smoke)\n"
            "endif()\n"
        )
        if cmake_test not in rendered["CMakeLists.txt"]:
            raise ValueError(f"{kind} scaffold no longer matches version-7 testing migration")
        rendered["CMakeLists.txt"] = rendered["CMakeLists.txt"].replace(
            cmake_test,
            cmake_test.replace(
                "endif()\n",
                f'''    pdr_add_component_contract_test(
        NAME {kind}-{name.lower()}-contract
        COMPONENT ${{CMAKE_CURRENT_SOURCE_DIR}}/pdr-component.json
        SERVICE_CONTRACT ${{CMAKE_CURRENT_SOURCE_DIR}}/bundle/service-contracts.json)
endif()
''',
            ),
        )
        rendered["bundle/service-contracts.json"] = json.dumps(
            {
                "schemaVersion": 1,
                "provides": [{
                    "contract": f"{symbolic}.status",
                    "version": "1.0.0",
                    "serviceName": f"{symbolic}.status",
                }],
                "requires": [],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        specification = rendered[f"{name}.bndlspec"]
        if "  <code>\n" not in specification:
            raise ValueError(f"{kind} Bundle spec no longer matches version-7 resource migration")
        rendered[f"{name}.bndlspec"] = specification.replace(
            "  <code>\n", "  <files>bundle/*</files>\n  <code>\n", 1
        )
        activator = rendered["src/BundleActivator.cpp"]
        property_line = f'        properties.set("pdr.plugin.version", "1.0.0");\n'
        if property_line not in activator:
            raise ValueError(f"{kind} activator no longer matches version-7 ownership migration")
        rendered["src/BundleActivator.cpp"] = activator.replace(
            property_line,
            property_line
            + f'        properties.set("pdr.bundle", "{symbolic}");\n'
            + '        properties.set("pdr.service.readiness", "ready");\n',
            1,
        )
        rendered["README.md"] += '''

## Independent contract test

`bundle/service-contracts.json` declares the Bundle-owned Service surface. The
generated CTest validates it without starting Runtime. Add Provider teams' real
`service-contracts.json` files through `PROVIDER_CONTRACTS` when this component
gains requirements; required version/count mismatches fail before integration.
'''
    if version >= 8 and kind in {"bundle", "plugin"}:
        slug = component_slug(name)
        lowered = name.lower()
        symbolic = f"pdr.plugin.{lowered}"
        namespace = f"PocoDDS::Generated::{name}"
        participant_id = f"plugin-{slug}"
        participant_service = f"pdr.configuration.participant.{lowered}"
        target_stem = f"pdr_generated_{kind}_{slug.replace('-', '_')}"
        rendered["CMakeLists.txt"] += f'''
if(BUILD_TESTING)
    pdr_add_configuration_participant_contract_test(
        NAME {kind}-{lowered}-configuration-participant-contract
        DECLARATION ${{CMAKE_CURRENT_SOURCE_DIR}}/bundle/configuration-participants.json)
endif()
'''
        rendered[f"include/PocoDDS/Generated/{name}/StatusService.h"] = f'''#pragma once

#include <PocoDDS/ConfigTransaction/ConfigurationParticipantService.h>

#include <mutex>
#include <string>

namespace {namespace}
{{
class StatusService final
    : public PocoDDS::ConfigTransaction::ConfigurationParticipantService
{{
public:
    static constexpr const char* SERVICE_NAME = "{symbolic}.status";
    static constexpr const char* PARTICIPANT_ID = "{participant_id}";
    static constexpr const char* CONFIGURATION_PREFIX = "{symbolic}";

    const std::string& pluginName() const noexcept {{ return _pluginName; }}
    bool started() const noexcept;
    void markStarted(bool value) noexcept;
    PocoDDS::ConfigTransaction::Values configuration() const;

    PocoDDS::ConfigTransaction::ParticipantDescriptor descriptor() const override;
    PocoDDS::ConfigTransaction::ParticipantResult preflight(
        const PocoDDS::ConfigTransaction::Context& context) override;
    PocoDDS::ConfigTransaction::ParticipantResult commit(
        const PocoDDS::ConfigTransaction::Context& context) override;
    PocoDDS::ConfigTransaction::ParticipantResult rollback(
        const PocoDDS::ConfigTransaction::Context& context) override;

    const std::type_info& type() const override {{ return typeid(StatusService); }}
    bool isA(const std::type_info& other) const override
    {{
        return std::string(other.name()) == typeid(StatusService).name() ||
               PocoDDS::ConfigTransaction::ConfigurationParticipantService::isA(other);
    }}

private:
    static PocoDDS::ConfigTransaction::Values ownedValues(
        const PocoDDS::ConfigTransaction::Snapshot& snapshot);

    std::string _pluginName{{"{name}"}};
    mutable std::mutex _mutex;
    bool _started{{false}};
    PocoDDS::ConfigTransaction::Values _configuration;
}};
}}
'''
        rendered["src/StatusService.cpp"] = f'''#include <PocoDDS/Generated/{name}/StatusService.h>

namespace {namespace}
{{
namespace
{{
bool owned(const std::string& key)
{{
    const std::string prefix(StatusService::CONFIGURATION_PREFIX);
    return key == prefix ||
           (key.size() > prefix.size() &&
            key.compare(0, prefix.size(), prefix) == 0 &&
            key[prefix.size()] == '.');
}}
}}

bool StatusService::started() const noexcept
{{
    std::lock_guard lock(_mutex);
    return _started;
}}

void StatusService::markStarted(bool value) noexcept
{{
    std::lock_guard lock(_mutex);
    _started = value;
}}

PocoDDS::ConfigTransaction::Values StatusService::configuration() const
{{
    std::lock_guard lock(_mutex);
    return _configuration;
}}

PocoDDS::ConfigTransaction::ParticipantDescriptor StatusService::descriptor() const
{{
    return {{PARTICIPANT_ID, {{CONFIGURATION_PREFIX}}, {{}}}};
}}

PocoDDS::ConfigTransaction::ParticipantResult StatusService::preflight(
    const PocoDDS::ConfigTransaction::Context&)
{{
    return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
}}

PocoDDS::ConfigTransaction::ParticipantResult StatusService::commit(
    const PocoDDS::ConfigTransaction::Context& context)
{{
    std::lock_guard lock(_mutex);
    _configuration = ownedValues(context.candidate);
    return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
}}

PocoDDS::ConfigTransaction::ParticipantResult StatusService::rollback(
    const PocoDDS::ConfigTransaction::Context& context)
{{
    std::lock_guard lock(_mutex);
    _configuration = ownedValues(context.previous);
    return PocoDDS::ConfigTransaction::ParticipantResult::accepted();
}}

PocoDDS::ConfigTransaction::Values StatusService::ownedValues(
    const PocoDDS::ConfigTransaction::Snapshot& snapshot)
{{
    PocoDDS::ConfigTransaction::Values result;
    for (const auto& [key, value] : snapshot.values)
        if (owned(key)) result.emplace(key, value);
    return result;
}}
}}
'''
        rendered["src/BundleActivator.cpp"] = f'''#include <PocoDDS/Generated/{name}/StatusService.h>

#include <Poco/ClassLibrary.h>
#include <Poco/AutoPtr.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

namespace {namespace}
{{
class BundleActivator final : public Poco::OSP::BundleActivator
{{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {{
        try
        {{
            _service = new StatusService;
            _service->markStarted(true);
            Poco::OSP::Properties properties;
            properties.set("pdr.plugin", "{symbolic}");
            properties.set("pdr.plugin.version", "1.0.0");
            properties.set("pdr.bundle", "{symbolic}");
            properties.set("pdr.service.readiness", "ready");
            _serviceRef = context->registry().registerService(
                StatusService::SERVICE_NAME, _service, properties);

            Poco::OSP::Properties participantProperties;
            participantProperties.set(
                PocoDDS::ConfigTransaction::ConfigurationParticipantService::PROPERTY_KIND,
                PocoDDS::ConfigTransaction::ConfigurationParticipantService::PARTICIPANT_KIND);
            participantProperties.set(
                PocoDDS::ConfigTransaction::ConfigurationParticipantService::PROPERTY_ID,
                StatusService::PARTICIPANT_ID);
            participantProperties.set("pdr.bundle", "{symbolic}");
            _participantRef = context->registry().registerService(
                "{participant_service}", _service, participantProperties);
            context->logger().information("{name} plugin started");
        }}
        catch (...)
        {{
            stop(context);
            throw;
        }}
    }}

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {{
        if (_participantRef)
        {{
            try {{ context->registry().unregisterService(_participantRef); }}
            catch (...) {{}}
        }}
        if (_serviceRef)
        {{
            try {{ context->registry().unregisterService(_serviceRef); }}
            catch (...) {{}}
        }}
        if (_service) _service->markStarted(false);
        _participantRef.reset();
        _serviceRef.reset();
        _service.reset();
    }}

private:
    Poco::AutoPtr<StatusService> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceRef::Ptr _participantRef;
}};
}}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS({namespace}::BundleActivator)
POCO_END_MANIFEST
'''
        rendered[f"tests/{name}Smoke.cpp"] = f'''#include <PocoDDS/Generated/{name}/StatusService.h>

int main()
{{
    {namespace}::StatusService service;
    if (service.pluginName() != "{name}" || service.started()) return 1;
    const auto descriptor = service.descriptor();
    if (descriptor.id != "{participant_id}" || descriptor.ownedPrefixes.size() != 1 ||
        descriptor.ownedPrefixes[0] != "{symbolic}" || !descriptor.after.empty()) return 2;

    PocoDDS::ConfigTransaction::Context context;
    context.candidate.values["{symbolic}.enabled"] = "true";
    context.candidate.values["pdr.unowned.value"] = "ignored";
    if (!service.preflight(context).success || !service.commit(context).success) return 3;
    const auto committed = service.configuration();
    if (committed.size() != 1 || committed.at("{symbolic}.enabled") != "true") return 4;
    if (!service.rollback(context).success || !service.configuration().empty()) return 5;
    service.markStarted(true);
    return service.started() &&
                   service.isA(typeid(PocoDDS::ConfigTransaction::ConfigurationParticipantService))
               ? 0 : 6;
}}
'''
        rendered["bundle/configuration-participants.json"] = json.dumps(
            {
                "schemaVersion": 1,
                "participants": [{
                    "id": participant_id,
                    "serviceName": participant_service,
                    "ownedPrefixes": [symbolic],
                    "after": [],
                }],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        rendered["README.md"] += f'''

## Transactional configuration ownership

`bundle/configuration-participants.json` declares `{symbolic}` as this Bundle's
configuration prefix. `StatusService` registers `{participant_service}` and keeps
only keys inside that prefix during commit/rollback. Add validation in `preflight`
before introducing product-specific keys; do not claim another team's prefix.

The isolated `{kind}-{lowered}-configuration-participant-contract` CTest catches
duplicate IDs, Service names, prefix overlap and dependency cycles. Pass other
teams' declarations through `PROVIDER_DECLARATIONS` when their participants are
listed in `after` or share the same product integration boundary.
'''
    if version >= 9 and kind in {"bundle", "plugin"}:
        lowered = name.lower()
        rendered["CMakeLists.txt"] += f'''
if(BUILD_TESTING)
    pdr_add_configuration_key_lifecycle_contract_test(
        NAME {kind}-{lowered}-configuration-key-lifecycle-contract
        DECLARATION ${{CMAKE_CURRENT_SOURCE_DIR}}/bundle/configuration-key-lifecycle.json
        PARTICIPANT_DECLARATION ${{CMAKE_CURRENT_SOURCE_DIR}}/bundle/configuration-participants.json
        RUNTIME_VERSION "${{PocoDDSRuntime_VERSION}}")
endif()
'''
        rendered["bundle/configuration-key-lifecycle.json"] = json.dumps(
            {"schemaVersion": 1, "entries": []}, indent=2, ensure_ascii=False
        ) + "\n"
        rendered["README.md"] += '''

## Configuration key lifecycle

`bundle/configuration-key-lifecycle.json` is owned by this Bundle. Before a
product migration renames or removes a published key, add a `PDR-CFG-*` entry
that identifies the Participant, replacement key, first deprecation release and
earliest later-major removal release. The isolated lifecycle CTest rejects
cross-team keys, replacement cycles and migration files without a matching
owner declaration. An empty file means this Bundle has no deprecated keys.
'''
    return rendered


def split_files(rendered: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    managed = {path: content for path, content in rendered.items() if managed_path(path)}
    project_files = {path: content for path, content in rendered.items() if not managed_path(path)}
    return managed, project_files


def build_state(kind: str, name: str, version: int, managed: dict[str, str],
                project_files: dict[str, str],
                unmanaged: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "template": TEMPLATE_ID,
        "kind": kind,
        "name": name,
        "appliedVersion": version,
        "managedFiles": [
            {"path": path, "baselineSha256": project_template.sha256_text(content)}
            for path, content in sorted(managed.items())
        ],
        "projectFiles": [
            {"path": path, "templateSha256": project_template.sha256_text(content)}
            for path, content in sorted(project_files.items())
        ],
        "unmanagedFiles": [
            {"path": path, "reason": reason}
            for path, reason in sorted((unmanaged or {}).items())
        ],
    }


def _validate_records(document: dict[str, Any], field: str, digest_field: str,
                      seen: set[str]) -> list[dict[str, str]]:
    records = document.get(field)
    if not isinstance(records, list):
        raise ValueError(f"component template {field} must be an array")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict) or set(item) != {"path", digest_field}:
            raise ValueError(f"component template {field}[{index}] has invalid fields")
        path = project_template.safe_relative(item["path"], f"{field}[{index}].path")
        if path == STATE_PATH.as_posix() or path in seen:
            raise ValueError(f"duplicate or reserved component template path: {path}")
        seen.add(path)
        value = item[digest_field]
        if not isinstance(value, str) or not project_template.SHA256.fullmatch(value):
            raise ValueError(f"component template {field}[{index}] has invalid digest")
        normalized.append({"path": path, digest_field: value})
    return sorted(normalized, key=lambda item: item["path"])


def validate_state(document: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "template", "kind", "name", "appliedVersion",
        "managedFiles", "projectFiles", "unmanagedFiles",
    }
    if set(document) != required:
        raise ValueError("component template state has an unexpected envelope")
    if document["schemaVersion"] != 1 or document["template"] != TEMPLATE_ID:
        raise ValueError("unsupported component template state contract")
    kind = document["kind"]
    name = document["name"]
    if kind not in COMPONENT_KINDS:
        raise ValueError(f"unsupported component template kind: {kind}")
    if not isinstance(name, str) or COMPONENT_NAME.fullmatch(name) is None:
        raise ValueError("component template name must be PascalCase ASCII")
    version = document["appliedVersion"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("component template appliedVersion must be a positive integer")
    seen: set[str] = set()
    managed = _validate_records(document, "managedFiles", "baselineSha256", seen)
    project_files = _validate_records(document, "projectFiles", "templateSha256", seen)
    unmanaged_source = document["unmanagedFiles"]
    if not isinstance(unmanaged_source, list):
        raise ValueError("component template unmanagedFiles must be an array")
    unmanaged: list[dict[str, str]] = []
    for index, item in enumerate(unmanaged_source):
        if not isinstance(item, dict) or set(item) != {"path", "reason"}:
            raise ValueError(f"component template unmanagedFiles[{index}] has invalid fields")
        path = project_template.safe_relative(item["path"], f"unmanagedFiles[{index}].path")
        if path == STATE_PATH.as_posix() or path in seen:
            raise ValueError(f"duplicate or reserved component template path: {path}")
        seen.add(path)
        reason = item["reason"]
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"component template unmanagedFiles[{index}] reason is invalid")
        unmanaged.append({"path": path, "reason": reason})
    return {
        "schemaVersion": 1,
        "template": TEMPLATE_ID,
        "kind": kind,
        "name": name,
        "appliedVersion": version,
        "managedFiles": managed,
        "projectFiles": project_files,
        "unmanagedFiles": sorted(unmanaged, key=lambda item: item["path"]),
    }


def load_state(root: Path) -> dict[str, Any]:
    path = root / STATE_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"component template state not found: {path}; run pdr component adopt"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read component template state: {path}") from error
    if not isinstance(document, dict):
        raise ValueError("component template state root must be an object")
    return validate_state(document)


def write_initial_state(root: Path, kind: str, name: str,
                        rendered: dict[str, str]) -> None:
    managed, project_files = split_files(rendered)
    project_template.atomic_json(
        root / STATE_PATH,
        build_state(kind, name, CURRENT_TEMPLATE_VERSION, managed, project_files),
    )


def require_current_clean(root: Path,
                          base_renderer: BaseRenderer = default_base_renderer) -> dict[str, Any] | None:
    root = root.resolve()
    if not (root / STATE_PATH).is_file():
        return None
    state = load_state(root)
    if state["appliedVersion"] != CURRENT_TEMPLATE_VERSION:
        raise ValueError(
            f"component template is outdated: {root}; "
            f"applied={state['appliedVersion']} current={CURRENT_TEMPLATE_VERSION}"
        )
    desired, _ = split_files(render_component_template(
        state["kind"], state["name"], base_renderer, CURRENT_TEMPLATE_VERSION
    ))
    managed = {item["path"]: item["baselineSha256"] for item in state["managedFiles"]}
    unmanaged = {item["path"] for item in state["unmanagedFiles"]}
    missing_records = sorted(set(desired) - set(managed) - unmanaged)
    unexpected_records = sorted(set(managed) - set(desired))
    stale_baselines = sorted(
        path for path, baseline in managed.items()
        if path in desired and baseline != project_template.sha256_text(desired[path])
    )
    if missing_records or unexpected_records or stale_baselines:
        details = []
        if missing_records:
            details.append("untracked=" + ",".join(missing_records))
        if unexpected_records:
            details.append("unexpected=" + ",".join(unexpected_records))
        if stale_baselines:
            details.append("stale-baseline=" + ",".join(stale_baselines))
        raise ValueError(
            f"component template state does not match the current renderer in {root}: "
            + "; ".join(details)
        )
    drift = [
        item["path"] for item in state["managedFiles"]
        if project_template.file_sha256(root / item["path"]) != item["baselineSha256"]
    ]
    if drift:
        raise ValueError(
            f"component template managed files drifted in {root}: " + ", ".join(drift)
        )
    return state


def status_document(root: Path, base_renderer: BaseRenderer) -> dict[str, Any]:
    root = root.resolve()
    state = load_state(root)
    if state["appliedVersion"] > CURRENT_TEMPLATE_VERSION:
        raise ValueError("component template was created by a newer pdr CLI")
    desired = render_component_template(
        state["kind"], state["name"], base_renderer, CURRENT_TEMPLATE_VERSION
    )
    desired_managed, desired_project = split_files(desired)
    managed = {item["path"]: item["baselineSha256"] for item in state["managedFiles"]}
    unmanaged_paths = {item["path"] for item in state["unmanagedFiles"]}
    records: list[dict[str, Any]] = []
    drifted = False
    for path, baseline in sorted(managed.items()):
        current = project_template.file_sha256(root / path)
        condition = "clean" if current == baseline else ("missing" if current is None else "modified")
        drifted = drifted or condition != "clean"
        records.append({
            "path": path,
            "condition": condition,
            "baselineSha256": baseline,
            "currentSha256": current,
            "targetSha256": (
                project_template.sha256_text(desired_managed[path])
                if path in desired_managed else None
            ),
        })
    for path in sorted(set(desired_managed) - set(managed) - unmanaged_paths):
        records.append({
            "path": path,
            "condition": "untracked",
            "baselineSha256": None,
            "currentSha256": project_template.file_sha256(root / path),
            "targetSha256": project_template.sha256_text(desired_managed[path]),
        })
        drifted = True
    project_records = []
    for path, content in sorted(desired_project.items()):
        current = project_template.file_sha256(root / path)
        template_sha = project_template.sha256_text(content)
        condition = "missing" if current is None else (
            "template-original" if current == template_sha else "product-owned"
        )
        project_records.append({
            "path": path, "condition": condition,
            "templateSha256": template_sha, "currentSha256": current,
        })
    update_available = state["appliedVersion"] < CURRENT_TEMPLATE_VERSION
    return {
        "schemaVersion": 1,
        "operation": "component-template-status",
        "component": str(root),
        "kind": state["kind"],
        "name": state["name"],
        "appliedVersion": state["appliedVersion"],
        "currentVersion": CURRENT_TEMPLATE_VERSION,
        "updateAvailable": update_available,
        "drifted": drifted,
        "healthy": not update_available and not drifted,
        "managedFiles": records,
        "projectFiles": project_records,
        "unmanagedFiles": state["unmanagedFiles"],
    }


def _write_report(root: Path, value: str | Path | None, document: dict[str, Any]) -> None:
    project_template.write_report(root, value, document)


def status_command(args: Any, base_renderer: BaseRenderer) -> int:
    root = Path(args.component).resolve()
    report = status_document(root, base_renderer)
    _write_report(root, args.report, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"PDR_COMPONENT_TEMPLATE_STATUS kind={report['kind']} "
            f"version={report['appliedVersion']} current={report['currentVersion']} "
            f"update={str(report['updateAvailable']).lower()} "
            f"drift={str(report['drifted']).lower()}"
        )
    return 2 if args.check and not report["healthy"] else 0


def adopt_command(args: Any, base_renderer: BaseRenderer) -> int:
    root = Path(args.component).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"component directory not found: {root}")
    state_path = root / STATE_PATH
    if state_path.exists():
        raise ValueError("component already has template state")
    rendered = render_component_template(args.kind, args.name, base_renderer, args.version)
    desired_managed, project_files = split_files(rendered)
    managed: dict[str, str] = {}
    unmanaged: dict[str, str] = {}
    for path, content in desired_managed.items():
        current = project_template.file_sha256(root / path)
        if current == project_template.sha256_text(content):
            managed[path] = content
        else:
            unmanaged[path] = "missing" if current is None else "pre-existing-customization"
    state = build_state(
        args.kind, args.name, args.version, managed, project_files, unmanaged
    )
    journal = project_template.transactional_write(
        root,
        "component-template-adopt",
        {STATE_PATH.as_posix(): project_template.pretty_json(state)},
        {STATE_PATH.as_posix(): None},
    )
    report = {
        "schemaVersion": 1,
        "operation": "component-template-adopt",
        "kind": args.kind,
        "name": args.name,
        "version": args.version,
        "managedFiles": sorted(managed),
        "unmanagedFiles": state["unmanagedFiles"],
        "journal": journal.relative_to(root).as_posix(),
    }
    _write_report(root, args.report, report)
    print(
        f"PDR_COMPONENT_TEMPLATE_ADOPT_PASS kind={args.kind} version={args.version} "
        f"managed={len(managed)} unmanaged={len(unmanaged)} journal={journal}"
    )
    return 0


def upgrade_command(args: Any, base_renderer: BaseRenderer) -> int:
    root = Path(args.component).resolve()
    state_before = project_template.file_sha256(root / STATE_PATH)
    state = load_state(root)
    if project_template.file_sha256(root / STATE_PATH) != state_before:
        raise RuntimeError("component template state changed during upgrade planning")
    target = CURRENT_TEMPLATE_VERSION if args.target_version is None else args.target_version
    if target not in SUPPORTED_TEMPLATE_VERSIONS:
        raise ValueError(f"unsupported component template target version: {target}")
    if target < state["appliedVersion"]:
        raise ValueError("component template downgrade is not supported")
    rendered = render_component_template(state["kind"], state["name"], base_renderer, target)
    desired_managed, desired_project = split_files(rendered)
    actions, conflicts, observed = project_template.conflict_plan(root, desired_managed, state)
    accept = project_template.normalize_selections(args.accept_template, "--accept-template")
    keep = project_template.normalize_selections(args.keep_project, "--keep-project")
    if accept & keep:
        raise ValueError("a component template path cannot be both accepted and kept")
    conflict_paths = {item["path"] for item in conflicts}
    unknown = (accept | keep) - conflict_paths
    if unknown:
        raise ValueError("conflict selection is not active: " + ", ".join(sorted(unknown)))
    unresolved = conflict_paths - accept - keep
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "operation": "component-template-upgrade",
        "component": str(root),
        "kind": state["kind"],
        "name": state["name"],
        "fromVersion": state["appliedVersion"],
        "toVersion": target,
        "actions": [{"path": path, "action": action} for path, action in sorted(actions.items())],
        "conflicts": conflicts,
        "unresolvedConflicts": sorted(unresolved),
        "applied": False,
    }
    if unresolved:
        _write_report(root, args.report, report)
        print(
            f"PDR_COMPONENT_TEMPLATE_UPGRADE_CONFLICT conflicts={len(unresolved)} "
            f"report={args.report or '-'}"
        )
        return 2
    file_changes: dict[str, bytes | None] = {}
    managed_content: dict[str, str] = {}
    unmanaged = {item["path"]: item["reason"] for item in state["unmanagedFiles"]}
    for path, action in sorted(actions.items()):
        if path in keep:
            unmanaged[path] = "kept-product-customization"
            continue
        unmanaged.pop(path, None)
        if path in desired_managed:
            managed_content[path] = desired_managed[path]
            if action != "manage" or path in accept:
                file_changes[path] = desired_managed[path].encode("utf-8")
        elif action == "remove" or path in accept:
            file_changes[path] = None
    known_project_files = {item["path"] for item in state["projectFiles"]}
    for path, content in sorted(desired_project.items()):
        if path in known_project_files:
            continue
        current = project_template.file_sha256(root / path)
        observed[path] = current
        if current is None:
            # A new product-owned contract starts from the template default, but
            # subsequent template upgrades never overwrite product edits.
            if (path == "bundle/service-contracts.json" and
                    state["kind"] in {"bundle", "plugin"} and
                    state["appliedVersion"] < 7):
                # Existing Activators are product-owned and are intentionally
                # not rewritten with the v7 pdr.bundle/readiness properties.
                # Seed a non-claiming contract so an upgrade cannot make a
                # previously healthy Bundle fail Runtime owner validation.
                content = json.dumps({
                    "schemaVersion": 1, "provides": [], "requires": [],
                }, indent=2) + "\n"
            if (path == "bundle/configuration-participants.json" and
                    state["kind"] in {"bundle", "plugin"} and
                    state["appliedVersion"] < 8):
                # v8 does not overwrite the product-owned Activator/Service of
                # an existing plugin. Seed a non-claiming declaration so the
                # added contract test is useful without creating a Runtime
                # expectation that the old source cannot satisfy.
                content = json.dumps({
                    "schemaVersion": 1, "participants": [],
                }, indent=2) + "\n"
            file_changes[path] = content.encode("utf-8")
    new_state = build_state(
        state["kind"], state["name"], target,
        managed_content, desired_project, unmanaged,
    )
    file_changes[STATE_PATH.as_posix()] = project_template.pretty_json(new_state)
    preconditions = dict(observed)
    preconditions[STATE_PATH.as_posix()] = state_before
    journal = project_template.transactional_write(
        root, "component-template-upgrade", file_changes, preconditions
    )
    report.update({
        "applied": True,
        "journal": journal.relative_to(root).as_posix(),
        "managedFiles": [item["path"] for item in new_state["managedFiles"]],
        "projectFiles": new_state["projectFiles"],
        "unmanagedFiles": new_state["unmanagedFiles"],
    })
    _write_report(root, args.report, report)
    print(
        f"PDR_COMPONENT_TEMPLATE_UPGRADE_PASS kind={state['kind']} "
        f"from={state['appliedVersion']} to={target} managed={len(new_state['managedFiles'])} "
        f"unmanaged={len(new_state['unmanagedFiles'])} journal={journal}"
    )
    return 0


def recover_command(args: Any) -> int:
    root = Path(args.component).resolve()
    journal = project_template.confined(
        root, args.journal, "component template recovery journal", must_exist=True
    )
    changed, transaction_id, status = project_template.recover_transaction(
        root,
        journal,
        {"component-template-adopt", "component-template-upgrade"},
        args.retry_rollback,
    )
    marker = "PASS" if changed else "NOOP"
    print(
        f"PDR_COMPONENT_TEMPLATE_RECOVER_{marker} transaction={transaction_id} "
        f"status={status} journal={journal}"
    )
    return 0


def collaboration_contract(root: Path) -> dict[str, Any]:
    path = root.resolve() / COLLABORATION_CONTRACT_PATH
    if not path.is_file():
        raise FileNotFoundError(f"component collaboration contract not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid component collaboration contract: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("requires"), list):
        raise ValueError("component collaboration contract has no requires array")
    return document


def dependency_command(args: Any) -> int:
    root = Path(args.component).resolve()
    document = collaboration_contract(root)
    current = document["requires"]
    if not all(isinstance(item, str) and re.fullmatch(
            r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", item) for item in current):
        raise ValueError("component collaboration contract contains invalid dependency ids")
    if args.dependency_operation == "list":
        if args.json:
            print(json.dumps(sorted(current), indent=2, ensure_ascii=False))
        else:
            for item in sorted(current):
                print(item)
        return 0

    dependency = args.dependency
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", dependency):
        raise ValueError("component dependency must be lowercase kebab-case")
    component_id = document.get("id")
    if dependency == component_id:
        raise ValueError("component cannot depend on itself")
    if args.dependency_operation == "add":
        if dependency in current:
            raise ValueError(f"component dependency already exists: {dependency}")
        current.append(dependency)
        current.sort()
    elif args.dependency_operation == "remove":
        if dependency not in current:
            raise ValueError(f"component dependency is not declared: {dependency}")
        current.remove(dependency)
    else:
        raise ValueError(f"unsupported component dependency operation: {args.dependency_operation}")
    project_template.atomic_json(root / COLLABORATION_CONTRACT_PATH, document)
    print(
        f"PDR_COMPONENT_DEPENDENCY_{args.dependency_operation.upper()}_PASS "
        f"component={component_id} dependency={dependency}"
    )
    return 0


def baseline_fingerprint(kind: str, base_renderer: BaseRenderer,
                         name: str = "TemplateProbe") -> str:
    rendered = render_component_template(kind, name, base_renderer, 1)
    evidence = {
        path: project_template.sha256_text(content)
        for path, content in sorted(rendered.items())
    }
    return hashlib.sha256(project_template.canonical_json(evidence)).hexdigest()
