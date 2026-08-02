add_executable(pdr-plugin-host src/PluginHost.cpp)
target_link_libraries(pdr-plugin-host PRIVATE
    Poco::OSP
    Poco::Util
    Poco::JSON
    Poco::Foundation)
pdr_set_warnings(pdr-plugin-host)
pdr_configure_subprocess(pdr-plugin-host)

add_custom_command(TARGET pdr-plugin-host POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:pdr-plugin-host>/data"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-plugin-host.properties"
        "$<TARGET_FILE_DIR:pdr-plugin-host>/pdr-plugin-host.properties"
    VERBATIM)

install(TARGETS pdr-plugin-host
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-plugin-host")
install(FILES config/pdr-plugin-host.properties
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-plugin-host")
