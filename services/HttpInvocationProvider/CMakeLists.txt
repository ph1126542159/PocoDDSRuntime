add_library(PDRHttpInvocationProviderCore STATIC
    src/HttpInvocationProvider.cpp)
add_library(PocoDDS::HttpInvocationProviderCore ALIAS
    PDRHttpInvocationProviderCore)
target_include_directories(PDRHttpInvocationProviderCore
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(PDRHttpInvocationProviderCore PUBLIC cxx_std_17)
target_link_libraries(PDRHttpInvocationProviderCore
    PUBLIC PocoDDS::ServiceClientAPI
    PRIVATE
        PocoDDS::Security
        Poco::NetSSL
        Poco::Net
        Poco::Foundation)
pdr_set_warnings(PDRHttpInvocationProviderCore)

myiot_add_osp_bundle(PDR_HttpInvocationProvider_Bundle
    "pdr.service.httpInvocationProvider"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PocoDDS::HttpInvocationProviderCore
        PocoDDS::ServiceClientAPI
        PocoDDS::Health
        Poco::OSP
        Poco::NetSSL
        Poco::Net
        Poco::Util
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/HttpInvocationProvider.bndlspec)
pdr_set_warnings(PDR_HttpInvocationProvider_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-http-invocation-provider-smoke
        tests/HttpInvocationProviderSmoke.cpp)
    target_link_libraries(pdr-http-invocation-provider-smoke
        PRIVATE
            PocoDDS::HttpInvocationProviderCore
            PocoDDS::ServiceClientTesting
            Poco::Net
            Poco::Foundation)
    pdr_set_warnings(pdr-http-invocation-provider-smoke)
    add_test(NAME http-invocation-provider-smoke
        COMMAND pdr-http-invocation-provider-smoke)
    set_tests_properties(http-invocation-provider-smoke PROPERTIES
        LABELS "service-client;provider;http;security;integration"
        TIMEOUT 20)
    if(WIN32)
        set_tests_properties(http-invocation-provider-smoke PROPERTIES
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${PDR_INSTALL_PREFIX}/bin;PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin")
    endif()
endif()
