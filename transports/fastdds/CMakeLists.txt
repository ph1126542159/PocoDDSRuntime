add_library(PDRFastDdsTransport STATIC
    src/FastDdsTransport.cpp
    src/Registration.cpp)
add_library(PocoDDS::FastDDSTransport ALIAS PDRFastDdsTransport)
set_target_properties(PDRFastDdsTransport PROPERTIES EXPORT_NAME FastDDSTransport)
target_include_directories(PDRFastDdsTransport
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_features(PDRFastDdsTransport PUBLIC cxx_std_17)
target_compile_definitions(PDRFastDdsTransport PUBLIC PDR_FASTDDS_TRANSPORT_STATIC)
target_link_libraries(PDRFastDdsTransport
    PUBLIC PocoDDS::RuntimeCore
    PRIVATE PocoDDS::FastDDSCore)
pdr_set_warnings(PDRFastDdsTransport)

install(TARGETS PDRFastDdsTransport EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
install(FILES README.md
    DESTINATION "${CMAKE_INSTALL_DOCDIR}/transports/fastdds")

if(BUILD_TESTING)
    add_executable(pdr-fastdds-transport-smoke tests/FastDdsTransportSmoke.cpp)
    target_link_libraries(pdr-fastdds-transport-smoke
        PRIVATE PocoDDS::FastDDSTransport PocoDDS::RuntimeCoreTesting)
    pdr_set_warnings(pdr-fastdds-transport-smoke)
    add_test(NAME fastdds-transport-smoke COMMAND pdr-fastdds-transport-smoke)
    set_tests_properties(fastdds-transport-smoke PROPERTIES
        LABELS "transport;fastdds;integration;fault-injection" TIMEOUT 20)
    if(WIN32)
        set_tests_properties(fastdds-transport-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()

    add_executable(pdr-fastdds-transport-recovery
        tests/FastDdsTransportRecovery.cpp)
    target_link_libraries(pdr-fastdds-transport-recovery
        PRIVATE PocoDDS::FastDDSTransport PocoDDS::RuntimeCore)
    pdr_set_warnings(pdr-fastdds-transport-recovery)
    add_test(NAME fastdds-transport-peer-recovery
        COMMAND pdr-fastdds-transport-recovery)
    set_tests_properties(fastdds-transport-peer-recovery PROPERTIES
        LABELS "transport;fastdds;integration;fault-injection;recovery"
        TIMEOUT 20)
    if(WIN32)
        set_tests_properties(fastdds-transport-peer-recovery PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()

endif()
