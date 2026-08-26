add_executable(pdr-launcher src/RuntimeLauncher.cpp)
target_link_libraries(pdr-launcher PRIVATE
    PocoDDS::BundleManagement
    Poco::OSP
    Poco::Util
    Poco::JSON
    Poco::XML
    Poco::Foundation)
pdr_set_warnings(pdr-launcher)
pdr_configure_subprocess(pdr-launcher)

if(BUILD_TESTING)
    file(SHA256
        "${CMAKE_SOURCE_DIR}/config/fastdds-deployment.properties.example"
        pdr_launcher_fastdds_example_sha256)
    add_executable(pdr-launcher-crash-child tests/CrashOnceChild.cpp)
    pdr_set_warnings(pdr-launcher-crash-child)
    add_executable(pdr-launcher-crash-recovery-test tests/LauncherCrashRecoveryTest.cpp)
    target_link_libraries(pdr-launcher-crash-recovery-test PRIVATE Poco::Foundation)
    target_compile_definitions(pdr-launcher-crash-recovery-test PRIVATE
        PDR_LAUNCHER_TEST_CONFIG="${CMAKE_CURRENT_SOURCE_DIR}/tests/launcher-test.properties")
    pdr_set_warnings(pdr-launcher-crash-recovery-test)
    add_test(NAME launcher-crash-recovery
        COMMAND pdr-launcher-crash-recovery-test
            "$<TARGET_FILE:pdr-launcher>"
            "$<TARGET_FILE:pdr-launcher-crash-child>"
            "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(launcher-crash-recovery PROPERTIES
        LABELS "fault-injection;nightly;process"
        TIMEOUT 15)

    add_executable(pdr-launcher-always-crash-child tests/AlwaysCrashChild.cpp)
    pdr_set_warnings(pdr-launcher-always-crash-child)
    add_executable(pdr-launcher-restart-budget-test tests/LauncherRestartBudgetTest.cpp)
    target_link_libraries(pdr-launcher-restart-budget-test PRIVATE Poco::Foundation)
    target_compile_definitions(pdr-launcher-restart-budget-test PRIVATE
        PDR_LAUNCHER_BUDGET_CONFIG="${CMAKE_CURRENT_SOURCE_DIR}/tests/launcher-budget-test.properties")
    pdr_set_warnings(pdr-launcher-restart-budget-test)
    add_test(NAME launcher-restart-budget
        COMMAND pdr-launcher-restart-budget-test
            "$<TARGET_FILE:pdr-launcher>"
            "$<TARGET_FILE:pdr-launcher-always-crash-child>"
            "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(launcher-restart-budget PROPERTIES
        LABELS "fault-injection;process;recovery;reliability"
        TIMEOUT 15)

    add_executable(pdr-launcher-deployment-child tests/DeploymentChild.cpp)
    pdr_set_warnings(pdr-launcher-deployment-child)
    add_executable(pdr-launcher-deployment-test tests/LauncherDeploymentTest.cpp)
    target_link_libraries(pdr-launcher-deployment-test PRIVATE
        PocoDDS::BundleManagement
        Poco::Foundation)
    pdr_set_warnings(pdr-launcher-deployment-test)
    add_dependencies(pdr-launcher-deployment-test
        pdr-launcher
        pdr-launcher-deployment-child)
    add_test(NAME launcher-bundle-deployment
        COMMAND pdr-launcher-deployment-test
            "$<TARGET_FILE:pdr-launcher>"
            "$<TARGET_FILE:pdr-launcher-deployment-child>"
            "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(launcher-bundle-deployment PROPERTIES
        LABELS "fault-injection;process;reliability;bundle-deployment"
        TIMEOUT 45)
    if(WIN32)
        set_property(TEST launcher-bundle-deployment PROPERTY
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-launcher-heartbeat-silent-child tests/HeartbeatSilentChild.cpp)
    pdr_set_warnings(pdr-launcher-heartbeat-silent-child)
    add_executable(pdr-launcher-missing-heartbeat-test tests/LauncherMissingHeartbeatTest.cpp)
    target_link_libraries(pdr-launcher-missing-heartbeat-test PRIVATE Poco::Foundation)
    pdr_set_warnings(pdr-launcher-missing-heartbeat-test)
    add_test(NAME launcher-missing-heartbeat
        COMMAND pdr-launcher-missing-heartbeat-test
            "$<TARGET_FILE:pdr-launcher>"
            "$<TARGET_FILE:pdr-launcher-heartbeat-silent-child>"
            "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(launcher-missing-heartbeat PROPERTIES
        LABELS "fault-injection;process;reliability;watchdog"
        TIMEOUT 15)

    add_executable(pdr-launcher-preflight-probe tests/PreflightProbe.cpp)
    target_link_libraries(pdr-launcher-preflight-probe PRIVATE Poco::Foundation)
    pdr_set_warnings(pdr-launcher-preflight-probe)
    add_executable(pdr-launcher-preflight-child tests/PreflightChild.cpp)
    pdr_set_warnings(pdr-launcher-preflight-child)
    add_executable(pdr-launcher-preflight-test tests/LauncherPreflightTest.cpp)
    target_link_libraries(pdr-launcher-preflight-test PRIVATE Poco::Foundation)
    pdr_set_warnings(pdr-launcher-preflight-test)
    add_dependencies(pdr-launcher-preflight-test
        pdr-launcher
        pdr-launcher-preflight-probe
        pdr-launcher-preflight-child
        pdr-fastdds-profile-check)
    add_test(NAME launcher-preflight-gate
        COMMAND pdr-launcher-preflight-test
            "$<TARGET_FILE:pdr-launcher>"
            "$<TARGET_FILE:pdr-launcher-preflight-probe>"
            "$<TARGET_FILE:pdr-launcher-preflight-child>"
            "${CMAKE_CURRENT_BINARY_DIR}"
            "$<TARGET_FILE:pdr-fastdds-profile-check>"
            "${CMAKE_SOURCE_DIR}/config/fastdds-deployment.properties.example"
            "${pdr_launcher_fastdds_example_sha256}")
    set_tests_properties(launcher-preflight-gate PROPERTIES
        LABELS "configuration;fault-injection;process;reliability;preflight"
        TIMEOUT 20)
    if(WIN32)
        set_property(TEST launcher-preflight-gate PROPERTY
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    if(WIN32)
        add_executable(pdr-launcher-job-limit-child tests/JobLimitProbeChild.cpp)
        target_link_libraries(pdr-launcher-job-limit-child PRIVATE Poco::Foundation)
        pdr_set_warnings(pdr-launcher-job-limit-child)
        add_executable(pdr-launcher-job-object-test tests/LauncherJobObjectTest.cpp)
        target_link_libraries(pdr-launcher-job-object-test PRIVATE Poco::Foundation)
        pdr_set_warnings(pdr-launcher-job-object-test)
        add_test(NAME launcher-job-object-limit
            COMMAND pdr-launcher-job-object-test
                "$<TARGET_FILE:pdr-launcher>"
                "$<TARGET_FILE:pdr-launcher-job-limit-child>"
                "${CMAKE_CURRENT_BINARY_DIR}")
        set_tests_properties(launcher-job-object-limit PROPERTIES
            LABELS "fault-injection;process;reliability;resource-limit;windows"
            TIMEOUT 15)
    endif()
endif()

add_custom_command(TARGET pdr-launcher POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-launcher.properties"
        "$<TARGET_FILE_DIR:pdr-launcher>/pdr-launcher.properties"
    VERBATIM)

install(TARGETS pdr-launcher
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher")
# Keep the Launcher and its internal deployment ABI together. On Windows the
# executable directory wins DLL lookup, preventing an older SDK/runtime prefix
# on PATH from satisfying this private dependency.
if(WIN32)
    install(FILES "$<TARGET_FILE:PDRBundleManagement>"
        DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher")
endif()
install(FILES config/pdr-launcher.properties
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher")
install(DIRECTORY
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher/logs")
install(DIRECTORY
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher/bundles")
