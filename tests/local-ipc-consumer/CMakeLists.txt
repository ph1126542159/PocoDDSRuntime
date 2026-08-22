cmake_minimum_required(VERSION 3.24)
project(PDRLocalIpcConsumer LANGUAGES CXX)

find_package(PDRLocalIpc CONFIG REQUIRED)
find_package(PDRNativeProcess CONFIG REQUIRED)

add_executable(pdr-local-ipc-consumer main.cpp)
target_link_libraries(pdr-local-ipc-consumer
    PRIVATE PocoDDS::LocalIpc PocoDDS::NativeProcess)
target_compile_features(pdr-local-ipc-consumer PRIVATE cxx_std_17)
