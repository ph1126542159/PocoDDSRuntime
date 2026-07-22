cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntimeInstallConsumer LANGUAGES CXX)

find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED)

add_executable(pdr-install-consumer main.cpp)
target_link_libraries(pdr-install-consumer PRIVATE
    PocoDDS::Core
    PocoDDS::OSP
    PocoDDS::CodeGeneration
    PocoDDS::FastDDS
    PocoDDS::Observability
    PocoDDS::Admin)
target_compile_features(pdr-install-consumer PRIVATE cxx_std_17)
