add_library(PDRProtocolROS
    src/BridgeClient.cpp)
add_library(PocoDDS::ROS ALIAS PDRProtocolROS)

target_include_directories(PDRProtocolROS
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRProtocolROS PUBLIC PocoDDS::Reliability Poco::Foundation Poco::JSON Poco::Net Poco::NetSSL)
pdr_set_warnings(PDRProtocolROS)
set_target_properties(PDRProtocolROS PROPERTIES EXPORT_NAME ROS)

if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    add_executable(pdr-ros-smoke tests/RosSmoke.cpp)
    target_link_libraries(pdr-ros-smoke PRIVATE PocoDDS::ROS)
    pdr_set_warnings(pdr-ros-smoke)
    add_test(NAME ros-smoke COMMAND pdr-ros-smoke)

    add_executable(pdr-ros-bridge-integration tests/RosBridgeIntegration.cpp)
    target_link_libraries(pdr-ros-bridge-integration PRIVATE PocoDDS::ROS Poco::Net Poco::JSON)
    pdr_set_warnings(pdr-ros-bridge-integration)
    add_test(NAME ros-bridge-integration COMMAND pdr-ros-bridge-integration)
    set_tests_properties(ros-bridge-integration PROPERTIES
        LABELS "protocol;fault-injection;release" TIMEOUT 15)

    add_executable(pdr-ros-tls-probe tests/RosTlsProbe.cpp)
    target_link_libraries(pdr-ros-tls-probe PRIVATE PocoDDS::ROS)
    pdr_set_warnings(pdr-ros-tls-probe)
    # The end-to-end probe asserts the SystemMonitoring /api/v1/protocols view.
    # The rosbridge client/probe tests above remain profile-independent.
    if(PDR_ENABLE_OBSERVABILITY AND PDR_OPENSSL_EXECUTABLE AND Python3_EXECUTABLE)
        add_test(NAME ros-tls-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/ros_tls_integration.py"
                --openssl "${PDR_OPENSSL_EXECUTABLE}"
                --probe "$<TARGET_FILE:pdr-ros-tls-probe>"
                --runtime-smoke "${CMAKE_SOURCE_DIR}/tools/runtime_smoke.py"
                --runtime "$<TARGET_FILE:pdr-runtime>"
                --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
                --config "${CMAKE_SOURCE_DIR}/config/pdr-runtime.properties"
                --install-bin "${PDR_INSTALL_PREFIX}/bin"
                --report "${CMAKE_BINARY_DIR}/reports/runtime-ros-tls-integration.json")
        set_tests_properties(ros-tls-integration PROPERTIES
            LABELS "protocol;integration;security;runtime" TIMEOUT 45
            RESOURCE_LOCK pdr_runtime_http)
    endif()
endif()

install(TARGETS PDRProtocolROS EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
