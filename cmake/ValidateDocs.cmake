set(required_docs
    "docs/architecture/layering-rules.md"
    "docs/architecture/extensibility.md"
    "docs/architecture/performance-budgets.md"
    "docs/architecture/deployment-profiles.md"
    "docs/architecture/framework-model-selection.md"
    "docs/adr/README.md"
    "docs/operations/runbook.md"
    "docs/operations/troubleshooting.md"
    "docs/operations/recovery.md"
    "docs/development/new-service.md"
    "docs/development/new-device.md"
    "docs/development/new-protocol.md"
    "docs/development/new-subprocess.md"
    "docs/development/sdk-and-scaffolding.md"
    "docs/development/project-workspaces.md"
    "docs/development/project-configuration.md"
    "docs/development/project-templates.md"
    "docs/development/component-templates.md"
    "docs/development/project-pipelines.md"
    "docs/development/project-delivery.md"
    "docs/security/README.md"
    "docs/compatibility/README.md")
foreach(relative_path IN LISTS required_docs)
    if(NOT EXISTS "${SOURCE_DIR}/${relative_path}")
        message(FATAL_ERROR "Missing governance document: ${relative_path}")
    endif()
endforeach()
file(READ "${SOURCE_DIR}/docs/README.md" index)
foreach(link
        "architecture/layering-rules.md"
        "architecture/extensibility.md"
        "architecture/performance-budgets.md"
        "architecture/framework-model-selection.md"
        "development/project-workspaces.md"
        "development/project-configuration.md"
        "development/project-templates.md"
        "development/component-templates.md"
        "development/project-pipelines.md"
        "development/project-delivery.md"
        "operations/runbook.md"
        "operations/troubleshooting.md"
        "operations/recovery.md")
    string(FIND "${index}" "${link}" position)
    if(position EQUAL -1)
        message(FATAL_ERROR "Documentation index is missing: ${link}")
    endif()
endforeach()
message(STATUS "DOCUMENTATION_FILES_PASS")
