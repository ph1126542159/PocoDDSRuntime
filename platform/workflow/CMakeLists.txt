add_library(PDRWorkflowAPI INTERFACE)
add_library(PocoDDS::WorkflowAPI ALIAS PDRWorkflowAPI)
set_target_properties(PDRWorkflowAPI PROPERTIES EXPORT_NAME WorkflowAPI)
target_include_directories(PDRWorkflowAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRWorkflowAPI INTERFACE Poco::OSP Poco::Foundation)
target_compile_definitions(PDRWorkflowAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

add_library(PDRWorkflowCore
    src/SqliteWorkflowStore.cpp
    src/WorkflowEngine.cpp)
add_library(PocoDDS::WorkflowCore ALIAS PDRWorkflowCore)
set_target_properties(PDRWorkflowCore PROPERTIES EXPORT_NAME WorkflowCore)
target_include_directories(PDRWorkflowCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRWorkflowCore
    PUBLIC PocoDDS::WorkflowAPI Poco::Data Poco::DataSQLite Poco::JSON Poco::Foundation)
pdr_set_warnings(PDRWorkflowCore)

if(BUILD_TESTING)
    add_executable(pdr-workflow-runtime-smoke tests/WorkflowRuntimeSmoke.cpp)
    target_link_libraries(pdr-workflow-runtime-smoke PRIVATE PocoDDS::WorkflowCore)
    pdr_set_warnings(pdr-workflow-runtime-smoke)
    add_test(NAME workflow-runtime-smoke COMMAND pdr-workflow-runtime-smoke)
    set_tests_properties(workflow-runtime-smoke PROPERTIES
        LABELS "workflow;recovery;release")
endif()

install(TARGETS PDRWorkflowAPI PDRWorkflowCore
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
