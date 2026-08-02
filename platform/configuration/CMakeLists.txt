add_library(PDRConfiguration
    src/ConfigurationValidator.cpp
    src/IndexedConfiguration.cpp)
add_library(PocoDDS::Configuration ALIAS PDRConfiguration)
set_target_properties(PDRConfiguration PROPERTIES EXPORT_NAME Configuration)
target_include_directories(PDRConfiguration PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRConfiguration PUBLIC PocoDDS::Security Poco::Util Poco::Foundation)
pdr_set_warnings(PDRConfiguration)

add_executable(pdr-config-check tools/ConfigCheck.cpp)
target_link_libraries(pdr-config-check PRIVATE PocoDDS::Configuration Poco::Util Poco::Foundation)
pdr_set_warnings(pdr-config-check)

if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    add_executable(pdr-configuration-smoke tests/ConfigurationSmoke.cpp)
    target_link_libraries(pdr-configuration-smoke PRIVATE PocoDDS::Configuration)
    pdr_set_warnings(pdr-configuration-smoke)
    add_test(NAME configuration-smoke COMMAND pdr-configuration-smoke)
    if(Python3_Interpreter_FOUND)
        add_test(NAME configuration-file-check
            COMMAND "${CMAKE_COMMAND}"
                "-DPDR_CONFIG_CHECK=$<TARGET_FILE:pdr-config-check>"
                "-DPDR_PYTHON=${Python3_EXECUTABLE}"
                "-DPDR_TOOL=${CMAKE_SOURCE_DIR}/tools/pdr.py"
                "-DPDR_VALID_CONFIG=${CMAKE_SOURCE_DIR}/config/pdr-runtime.properties"
                "-DPDR_TEST_DIR=${CMAKE_CURRENT_BINARY_DIR}/config-check-test"
                -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunConfigCheckTest.cmake")
        set_tests_properties(configuration-file-check PROPERTIES LABELS "release;configuration")
    endif()
endif()

install(TARGETS PDRConfiguration EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(TARGETS pdr-config-check RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")

add_executable(pdr-signature-check tools/ReleaseSignatureCheck.cpp)
target_link_libraries(pdr-signature-check PRIVATE Poco::JSON Poco::Foundation OpenSSL::Crypto)
pdr_set_warnings(pdr-signature-check)
install(TARGETS pdr-signature-check RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
