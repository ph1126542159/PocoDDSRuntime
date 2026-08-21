cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntime VERSION 0.1.0 LANGUAGES CXX)

include(GNUInstallDirs)
include(CTest)
set_property(GLOBAL PROPERTY USE_FOLDERS ON)

list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(MSVC)
    # A machine-wide vcpkg MSBuild integration may inject AppLocal into every
    # generated target. This project owns its runtime DLL layout explicitly,
    # and AppLocal otherwise probes for PowerShell 7 (pwsh.exe) after each link.
    list(APPEND CMAKE_VS_GLOBALS "VcpkgApplocalDeps=false")

    # All build-local third-party packages are produced as Release artifacts.
    # Debug project objects therefore keep the Release-compatible runtime and
    # iterator ABI while retaining Debug optimization and symbol settings.
    set(CMAKE_CONFIGURATION_TYPES "Debug;Release"
        CACHE STRING "Supported build configurations" FORCE)
    set(CMAKE_MAP_IMPORTED_CONFIG_DEBUG Release)
    add_compile_options(
        /FS
        /utf-8
        # The Visual Studio generator adds _DEBUG through the generated
        # PreprocessorDefinitions list, independently of CMAKE_*_FLAGS_DEBUG.
        # /U_DEBUG is emitted after that list and is therefore the reliable
        # way to keep Debug builds ABI-compatible with Release-only packages.
        $<$<CONFIG:Debug>:/U_DEBUG>)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    # CMake's MSVC Debug defaults add /D_DEBUG independently of /MD. The MSVC
    # CRT headers interpret _DEBUG as a request for the debug CRT and emit an
    # MDd_DynamicDebug mismatch marker, even when RuntimeLibrary is /MD.
    # Remove that definition so Debug objects remain ABI-compatible with the
    # Release-only Poco/Fast DDS dependency prefix while keeping /Od and PDBs.
    foreach(language C CXX)
        string(REPLACE "/D_DEBUG" "" CMAKE_${language}_FLAGS_DEBUG
            "${CMAKE_${language}_FLAGS_DEBUG}")
        string(REPLACE "/D _DEBUG" "" CMAKE_${language}_FLAGS_DEBUG
            "${CMAKE_${language}_FLAGS_DEBUG}")
    endforeach()
    add_compile_definitions(
        $<$<CONFIG:Debug>:_ITERATOR_DEBUG_LEVEL=0>
        $<$<CONFIG:Debug>:NDEBUG>)
endif()

add_compile_definitions(POCO_NO_AUTOMATIC_LIBS)

if(CMAKE_SYSTEM_NAME STREQUAL "Windows")
    set(MYIOT_PLATFORM_OSNAME "Windows_NT")
else()
    set(MYIOT_PLATFORM_OSNAME "${CMAKE_SYSTEM_NAME}")
endif()

if(CMAKE_VS_PLATFORM_NAME STREQUAL "x64")
    set(MYIOT_PLATFORM_OSARCH "AMD64")
elseif(CMAKE_SYSTEM_PROCESSOR)
    set(MYIOT_PLATFORM_OSARCH "${CMAKE_SYSTEM_PROCESSOR}")
else()
    set(MYIOT_PLATFORM_OSARCH "unknown")
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(PDR_PROCESS_OUTPUT_ROOT "${CMAKE_BINARY_DIR}/bin")
set(PDR_RUNTIME_PROCESS_DIRECTORY "${PDR_PROCESS_OUTPUT_ROOT}")
set(PDR_SUBPROCESS_OUTPUT_ROOT "${PDR_PROCESS_OUTPUT_ROOT}/processes")
set(PDR_BUNDLE_OUTPUT_DIRECTORY "${PDR_RUNTIME_PROCESS_DIRECTORY}/bundles")
set(PDR_TEST_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/test")
if(CMAKE_CONFIGURATION_TYPES)
    foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
        string(TOUPPER "${configuration}" configuration_upper)
        set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${configuration_upper} "${CMAKE_BINARY_DIR}/bin")
        set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_${configuration_upper} "${CMAKE_BINARY_DIR}/bin")
        set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY_${configuration_upper} "${CMAKE_BINARY_DIR}/bin")
    endforeach()
endif()

set(_pdr_install_prefix "${CMAKE_CURRENT_SOURCE_DIR}/build/install")
set(PDR_INSTALL_PREFIX "${_pdr_install_prefix}"
    CACHE PATH "Unified runtime and third-party installation prefix")
option(PDR_RELEASE_REQUIRE_CLEAN
    "Require a clean Git worktree when generating release artifacts" OFF)
# Migrate the repository's former split dependency prefix. Explicit custom
# prefixes (for example an ARM64 sysroot) remain untouched.
if(PDR_INSTALL_PREFIX STREQUAL
   "${CMAKE_CURRENT_SOURCE_DIR}/build/dependencies/install")
    set(PDR_INSTALL_PREFIX "${_pdr_install_prefix}"
        CACHE PATH "Unified runtime and third-party installation prefix" FORCE)
endif()
# Keep a normal configure/install cycle in one predictable tree. A caller can
# still override either cache entry for an architecture-specific cross build.
if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
    set(CMAKE_INSTALL_PREFIX "${_pdr_install_prefix}"
        CACHE PATH "Unified PocoDDSRuntime installation prefix" FORCE)
endif()
unset(_pdr_install_prefix)
list(PREPEND CMAKE_PREFIX_PATH "${PDR_INSTALL_PREFIX}")

option(MYIOT_ENABLE_DATA_MODULES "Build Poco Data-related OSP bundles" OFF)
option(PDR_ENABLE_OBSERVABILITY
    "Build the OpenTelemetry business observability module" ON)
option(PDR_AUTO_BOOTSTRAP_DEPENDENCIES
    "Build missing third-party dependencies during project configuration" ON)
set(PDR_PROFILE "custom" CACHE STRING "Deployment profile: embedded, edge-test, server or custom")
set_property(CACHE PDR_PROFILE PROPERTY STRINGS embedded edge-test server custom)
option(PDR_BUILD_WEBUI "Build and package administration WebUI page bundles" ON)
option(PDR_BUILD_LAUNCHER "Build the independent runtime watchdog launcher" ON)
option(PDR_BUILD_PLUGIN_HOST "Build the isolated OSP plugin host process" ON)
option(PDR_BUILD_QT3D "Build the Qt3D demonstration subprocess" ON)
option(PDR_BUILD_LEGACY_RUNTIME
    "Build the existing Poco/OSP runtime and direct Fast-DDS integrations" ON)
option(PDR_BUILD_ROBOTICS_RUNTIME
    "Build the transport-neutral embodied robotics runtime core" OFF)
set(PDR_COMM_BACKEND "FASTDDS" CACHE STRING
    "Inter-process communication backend: FASTDDS or ROS2")
set_property(CACHE PDR_COMM_BACKEND PROPERTY STRINGS FASTDDS ROS2)
if(NOT PDR_COMM_BACKEND MATCHES "^(FASTDDS|ROS2)$")
    message(FATAL_ERROR "Unsupported PDR_COMM_BACKEND: ${PDR_COMM_BACKEND}")
endif()
if(NOT PDR_PROFILE MATCHES "^(embedded|edge-test|server|custom)$")
    message(FATAL_ERROR "Unsupported PDR_PROFILE: ${PDR_PROFILE}")
endif()

# External plugins carry this contract in their Bundle manifest. API versions use
# semantic ranges; the ABI fingerprint is intentionally exact because OSP loads
# plugin shared libraries into the Runtime process.
set(PDR_PLUGIN_API_VERSION "1.0.0")
set(PDR_PLUGIN_ABI_VERSION "1.0.0")
string(REGEX MATCH "^[0-9]+" PDR_PLUGIN_COMPILER_MAJOR "${CMAKE_CXX_COMPILER_VERSION}")
set(PDR_PLUGIN_ABI_FINGERPRINT
    "${CMAKE_CXX_COMPILER_ID}-${PDR_PLUGIN_COMPILER_MAJOR}-${MYIOT_PLATFORM_OSNAME}-${MYIOT_PLATFORM_OSARCH}")
math(EXPR PDR_PLUGIN_RUNTIME_NEXT_MINOR "${PROJECT_VERSION_MINOR} + 1")
set(PDR_PLUGIN_RUNTIME_RANGE
    "[${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}.0,${PROJECT_VERSION_MAJOR}.${PDR_PLUGIN_RUNTIME_NEXT_MINOR}.0)")
set(SHARED_LIBRARY_VERSION 1 CACHE STRING "Compatibility version for migrated platform libraries")

include(PDRWarnings)
include(PDRProcessLayout)

if(PDR_BUILD_ROBOTICS_RUNTIME)
    set(CMAKE_FOLDER "Robotics")
    add_subdirectory(robotics)
endif()

if(NOT PDR_BUILD_LEGACY_RUNTIME)
    if(NOT PDR_BUILD_ROBOTICS_RUNTIME)
        message(FATAL_ERROR
            "PDR_BUILD_LEGACY_RUNTIME=OFF requires PDR_BUILD_ROBOTICS_RUNTIME=ON")
    endif()
    if(PDR_COMM_BACKEND STREQUAL "FASTDDS")
        message(WARNING
            "The standalone robotics core uses an in-process test transport. "
            "Select PDR_COMM_BACKEND=ROS2 and build robotics/ros2_ws with colcon "
            "to enable inter-process ROS 2 communication.")
    endif()
    unset(CMAKE_FOLDER)
    pdr_configure_test_output_tree("${CMAKE_CURRENT_SOURCE_DIR}")
    return()
endif()

if(NOT PDR_COMM_BACKEND STREQUAL "FASTDDS")
    message(FATAL_ERROR
        "The legacy runtime still requires PDR_COMM_BACKEND=FASTDDS. "
        "Use the robotics preset for the ROS2 migration path.")
endif()

include(PDRDependencies)
pdr_bootstrap_missing_dependencies()
pdr_require_poco()
pdr_require_paho_mqtt()
if(PDR_ENABLE_OBSERVABILITY)
    # Load the complete Protobuf export used by OpenTelemetry before Fast DDS.
    # Fast DDS may otherwise create CMake's reduced legacy Protobuf targets,
    # which conflict with the remaining targets in protobuf-config.cmake.
    pdr_require_opentelemetry()
endif()
pdr_require_fastdds()

# GCC 8 and older keep filesystem symbols in a separate compatibility
# library. Poco 1.15's static Foundation archive uses those symbols through
# its logger implementation, so propagate the required link dependency.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND
   CMAKE_CXX_COMPILER_VERSION VERSION_LESS 9.0)
    target_link_libraries(Poco::Foundation INTERFACE stdc++fs)
endif()
include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/PocoCompat.cmake")

set(MYIOT_OSP_BUNDLE_CREATOR_COMMAND "$<TARGET_FILE:OSPBundleCreator>")
if(CMAKE_CROSSCOMPILING)
    set(MYIOT_QEMU_ARM "" CACHE FILEPATH
        "Host-side qemu-aarch64 used to execute the target bundle creator")
    if(NOT MYIOT_QEMU_ARM OR NOT EXISTS "${MYIOT_QEMU_ARM}")
        message(FATAL_ERROR
            "Cross-compiling requires MYIOT_QEMU_ARM to run OSPBundleCreator")
    endif()
    set(MYIOT_OSP_BUNDLE_CREATOR_COMMAND
        "${MYIOT_QEMU_ARM}"
        "-L"
        "${CMAKE_SYSROOT}"
        "$<TARGET_FILE:OSPBundleCreator>")
endif()
if(WIN32)
    set(MYIOT_BUNDLE_OPT_PREFIX "/")
else()
    set(MYIOT_BUNDLE_OPT_PREFIX "--")
endif()
set(MYIOT_OSP_BUNDLE_OSNAME "${MYIOT_PLATFORM_OSNAME}")
set(MYIOT_OSP_BUNDLE_OSARCH "${MYIOT_PLATFORM_OSARCH}")

set(CMAKE_FOLDER "Platform")
add_subdirectory(sdk)
add_subdirectory(platform/security)
add_subdirectory(platform/configuration)
add_subdirectory(platform/reliability)
add_subdirectory(platform/health)
add_subdirectory(platform/persistence)
add_subdirectory(platform/CodeGeneration)
add_subdirectory(platform/Geo)
add_subdirectory(platform/Serial)
add_subdirectory(platform/WebTunnel)
if(PDR_ENABLE_OBSERVABILITY)
    set(CMAKE_FOLDER "Observability")
    add_subdirectory(platform/observability)
endif()
add_subdirectory(platform/OSP)
add_subdirectory(platform/BundleManagement)
add_subdirectory(platform/ProcessManagement)

set(CMAKE_FOLDER "Protocols")
add_subdirectory(platform/protocols)

set(CMAKE_FOLDER "Devices")
add_subdirectory(platform/devices)

set(CMAKE_FOLDER "Application")
add_subdirectory(application)

set(CMAKE_FOLDER "Communication")
add_subdirectory(platform/DDS)

set(CMAKE_FOLDER "Services")
add_subdirectory(services)

set(CMAKE_FOLDER "Applications")
if(PDR_BUILD_LAUNCHER OR PDR_BUILD_QT3D)
    add_subdirectory(SubSystem)
endif()
if(PDR_BUILD_WEBUI)
    add_subdirectory(webui)
endif()
add_subdirectory(server)

unset(CMAKE_FOLDER)
pdr_configure_test_output_tree("${CMAKE_CURRENT_SOURCE_DIR}")
if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    add_test(NAME contract-files
        COMMAND "${CMAKE_COMMAND}"
            -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ValidateContracts.cmake")
    add_test(NAME documentation-files
        COMMAND "${CMAKE_COMMAND}"
            -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ValidateDocs.cmake")
    add_test(NAME deployment-profiles
        COMMAND "${CMAKE_COMMAND}"
            -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ValidateProfiles.cmake")
    add_test(NAME sdk-external-consumer
        COMMAND "${CMAKE_COMMAND}"
            -DPDR_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -DPDR_BINARY_DIR=${CMAKE_BINARY_DIR}
            -DPDR_CONFIG=$<CONFIG>
            -DPDR_GENERATOR=${CMAKE_GENERATOR}
            -DPDR_GENERATOR_PLATFORM=${CMAKE_GENERATOR_PLATFORM}
            -DPDR_DEPENDENCY_PREFIX=${PDR_INSTALL_PREFIX}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/RunSDKConsumerTest.cmake")
    if(Python3_Interpreter_FOUND)
      add_test(NAME generated-device-consumer
        COMMAND "${CMAKE_COMMAND}"
            -DPDR_CMAKE=${CMAKE_COMMAND}
            -DPDR_CTEST=${CMAKE_CTEST_COMMAND}
            -DPDR_PYTHON=${Python3_EXECUTABLE}
            -DPDR_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -DPDR_BINARY_DIR=${CMAKE_BINARY_DIR}
            -DPDR_CONFIG=$<CONFIG>
            -DPDR_GENERATOR=${CMAKE_GENERATOR}
            -DPDR_GENERATOR_PLATFORM=${CMAKE_GENERATOR_PLATFORM}
            -DPDR_DEPENDENCY_PREFIX=${PDR_INSTALL_PREFIX}
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/RunGeneratedDeviceTest.cmake")
      set_tests_properties(generated-device-consumer PROPERTIES
          LABELS "sdk;device" TIMEOUT 90)
      add_test(NAME generated-plugin-consumer
        COMMAND "${CMAKE_COMMAND}"
            -DPDR_CMAKE=${CMAKE_COMMAND}
            -DPDR_CTEST=${CMAKE_CTEST_COMMAND}
            -DPDR_PYTHON=${Python3_EXECUTABLE}
            -DPDR_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -DPDR_BINARY_DIR=${CMAKE_BINARY_DIR}
            -DPDR_CONFIG=$<CONFIG>
            -DPDR_GENERATOR=${CMAKE_GENERATOR}
            -DPDR_GENERATOR_PLATFORM=${CMAKE_GENERATOR_PLATFORM}
            -DPDR_DEPENDENCY_PREFIX=${PDR_INSTALL_PREFIX}
            -DPDR_RUNTIME_FILE_NAME=$<TARGET_FILE_NAME:pdr-runtime>
            -DPDR_PLUGIN_HOST_FILE_NAME=$<TARGET_FILE_NAME:pdr-plugin-host>
            -DPDR_LAUNCHER_FILE_NAME=$<TARGET_FILE_NAME:pdr-launcher>
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/RunGeneratedPluginTest.cmake")
      set_tests_properties(generated-plugin-consumer PROPERTIES
          LABELS "sdk;plugin;runtime;integration" RESOURCE_LOCK pdr_runtime_http TIMEOUT 120)
    endif()
    if(Python3_Interpreter_FOUND)
        add_test(NAME developer-cli
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_pdr.py")
        add_test(NAME plugin-transactions
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_plugin_manager.py")
        set_tests_properties(plugin-transactions PROPERTIES
            LABELS "plugin;release;recovery;security")
        add_test(NAME service-ownership-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_service_ownership.py")
        set_tests_properties(service-ownership-policy PROPERTIES
            LABELS "runtime;security;release")
        add_test(NAME compatibility-baseline
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_compatibility.py"
                --root "${CMAKE_CURRENT_SOURCE_DIR}")
        add_test(NAME compatibility-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_compatibility.py")
        add_test(NAME configuration-contract
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_config_contract.py")
        set_tests_properties(configuration-contract PROPERTIES
            LABELS "configuration;release")
        add_test(NAME soak-runner-smoke
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/soak_runner.py"
                --duration 0.5
                --interval 0.1
                --warmup 0.3
                --output "${CMAKE_BINARY_DIR}/reports/soak-smoke.json"
                --max-rss-growth-mib 16
                --max-handle-growth 8
                -- "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/soak_target.py")
        set_tests_properties(soak-runner-smoke PROPERTIES LABELS "soak;nightly" TIMEOUT 10)
        add_test(NAME soak-health-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_soak_health.py")
        set_tests_properties(soak-health-policy PROPERTIES LABELS "soak;nightly" TIMEOUT 15)
        add_test(NAME device-acceptance-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_device_acceptance.py")
        set_tests_properties(device-acceptance-policy PROPERTIES
            LABELS "device;release"
            TIMEOUT 10)
        add_test(NAME protocol-acceptance-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_protocol_acceptance.py")
        set_tests_properties(protocol-acceptance-policy PROPERTIES
            LABELS "protocol;release"
            TIMEOUT 10)
        add_test(NAME security-config
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/security_gate.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties")
        add_test(NAME security-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_security_gate.py")
        add_test(NAME release-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_release_manifest.py")
        add_test(NAME release-qualification-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_release_qualification.py")
        set_tests_properties(release-qualification-policy PROPERTIES LABELS "release")
        add_test(NAME external-acceptance-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_external_acceptance.py"
                --verifier "$<TARGET_FILE:pdr-signature-check>")
        set_tests_properties(external-acceptance-policy PROPERTIES LABELS "release")
        add_test(NAME evidence-bundle-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_evidence_bundle.py"
                --verifier "$<TARGET_FILE:pdr-signature-check>")
        set_tests_properties(evidence-bundle-policy PROPERTIES LABELS "release;security")
        add_test(NAME release-pipeline-policy
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_release_pipeline.py")
        set_tests_properties(release-pipeline-policy PROPERTIES LABELS "release;recovery")
        add_test(NAME release-signature-check
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_release_signature_check.py"
                --executable "$<TARGET_FILE:pdr-signature-check>")
        set_tests_properties(release-signature-check PROPERTIES LABELS "release;security")
        add_test(NAME plugin-publisher-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_plugin_publisher_integration.py"
                --python "${Python3_EXECUTABLE}"
                --pdr "${CMAKE_CURRENT_SOURCE_DIR}/tools/pdr.py"
                --verifier "$<TARGET_FILE:pdr-signature-check>")
        set_tests_properties(plugin-publisher-integration PROPERTIES
            LABELS "plugin;release;security" TIMEOUT 30)
        add_test(NAME dependency-lock
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_dependency_lock.py")
        add_test(NAME release-matrix
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_release_matrix.py")
        add_test(NAME release-artifacts
            COMMAND "${CMAKE_COMMAND}"
                -DPDR_CMAKE=${CMAKE_COMMAND}
                -DPDR_PYTHON=${Python3_EXECUTABLE}
                -DPDR_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
                -DPDR_BINARY_DIR=${CMAKE_BINARY_DIR}
                -DPDR_CONFIG=$<CONFIG>
                -DPDR_VERSION=${PROJECT_VERSION}
                -DPDR_REQUIRE_CLEAN=${PDR_RELEASE_REQUIRE_CLEAN}
                -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/RunReleaseValidation.cmake")
        add_test(NAME upgrade-rollback
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/tests/test_upgrade_manager.py")
        if(NOT CMAKE_CROSSCOMPILING)
            add_test(NAME runtime-upgrade-acceptance-integration
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/upgrade_transaction_integration.py"
                    --cmake "${CMAKE_COMMAND}"
                    --python "${Python3_EXECUTABLE}"
                    --source "${CMAKE_CURRENT_SOURCE_DIR}"
                    --build "${CMAKE_BINARY_DIR}"
                    --config "$<CONFIG>"
                    --version "${PROJECT_VERSION}"
                    --runtime-file-name "$<TARGET_FILE_NAME:pdr-runtime>"
                    --signature-check-executable "$<TARGET_FILE:pdr-signature-check>"
                    --cycles 3
                    --workspace "${CMAKE_BINARY_DIR}/reports/runtime-upgrade-acceptance-workspace"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-upgrade-acceptance-integration.json")
            set_tests_properties(runtime-upgrade-acceptance-integration PROPERTIES
                LABELS "runtime;release;integration;recovery"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 120)
            add_test(NAME runtime-package-smoke
                COMMAND "${CMAKE_COMMAND}"
                    -DPDR_CMAKE=${CMAKE_COMMAND}
                    -DPDR_PYTHON=${Python3_EXECUTABLE}
                    -DPDR_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
                    -DPDR_BINARY_DIR=${CMAKE_BINARY_DIR}
                    -DPDR_DEPENDENCY_PREFIX=${PDR_INSTALL_PREFIX}
                    -DPDR_CONFIG=$<CONFIG>
                    -DPDR_RUNTIME_FILE_NAME=$<TARGET_FILE_NAME:pdr-runtime>
                    -DPDR_CONFIG_CHECK_FILE_NAME=$<TARGET_FILE_NAME:pdr-config-check>
                    -DPDR_IDENTITY_CHECK_FILE_NAME=$<TARGET_FILE_NAME:pdr-identity-check>
                    -DPDR_SIGNATURE_CHECK_FILE_NAME=$<TARGET_FILE_NAME:pdr-signature-check>
                    -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/RunRuntimePackageSmoke.cmake")
            set_tests_properties(runtime-package-smoke PROPERTIES
                LABELS "runtime;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            if(PDR_BUILD_WEBUI)
                add_test(NAME runtime-web-protocol-diagnostics
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                        --executable "$<TARGET_FILE:pdr-runtime>"
                        --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                        --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                        --timeout 20
                        --stability-window 2
                        --probe-delay 4
                        --clear-code-cache
                        --path "${PDR_INSTALL_PREFIX}/bin"
                        --path "$<TARGET_FILE_DIR:pdr-runtime>"
                        --endpoint "/home/"
                        --endpoint "/api/v1/protocols"
                        --endpoint "/api/v1/diagnostic-events"
                        --endpoint "/api/v1/alerts"
                        --endpoint "/api/v1/alert-sinks"
                        --endpoint "/api/v1/business-traces"
                        --endpoint "/api/v1/heartbeat-businesses"
                        --endpoint "/api/v1/metrics"
                        --endpoint "/health/detail"
                        --endpoint "/webevent"
                        --expect-status "/webevent=401"
                        --follow-html-assets
                        --require-body "assets/app-[A-Za-z0-9_-]+\\.js"
                        --require-body "运行拓扑"
                        --require-body "需要关注"
                        --require-body "资源趋势"
                        --require-body "打开进程工作台"
                        --require-body "业务追踪"
                        --require-body "ROS Bridge"
                        --require-body "\"protocols\""
                        --set "pdr.udp.count=1"
                        --set "pdr.udp.0.id=runtime-udp"
                        --set "pdr.udp.0.localHost=127.0.0.1"
                        --set "pdr.udp.0.localPort=0"
                        --set "pdr.udp.0.remoteHost=127.0.0.1"
                        --set "pdr.udp.0.remotePort=9"
                        --set "pdr.udp.0.required=true"
                        --set "pdr.ros.count=1"
                        --set "pdr.ros.0.id=runtime-ros-offline"
                        --set "pdr.ros.0.uri=ws://127.0.0.1:1"
                        --set "pdr.ros.0.required=false"
                        --set "pdr.ros.0.autoReconnect=false"
                        --set "pdr.alerts.debounceMilliseconds=0"
                        --set "pdr.alerts.silencedCodes=PDR-PROTOCOL-ROS-*"
                        --post "/api/v1/protocols={\"id\":\"runtime-udp\",\"action\":\"close\"}"
                        --post "/api/v1/protocols={\"id\":\"runtime-udp\",\"action\":\"open\"}"
                        --post-interval 0.25
                        --post-health-interval 0.1
                        --post-expect-status "1:/health/ready=503"
                        --require-log "Optional protocol runtime-ros-offline failed to open"
                        --require-log "alert.event=alert.opened"
                        --require-body "\"status\":\"silenced\""
                        --require-body "local-history"
                        --require-body "\"silenced\":true"
                        --require-log "Protocol gateway started with 2 protocol instance"
                        --require-log "diagnostic.event=failure.detected domain=protocol instance=runtime-ros-offline error.code=PDR-PROTOCOL-ROS-CONNECT_FAILED"
                        --require-body "runtime-udp"
                        --require-body "runtime-ros-offline"
                        --require-body "\"type\":\"udp\""
                        --require-body "\"open\":true"
                        --require-body "\"open\":false"
                        --require-body "PDR-PROTOCOL-ROS-CONNECT_FAILED"
                        --require-body "\"event\":\"failure.detected\""
                        --require-body "\"businessName\":\"runtime.diagnostics\""
                        --require-body "\"businessInstanceId\":\"protocol:runtime-ros-offline\""
                        --require-body "\"category\":\"transient\""
                        --require-body "\"retryable\":true"
                        --require-body "\"occurredAtMicroseconds\":"
                        --require-body "\"action\":\"close\""
                        --require-body "\"action\":\"open\""
                        --require-body "pdr.health.component.samples"
                        --require-body "pdr.diagnostics.failure.samples"
                        --require-body "\"schemaVersion\":2"
                        --require-body "PDR-HEALTH-PROTOCOL-REQUIRED_CLOSED"
                        --require-body "\"affected\":\\[\"runtime-udp\"\\]"
                        --forbid-body "\"businessName\":\"主子进程Fast-DDS心跳\""
                        --require-log "Internal subprocess transport heartbeat disabled: no subprocess is running"
                        --report "${CMAKE_BINARY_DIR}/reports/runtime-web-protocol-diagnostics.json")
                set_tests_properties(runtime-web-protocol-diagnostics PROPERTIES
                    LABELS "runtime;protocol;release;webui"
                    RESOURCE_LOCK pdr_runtime_http
                    TIMEOUT 45)
                add_test(NAME runtime-webevent-auth-integration
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_webevent_auth_integration.py"
                        --python "${Python3_EXECUTABLE}"
                        --runtime-smoke "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                        --executable "$<TARGET_FILE:pdr-runtime>"
                        --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                        --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                        --path "${PDR_INSTALL_PREFIX}/bin"
                        --path "$<TARGET_FILE_DIR:pdr-runtime>"
                        --report "${CMAKE_BINARY_DIR}/reports/runtime-webevent-auth-integration.json")
                set_tests_properties(runtime-webevent-auth-integration PROPERTIES
                    LABELS "runtime;security;integration;webui"
                    RESOURCE_LOCK pdr_runtime_http
                    TIMEOUT 60)
                add_test(NAME runtime-identity-rotation-integration
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_identity_rotation_integration.py"
                        --executable "$<TARGET_FILE:pdr-runtime>"
                        --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                        --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                        --path "${PDR_INSTALL_PREFIX}/bin"
                        --path "$<TARGET_FILE_DIR:pdr-runtime>"
                        --report "${CMAKE_BINARY_DIR}/reports/runtime-identity-rotation-integration.json")
                set_tests_properties(runtime-identity-rotation-integration PROPERTIES
                    LABELS "runtime;security;identity;integration"
                    RESOURCE_LOCK pdr_runtime_http
                    TIMEOUT 45)
                add_test(NAME runtime-alert-debounce
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                        --executable "$<TARGET_FILE:pdr-runtime>"
                        --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                        --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                        --timeout 12
                        --stability-window 2
                        --clear-code-cache
                        --path "${PDR_INSTALL_PREFIX}/bin"
                        --path "$<TARGET_FILE_DIR:pdr-runtime>"
                        --endpoint "/api/v1/alerts"
                        --set "pdr.ros.count=1"
                        --set "pdr.ros.0.id=runtime-ros-debounce"
                        --set "pdr.ros.0.uri=ws://127.0.0.1:1"
                        --set "pdr.ros.0.required=false"
                        --set "pdr.ros.0.autoReconnect=false"
                        --set "pdr.alerts.debounceMilliseconds=10000"
                        --require-body "\"status\":\"pending\""
                        --require-body "\"notified\":false"
                        --forbid-log "alert.event=alert.opened"
                        --report "${CMAKE_BINARY_DIR}/reports/runtime-alert-debounce.json")
                set_tests_properties(runtime-alert-debounce PROPERTIES
                    LABELS "runtime;protocol;fault-injection;release"
                    RESOURCE_LOCK pdr_runtime_http
                    TIMEOUT 30)
                add_test(NAME runtime-alert-history-degraded
                    COMMAND "${Python3_EXECUTABLE}"
                        "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                        --executable "$<TARGET_FILE:pdr-runtime>"
                        --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                        --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                        --timeout 12
                        --stability-window 2
                        --clear-code-cache
                        --path "${PDR_INSTALL_PREFIX}/bin"
                        --path "$<TARGET_FILE_DIR:pdr-runtime>"
                        --endpoint "/api/v1/alerts"
                        --endpoint "/api/v1/alert-history"
                        --set "pdr.alerts.history.path=?:/alerts.jsonl"
                        --require-log "Alert history disabled after initialization failure"
                        --require-body "\"enabled\":false"
                        --report "${CMAKE_BINARY_DIR}/reports/runtime-alert-history-degraded.json")
                set_tests_properties(runtime-alert-history-degraded PROPERTIES
                    LABELS "runtime;fault-injection;release"
                    RESOURCE_LOCK pdr_runtime_http
                    TIMEOUT 30)
            endif()
            add_test(NAME runtime-protocol-gateway-integration
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_protocol_gateway_integration.py"
                    --runtime-smoke "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --install-bin "${PDR_INSTALL_PREFIX}/bin"
                    --cycles 5
                    --max-handle-growth 24
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-protocol-gateway-integration.json")
            set_tests_properties(runtime-protocol-gateway-integration PROPERTIES
                LABELS "runtime;protocol;integration;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 90)
            add_test(NAME runtime-management-persistence-fault-integration
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_management_persistence_fault_integration.py"
                    --runtime-smoke "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --install-bin "${PDR_INSTALL_PREFIX}/bin"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-management-persistence-fault.json")
            set_tests_properties(runtime-management-persistence-fault-integration PROPERTIES
                LABELS "runtime;fault-injection;security;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-restore-acceptance-integration
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_restore_acceptance_integration.py"
                    --python "${Python3_EXECUTABLE}"
                    --pdr "${CMAKE_CURRENT_SOURCE_DIR}/tools/pdr.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --install-bin "${PDR_INSTALL_PREFIX}/bin"
                    --workspace "${CMAKE_BINARY_DIR}/reports/runtime-restore-acceptance-workspace"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-restore-acceptance-integration.json")
            set_tests_properties(runtime-restore-acceptance-integration PROPERTIES
                LABELS "runtime;integration;recovery;security;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-multi-device-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --timeout 20
                    --stability-window 2
                    --clear-code-cache
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --endpoint "/health/detail"
                    --endpoint "/api/v1/devices"
                    --set "pdr.simulation.count=3"
                    --set "pdr.simulation.0.id=simulation-primary"
                    --set "pdr.simulation.1.id=simulation-backup"
                    --set "pdr.simulation.2.id=simulation-diagnostics"
                    --require-log "started with 3 device\\(s\\)"
                    --require-body "\\\"count\\\":3"
                    --require-body "simulation-primary"
                    --require-body "simulation-backup"
                    --require-body "simulation-diagnostics"
                    --require-body "\"sequence\":"
                    --require-body "\"timestampMicroseconds\":"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-multi-device-smoke.json")
            set_tests_properties(runtime-multi-device-smoke PROPERTIES
                LABELS "runtime;device"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-modbus-reference-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/modbus_runtime_smoke.py"
                    --runtime-smoke "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-modbus-reference-smoke.json")
            set_tests_properties(runtime-modbus-reference-smoke PROPERTIES
                LABELS "runtime;device;protocol;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-serial-reference-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --timeout 20
                    --stability-window 2
                    --clear-code-cache
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --endpoint "/api/v1/devices"
                    --set "pdr.serial.count=1"
                    --set "pdr.serial.0.id=serial-reference"
                    --set "pdr.serial.0.transport=loopback"
                    --require-log "started with 2 device"
                    --require-body "serial-reference"
                    --require-body "\"type\":\"serial\""
                    --require-body "\"diagnostics\":"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-serial-reference-smoke.json")
            set_tests_properties(runtime-serial-reference-smoke PROPERTIES
                LABELS "runtime;device;protocol;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-gnss-reference-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --timeout 20
                    --stability-window 2
                    --clear-code-cache
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --endpoint "/api/v1/devices"
                    --set "pdr.gnss.count=1"
                    --set "pdr.gnss.0.id=gnss-reference"
                    --set "pdr.gnss.0.transport=loopback"
                    --set "pdr.gnss.0.required=false"
                    --require-log "started with 2 device"
                    --require-body "gnss-reference"
                    --require-body "\"type\":\"gnss.nmea0183\""
                    --require-body "\"state\":\"offline\""
                    --require-body "\"diagnostics\":"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-gnss-reference-smoke.json")
            set_tests_properties(runtime-gnss-reference-smoke PROPERTIES
                LABELS "runtime;device;protocol;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-xbee-reference-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --timeout 20
                    --stability-window 2
                    --clear-code-cache
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --endpoint "/api/v1/devices"
                    --set "pdr.xbee.count=1"
                    --set "pdr.xbee.0.id=xbee-reference"
                    --set "pdr.xbee.0.transport=loopback"
                    --set "pdr.xbee.0.required=false"
                    --set "pdr.xbee.0.sourceAddress=0013A200405291AB"
                    --set "pdr.xbee.0.analogChannel=0"
                    --require-log "started with 2 device"
                    --require-body "xbee-reference"
                    --require-body "\"type\":\"sensor.xbee.analog\""
                    --require-body "\"state\":\"offline\""
                    --require-body "\"diagnostics\":"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-xbee-reference-smoke.json")
            set_tests_properties(runtime-xbee-reference-smoke PROPERTIES
                LABELS "runtime;device;protocol;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-can-reference-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --timeout 20
                    --stability-window 2
                    --clear-code-cache
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --endpoint "/api/v1/devices"
                    --set "pdr.can.count=1"
                    --set "pdr.can.0.id=can-reference"
                    --set "pdr.can.0.transport=loopback"
                    --set "pdr.can.0.required=false"
                    --set "pdr.can.0.frameId=0x123"
                    --set "pdr.can.0.bitOffset=0"
                    --set "pdr.can.0.bitLength=16"
                    --require-log "started with 2 device"
                    --require-body "can-reference"
                    --require-body "\"type\":\"sensor.can.signal\""
                    --require-body "\"state\":\"offline\""
                    --require-body "\"diagnostics\":"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-can-reference-smoke.json")
            set_tests_properties(runtime-can-reference-smoke PROPERTIES
                LABELS "runtime;device;protocol;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-required-device-readiness
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --timeout 20
                    --stability-window 2
                    --clear-code-cache
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --endpoint "/health/detail"
                    --endpoint "/api/v1/devices"
                    --expect-status "/health/ready=503"
                    --set "pdr.can.count=1"
                    --set "pdr.can.0.id=required-can"
                    --set "pdr.can.0.transport=loopback"
                    --set "pdr.can.0.frameId=0x123"
                    --set "pdr.can.0.bitOffset=0"
                    --set "pdr.can.0.bitLength=16"
                    --require-body "required-can"
                    --require-body "\"status\":\"DEGRADED\""
                    --require-body "\"name\":\"devices\""
                    --require-body "\"ready\":false"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-required-device-readiness.json")
            set_tests_properties(runtime-required-device-readiness PROPERTIES
                LABELS "runtime;device;release;fault-injection"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
            add_test(NAME runtime-linux-sysfs-reference-smoke
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/linux_sysfs_runtime_smoke.py"
                    --runtime-smoke "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
                    --executable "$<TARGET_FILE:pdr-runtime>"
                    --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                    --config "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
                    --path "${PDR_INSTALL_PREFIX}/bin"
                    --path "$<TARGET_FILE_DIR:pdr-runtime>"
                    --report "${CMAKE_BINARY_DIR}/reports/runtime-linux-sysfs-reference-smoke.json")
            set_tests_properties(runtime-linux-sysfs-reference-smoke PROPERTIES
                LABELS "runtime;device;release"
                RESOURCE_LOCK pdr_runtime_http
                TIMEOUT 45)
        endif()
        set_tests_properties(security-config security-policy PROPERTIES LABELS "security")
        set_tests_properties(release-policy release-artifacts dependency-lock release-matrix upgrade-rollback
            PROPERTIES LABELS "release")
    endif()
endif()

# Runtime deployment layout. The current runtime bundles are generated directly
# into the owning process repository and installed into the same layout.
install(DIRECTORY "${PDR_BUNDLE_OUTPUT_DIRECTORY}/"
    DESTINATION "${CMAKE_INSTALL_BINDIR}/bundles"
    FILES_MATCHING PATTERN "*.bndl")
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
               "${PDR_GENERATED_SUBPROCESS_CONFIG}"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-production-identity.properties.example"
              "${CMAKE_CURRENT_SOURCE_DIR}/config/release-pipeline.example.json"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PocoDDSRuntime/examples")
install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/contracts/"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PocoDDSRuntime/contracts")
install(PROGRAMS
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/pdr.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/release_manifest.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/release_qualification.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/external_acceptance.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/evidence_bundle.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/release_pipeline.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/upgrade_manager.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/plugin_manager.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/upgrade_transaction_integration.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/runtime_smoke.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/soak_runner.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/device_acceptance.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/protocol_acceptance.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/security_gate.py"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/tools/pdr.ps1"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")
# A fresh package must be directly startable. Poco's FileChannel does not
# create the parent directory, and the OSP runtime also expects these writable
# roots to exist before the first request or trace is persisted.
install(DIRECTORY DESTINATION "${CMAKE_INSTALL_BINDIR}/logs")
install(DIRECTORY DESTINATION "${CMAKE_INSTALL_BINDIR}/data")
install(DIRECTORY DESTINATION "${CMAKE_INSTALL_BINDIR}/codeCache")
if(WIN32)
    # The official OTLP/HTTP exporter uses the shared curl/OpenSSL runtime on
    # Windows. Package every third-party runtime DLL from the unified prefix;
    # project-owned DLLs are installed from their targets below.
    file(GLOB pdr_third_party_runtime_dlls "${PDR_INSTALL_PREFIX}/bin/*.dll")
    list(FILTER pdr_third_party_runtime_dlls EXCLUDE REGEX
        "/(PDRObservability|PDRBundleManagement|PDRProcessManagement)\\.dll$")
    install(FILES ${pdr_third_party_runtime_dlls}
        DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()

# Public macchina.io platform extensions retained by this runtime.
install(TARGETS CodeGeneration Geo Serial WebTunnel OSP
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY
    "${CMAKE_CURRENT_SOURCE_DIR}/platform/CodeGeneration/include/"
    "${CMAKE_CURRENT_SOURCE_DIR}/platform/Geo/include/"
    "${CMAKE_CURRENT_SOURCE_DIR}/platform/Serial/include/"
    "${CMAKE_CURRENT_SOURCE_DIR}/platform/WebTunnel/include/"
    "${CMAKE_CURRENT_SOURCE_DIR}/platform/OSP/include/"
    DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")

include(CMakePackageConfigHelpers)
set(PDR_PACKAGE_CMAKE_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/PocoDDSRuntime")
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PocoDDSRuntimeConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/PocoDDSRuntimeConfig.cmake"
    INSTALL_DESTINATION "${PDR_PACKAGE_CMAKE_DIR}")
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/pdr-plugin-runtime.json.in"
    "${CMAKE_CURRENT_BINARY_DIR}/pdr-plugin-runtime.json"
    @ONLY)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/PocoDDSRuntimeConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMajorVersion)
install(EXPORT PocoDDSRuntimeTargets
    FILE PocoDDSRuntimeTargets.cmake
    NAMESPACE PocoDDS::
    DESTINATION "${PDR_PACKAGE_CMAKE_DIR}")
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/PocoDDSRuntimeConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/PocoDDSRuntimeConfigVersion.cmake"
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PocoDDSPlugins.cmake"
    DESTINATION "${PDR_PACKAGE_CMAKE_DIR}")
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/pdr-plugin-runtime.json"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")

if(PDR_PROFILE STREQUAL "edge-test" AND PDR_BUILD_QT3D AND
   NOT TARGET pdr-qt3d-subprocess)
    message(FATAL_ERROR
        "edge-test profile requires Qt6 Qt3D when PDR_BUILD_QT3D=ON; "
        "provide Qt6_DIR/CMAKE_PREFIX_PATH or explicitly disable the feature")
endif()

foreach(feature WEBUI LAUNCHER QT3D OBSERVABILITY DATA_MODULES)
    if((feature STREQUAL "WEBUI" AND PDR_BUILD_WEBUI) OR
       (feature STREQUAL "LAUNCHER" AND TARGET pdr-launcher) OR
       (feature STREQUAL "QT3D" AND TARGET pdr-qt3d-subprocess) OR
       (feature STREQUAL "OBSERVABILITY" AND PDR_ENABLE_OBSERVABILITY) OR
       (feature STREQUAL "DATA_MODULES" AND MYIOT_ENABLE_DATA_MODULES))
        set(PDR_PROFILE_${feature} true)
    else()
        set(PDR_PROFILE_${feature} false)
    endif()
endforeach()
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/pdr-profile.json.in"
    "${CMAKE_CURRENT_BINARY_DIR}/pdr-profile.json"
    @ONLY)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/pdr-profile.json"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/PocoDDSRuntime")
