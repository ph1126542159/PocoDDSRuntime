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
        LABELS "fault-injection;process;reliability"
        TIMEOUT 15)

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
install(FILES config/pdr-launcher.properties
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher")
