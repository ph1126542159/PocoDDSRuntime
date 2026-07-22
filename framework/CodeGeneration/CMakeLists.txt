add_library(PocoDDSCodeGeneration src/ContractGenerator.cpp)
target_include_directories(PocoDDSCodeGeneration PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
pdr_set_warnings(PocoDDSCodeGeneration)
add_library(PocoDDS::CodeGeneration ALIAS PocoDDSCodeGeneration)

