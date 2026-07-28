add_executable(pdr-runtime
    src/MacchinaServer.cpp)

target_link_libraries(pdr-runtime
    PRIVATE
        PocoDDS::BundleManagement
        PocoDDS::Configuration
        PocoDDS::ProcessManagement
        Poco::OSP
        Poco::Util
        Poco::Net
        Poco::JSON
        Poco::XML
        Poco::Foundation)
if(PDR_ENABLE_OBSERVABILITY)
    target_link_libraries(pdr-runtime PRIVATE
        PocoDDS::Observability
        PocoDDS::FastDDS)
    target_compile_definitions(pdr-runtime PRIVATE PDR_ENABLE_OBSERVABILITY=1)
endif()

pdr_set_warnings(pdr-runtime)
pdr_configure_main_process(pdr-runtime)

if(TARGET pdr-qt3d-subprocess)
    set(PDR_QT3D_SUBPROCESS_ENABLED true)
else()
    set(PDR_QT3D_SUBPROCESS_ENABLED false)
endif()
set(PDR_GENERATED_SUBPROCESS_CONFIG
    "${CMAKE_CURRENT_BINARY_DIR}/pdr-subprocesses.properties")
configure_file(
    "${CMAKE_SOURCE_DIR}/config/pdr-subprocesses.properties.in"
    "${PDR_GENERATED_SUBPROCESS_CONFIG}"
    @ONLY)
set(PDR_GENERATED_SUBPROCESS_CONFIG "${PDR_GENERATED_SUBPROCESS_CONFIG}"
    PARENT_SCOPE)

add_custom_command(TARGET pdr-runtime POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_SOURCE_DIR}/config/pdr-runtime.properties"
        "$<TARGET_FILE_DIR:pdr-runtime>/pdr-runtime.properties"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${PDR_GENERATED_SUBPROCESS_CONFIG}"
        "$<TARGET_FILE_DIR:pdr-runtime>/pdr-subprocesses.properties"
    VERBATIM)

install(TARGETS pdr-runtime
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
