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
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
set(PDR_PROCESS_OUTPUT_ROOT "${CMAKE_BINARY_DIR}/bin")
set(PDR_RUNTIME_PROCESS_DIRECTORY "${PDR_PROCESS_OUTPUT_ROOT}")
set(PDR_SUBPROCESS_OUTPUT_ROOT "${PDR_PROCESS_OUTPUT_ROOT}/processes")
set(PDR_BUNDLE_OUTPUT_DIRECTORY "${PDR_RUNTIME_PROCESS_DIRECTORY}/bundles")
set(PDR_TEST_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/bin")
if(CMAKE_CONFIGURATION_TYPES)
    foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
        string(TOUPPER "${configuration}" configuration_upper)
        set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${configuration_upper} "${CMAKE_BINARY_DIR}/bin")
        set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_${configuration_upper} "${CMAKE_BINARY_DIR}/bin")
        set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY_${configuration_upper} "${CMAKE_BINARY_DIR}/lib")
    endforeach()
endif()

set(_pdr_install_prefix "${CMAKE_CURRENT_SOURCE_DIR}/build/install")
set(PDR_INSTALL_PREFIX "${_pdr_install_prefix}"
    CACHE PATH "Unified runtime and third-party installation prefix")
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
set(SHARED_LIBRARY_VERSION 1 CACHE STRING "Compatibility version for migrated platform libraries")

include(PDRWarnings)
include(PDRProcessLayout)
include(PDRPoco)
include(PDRFastDDS)
include(PDRPahoMqtt)
pdr_require_poco()
pdr_require_fastdds()
pdr_require_paho_mqtt()
if(PDR_ENABLE_OBSERVABILITY)
    include(PDROpenTelemetry)
    pdr_require_opentelemetry()
endif()

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
add_subdirectory(platform/CodeGeneration)
add_subdirectory(platform/Geo)
add_subdirectory(platform/Serial)
add_subdirectory(platform/WebTunnel)
add_subdirectory(platform/OSP)
add_subdirectory(platform/BundleManagement)
add_subdirectory(platform/ProcessManagement)

set(CMAKE_FOLDER "Protocols")
add_subdirectory(platform/protocols)

set(CMAKE_FOLDER "Devices")
add_subdirectory(platform/devices)

if(PDR_ENABLE_OBSERVABILITY)
    set(CMAKE_FOLDER "Observability")
    add_subdirectory(platform/observability)
endif()

set(CMAKE_FOLDER "Communication")
add_subdirectory(platform/DDS)

set(CMAKE_FOLDER "Services")
add_subdirectory(services)

set(CMAKE_FOLDER "Applications")
add_subdirectory(launcher)
add_subdirectory(webui)
add_subdirectory(server)

unset(CMAKE_FOLDER)
pdr_configure_test_output_tree("${CMAKE_CURRENT_SOURCE_DIR}")

# Runtime deployment layout. The current runtime bundles are generated directly
# into the owning process repository and installed into the same layout.
install(DIRECTORY "${PDR_BUNDLE_OUTPUT_DIRECTORY}/"
    DESTINATION "${CMAKE_INSTALL_BINDIR}/bundles"
    FILES_MATCHING PATTERN "*.bndl")
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-runtime.properties"
              "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-subprocesses.properties"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")

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
