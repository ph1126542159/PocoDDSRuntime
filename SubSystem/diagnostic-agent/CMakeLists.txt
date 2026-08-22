add_executable(pdr-diagnostic-agent src/DiagnosticAgent.cpp)
target_link_libraries(pdr-diagnostic-agent PRIVATE
    Poco::JSON
    Poco::Foundation)
if(WIN32)
    target_link_libraries(pdr-diagnostic-agent PRIVATE dbghelp iphlpapi psapi ws2_32)
endif()
pdr_set_warnings(pdr-diagnostic-agent)
pdr_configure_subprocess(pdr-diagnostic-agent)

if(BUILD_TESTING)
    add_test(NAME diagnostic-agent-self-status
        COMMAND pdr-diagnostic-agent status --pid self)
    add_test(NAME diagnostic-agent-self-threads
        COMMAND pdr-diagnostic-agent threads --pid self)
    set_tests_properties(diagnostic-agent-self-status diagnostic-agent-self-threads
        PROPERTIES LABELS "diagnostics;process" TIMEOUT 10)
endif()

install(TARGETS pdr-diagnostic-agent
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-diagnostic-agent")
