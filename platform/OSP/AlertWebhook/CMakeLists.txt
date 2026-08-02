myiot_add_osp_bundle(PDR_AlertWebhook_Bundle "pdr.alert.webhook"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/AlertWebhook.cpp
    LINK_LIBS
        PocoDDS::Configuration
        PocoDDS::Reliability
        Poco::OSP
        Poco::JSON
        Poco::NetSSL
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/AlertWebhook.bndlspec)
pdr_set_warnings(PDR_AlertWebhook_Bundle)

if(BUILD_TESTING)
    find_program(PDR_ALERT_WEBHOOK_OPENSSL_EXECUTABLE openssl
        HINTS "C:/Program Files/Git/usr/bin" "C:/Program Files/OpenSSL-Win64/bin")
    if(NOT Python3_EXECUTABLE)
        find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    endif()
endif()
if(BUILD_TESTING AND PDR_ALERT_WEBHOOK_OPENSSL_EXECUTABLE AND Python3_EXECUTABLE)
    add_test(NAME alert-webhook-tls-integration
        COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_SOURCE_DIR}/tools/alert_webhook_tls_integration.py"
            --openssl "${PDR_ALERT_WEBHOOK_OPENSSL_EXECUTABLE}"
            --runtime-smoke "${CMAKE_SOURCE_DIR}/tools/runtime_smoke.py"
            --runtime "$<TARGET_FILE:pdr-runtime>"
            --working-directory "$<TARGET_FILE_DIR:pdr-runtime>"
            --config "${CMAKE_SOURCE_DIR}/config/pdr-runtime.properties"
            --install-bin "${PDR_INSTALL_PREFIX}/bin"
            --report "${CMAKE_BINARY_DIR}/reports/runtime-alert-webhook-tls.json")
    set_tests_properties(alert-webhook-tls-integration PROPERTIES
        LABELS "runtime;integration;security;release;fault-injection"
        RESOURCE_LOCK pdr_runtime_http
        TIMEOUT 60)
endif()
