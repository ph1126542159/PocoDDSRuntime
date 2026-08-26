myiot_add_osp_bundle(PDR_ConfigurationRuntime_Bundle "pdr.service.configurationRuntime"
    SOURCES
        ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
        ${CMAKE_CURRENT_SOURCE_DIR}/src/ParticipantAdmissionState.cpp
        ${CMAKE_CURRENT_SOURCE_DIR}/src/ParticipantExpectationState.cpp
        ${CMAKE_CURRENT_SOURCE_DIR}/src/KeyLifecycleState.cpp
    LINK_LIBS
        PocoDDS::Configuration
        PocoDDS::CapabilitiesAPI
        PocoDDS::ConfigTransactionCore
        PocoDDS::Security
        PocoDDS::Health
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Data
        Poco::DataSQLite
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${PROJECT_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/ConfigurationRuntime.bndlspec)
pdr_set_warnings(PDR_ConfigurationRuntime_Bundle)
target_compile_definitions(PDR_ConfigurationRuntime_Bundle PRIVATE
    PDR_RUNTIME_VERSION="${PROJECT_VERSION}")

if(BUILD_TESTING)
    add_executable(pdr-configuration-participant-admission-smoke
        tests/ParticipantAdmissionStateSmoke.cpp
        src/ParticipantAdmissionState.cpp)
    target_include_directories(pdr-configuration-participant-admission-smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(pdr-configuration-participant-admission-smoke PRIVATE
        PocoDDS::ConfigTransactionAPI
        PocoDDS::Health)
    pdr_set_warnings(pdr-configuration-participant-admission-smoke)
    add_test(NAME configuration-participant-admission-smoke
        COMMAND pdr-configuration-participant-admission-smoke)
    set_tests_properties(configuration-participant-admission-smoke PROPERTIES
        LABELS "configuration;transaction;health;negative;fault-injection;recovery;release")

    add_executable(pdr-configuration-participant-expectation-smoke
        tests/ParticipantExpectationStateSmoke.cpp
        src/ParticipantExpectationState.cpp)
    target_include_directories(pdr-configuration-participant-expectation-smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(pdr-configuration-participant-expectation-smoke PRIVATE
        PocoDDS::ConfigTransactionAPI
        PocoDDS::Health
        Poco::JSON
        Poco::Foundation)
    pdr_set_warnings(pdr-configuration-participant-expectation-smoke)
    add_test(NAME configuration-participant-expectation-smoke
        COMMAND pdr-configuration-participant-expectation-smoke)
    set_tests_properties(configuration-participant-expectation-smoke PROPERTIES
        LABELS "configuration;contract;dependency;health;negative;fault-injection;recovery;release")

    add_executable(pdr-configuration-key-lifecycle-state-smoke
        tests/KeyLifecycleStateSmoke.cpp
        src/KeyLifecycleState.cpp)
    target_include_directories(pdr-configuration-key-lifecycle-state-smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(pdr-configuration-key-lifecycle-state-smoke PRIVATE
        PocoDDS::ConfigTransactionAPI
        PocoDDS::Health
        Poco::JSON
        Poco::Foundation)
    pdr_set_warnings(pdr-configuration-key-lifecycle-state-smoke)
    add_test(NAME configuration-key-lifecycle-state-smoke
        COMMAND pdr-configuration-key-lifecycle-state-smoke)
    set_tests_properties(configuration-key-lifecycle-state-smoke PROPERTIES
        LABELS "configuration;migration;deprecation;ownership;health;negative;fault-injection;recovery;release")
endif()
