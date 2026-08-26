cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntimeSDKConsumer LANGUAGES CXX)

option(PDR_SDK_CONSUMER_PROTOCOLS "Exercise the installed protocol SDK" ON)
option(PDR_SDK_CONSUMER_UNKNOWN_COMPONENT "Exercise unknown-component rejection" OFF)
if(PDR_SDK_CONSUMER_UNKNOWN_COMPONENT)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS DoesNotExist)
elseif(PDR_SDK_CONSUMER_PROTOCOLS)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS
        SDK Protocols FastDDSAbiV1
        MembershipAPI MembershipCore MembershipPersistence
        ServiceDirectoryAPI ServiceDirectoryCore
        ServiceClientAPI ServiceClientCore ServiceClientTesting)
else()
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)
endif()

if(PDR_SDK_CONSUMER_PROTOCOLS)
    add_executable(pdr-membership-sdk-consumer membership.cpp)
    target_compile_features(pdr-membership-sdk-consumer PRIVATE cxx_std_17)
    target_link_libraries(pdr-membership-sdk-consumer PRIVATE
        PocoDDS::MembershipAPI
        PocoDDS::MembershipCore
        PocoDDS::MembershipPersistence)

    add_executable(pdr-service-directory-sdk-consumer service_directory.cpp)
    target_compile_features(pdr-service-directory-sdk-consumer PRIVATE cxx_std_17)
    target_link_libraries(pdr-service-directory-sdk-consumer PRIVATE
        PocoDDS::ServiceDirectoryAPI
        PocoDDS::ServiceDirectoryCore)

    add_executable(pdr-service-client-sdk-consumer service_client.cpp)
    target_compile_features(pdr-service-client-sdk-consumer PRIVATE cxx_std_17)
    target_link_libraries(pdr-service-client-sdk-consumer PRIVATE
        PocoDDS::ServiceClientAPI
        PocoDDS::ServiceClientCore
        PocoDDS::ServiceClientTesting)
endif()

add_executable(pdr-sdk-consumer main.cpp)
target_compile_features(pdr-sdk-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-sdk-consumer PRIVATE PocoDDS::SDK)
if(PDR_SDK_CONSUMER_PROTOCOLS)
    target_link_libraries(pdr-sdk-consumer PRIVATE
        PocoDDS::Protocols
        PocoDDS::FastDDSAbiV1)
    target_compile_definitions(pdr-sdk-consumer PRIVATE PDR_SDK_CONSUMER_PROTOCOLS=1)
endif()
