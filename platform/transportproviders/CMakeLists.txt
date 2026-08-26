add_library(PDRTransportProviderAPI INTERFACE)
add_library(PocoDDS::TransportProviderAPI ALIAS PDRTransportProviderAPI)
set_target_properties(PDRTransportProviderAPI PROPERTIES EXPORT_NAME TransportProviderAPI)
target_include_directories(PDRTransportProviderAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRTransportProviderAPI INTERFACE
    PocoDDS::RuntimeCore
    Poco::OSP
    Poco::Foundation)
target_compile_definitions(PDRTransportProviderAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

add_library(PDRTransportProviderCore
    src/ProviderRegistration.cpp)
add_library(PocoDDS::TransportProviderCore ALIAS PDRTransportProviderCore)
set_target_properties(PDRTransportProviderCore PROPERTIES EXPORT_NAME TransportProviderCore)
target_include_directories(PDRTransportProviderCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRTransportProviderCore PUBLIC
    PocoDDS::TransportProviderAPI)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRTransportProviderCore PUBLIC
        PDR_TRANSPORT_PROVIDER_STATIC)
endif()
pdr_set_warnings(PDRTransportProviderCore)

# OSP plug-ins receive only the stable provider contract. Concrete transports
# and the catalog implementation remain independently owned targets.
target_link_libraries(PDRPlugins INTERFACE PocoDDS::TransportProviderAPI)

if(BUILD_TESTING)
    add_executable(pdr-transport-provider-registry-smoke
        tests/TransportProviderRegistrySmoke.cpp)
    target_link_libraries(pdr-transport-provider-registry-smoke PRIVATE
        PocoDDS::TransportProviderCore)
    pdr_set_warnings(pdr-transport-provider-registry-smoke)
    add_test(NAME transport-provider-registry-smoke
        COMMAND pdr-transport-provider-registry-smoke)
    set_tests_properties(transport-provider-registry-smoke PROPERTIES
        LABELS "transport;plugin;contract;concurrency")
endif()

install(TARGETS PDRTransportProviderAPI PDRTransportProviderCore
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
