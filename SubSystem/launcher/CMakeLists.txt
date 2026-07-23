add_executable(pdr-launcher src/RuntimeLauncher.cpp)
target_link_libraries(pdr-launcher PRIVATE
    PocoDDS::BundleManagement
    Poco::OSP
    Poco::Util
    Poco::JSON
    Poco::XML
    Poco::Foundation)
pdr_set_warnings(pdr-launcher)
pdr_configure_subprocess(pdr-launcher)

add_custom_command(TARGET pdr-launcher POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-launcher.properties"
        "$<TARGET_FILE_DIR:pdr-launcher>/pdr-launcher.properties"
    VERBATIM)

install(TARGETS pdr-launcher
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher")
install(FILES config/pdr-launcher.properties
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-launcher")
