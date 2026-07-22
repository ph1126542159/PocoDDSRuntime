add_library(PocoDDSCodeGeneration src/ContractGenerator.cpp)
target_include_directories(PocoDDSCodeGeneration PUBLIC
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
    "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
pdr_set_warnings(PocoDDSCodeGeneration)
add_library(PocoDDS::CodeGeneration ALIAS PocoDDSCodeGeneration)
set_target_properties(PocoDDSCodeGeneration PROPERTIES EXPORT_NAME CodeGeneration)
install(TARGETS PocoDDSCodeGeneration EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
