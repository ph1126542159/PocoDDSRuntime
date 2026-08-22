myiot_add_osp_bundle(PDR_DiagnosticTerminal_Bundle "pdr.platform.diagnosticTerminal"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/DiagnosticTerminal.cpp
    LINK_LIBS
        PocoDDS::Configuration
        PocoDDS::DeviceCore
        PocoDDS::FastDDS
        PocoDDS::Health
        PocoDDS::Observability
        PocoDDS::ProcessManagement
        PocoDDS::Protocols
        PocoDDS::Security
        Poco::OSPWeb
        Poco::OSP
        Poco::JSON
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${PROJECT_SOURCE_DIR}/platform/OSP/ManagementAuth/include
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/DiagnosticTerminal.bndlspec)
target_compile_definitions(PDR_DiagnosticTerminal_Bundle PRIVATE
    PDR_RUNTIME_VERSION="${PROJECT_VERSION}")
pdr_set_warnings(PDR_DiagnosticTerminal_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-diagnostic-provider-smoke tests/DiagnosticProviderSmoke.cpp)
    target_include_directories(pdr-diagnostic-provider-smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include)
    target_link_libraries(pdr-diagnostic-provider-smoke PRIVATE Poco::OSP Poco::Foundation)
    pdr_set_warnings(pdr-diagnostic-provider-smoke)
    add_test(NAME diagnostic-provider-smoke COMMAND pdr-diagnostic-provider-smoke)
endif()

install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
