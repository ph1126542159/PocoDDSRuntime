cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntimeSDKConsumer LANGUAGES CXX)

find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED)

add_executable(pdr-sdk-consumer main.cpp)
target_compile_features(pdr-sdk-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-sdk-consumer PRIVATE PocoDDS::SDK)
