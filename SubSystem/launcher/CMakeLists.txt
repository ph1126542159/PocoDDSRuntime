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
