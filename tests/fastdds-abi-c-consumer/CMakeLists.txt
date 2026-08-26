cmake_minimum_required(VERSION 3.24)
project(PocoDDSFastDDSAbiCConsumer LANGUAGES C)

find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS FastDDSAbiV1)

add_executable(pdr-fastdds-abi-c-consumer main.c)
set_target_properties(pdr-fastdds-abi-c-consumer PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO)
target_link_libraries(pdr-fastdds-abi-c-consumer PRIVATE PocoDDS::FastDDSAbiV1)
