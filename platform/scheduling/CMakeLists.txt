add_library(PDRSchedulingCore src/Scheduler.cpp)
add_library(PocoDDS::SchedulingCore ALIAS PDRSchedulingCore)
set_target_properties(PDRSchedulingCore PROPERTIES EXPORT_NAME SchedulingCore)
target_include_directories(PDRSchedulingCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSchedulingCore PUBLIC
    PocoDDS::ResourceGovernanceCore Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRSchedulingCore PUBLIC PDR_SCHEDULING_STATIC)
endif()
pdr_set_warnings(PDRSchedulingCore)

add_library(PDRSchedulingAPI INTERFACE)
add_library(PocoDDS::SchedulingAPI ALIAS PDRSchedulingAPI)
set_target_properties(PDRSchedulingAPI PROPERTIES EXPORT_NAME SchedulingAPI)
target_include_directories(PDRSchedulingAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSchedulingAPI INTERFACE
    PocoDDS::SchedulingCore Poco::OSP Poco::Foundation)
target_compile_definitions(PDRSchedulingAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

add_library(PDRSchedulingConfiguration
    src/ScheduleConfigurationParticipant.cpp)
add_library(PocoDDS::SchedulingConfiguration ALIAS PDRSchedulingConfiguration)
set_target_properties(PDRSchedulingConfiguration PROPERTIES
    EXPORT_NAME SchedulingConfiguration)
target_include_directories(PDRSchedulingConfiguration PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSchedulingConfiguration PUBLIC
    PocoDDS::SchedulingAPI PocoDDS::ConfigTransactionAPI Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRSchedulingConfiguration PUBLIC
        PDR_SCHEDULING_CONFIGURATION_STATIC)
endif()
pdr_set_warnings(PDRSchedulingConfiguration)

target_link_libraries(PDRPlugins INTERFACE
    PocoDDS::SchedulingAPI PocoDDS::SchedulingConfiguration)
target_link_libraries(PDRSDK INTERFACE PocoDDS::SchedulingCore)

if(BUILD_TESTING)
    add_executable(pdr-scheduler-smoke tests/SchedulerSmoke.cpp)
    target_link_libraries(pdr-scheduler-smoke PRIVATE
        PocoDDS::SchedulingCore PocoDDS::ResourceGovernanceCore)
    pdr_set_warnings(pdr-scheduler-smoke)
    add_test(NAME scheduler-smoke COMMAND pdr-scheduler-smoke)
    set_tests_properties(scheduler-smoke PROPERTIES
        LABELS "scheduling;concurrency;backpressure;lifecycle;fault-injection;release")

    add_executable(pdr-schedule-configuration-smoke
        tests/ScheduleConfigurationSmoke.cpp)
    target_link_libraries(pdr-schedule-configuration-smoke PRIVATE
        PocoDDS::SchedulingConfiguration PocoDDS::ConfigTransactionCore
        PocoDDS::ResourceGovernanceCore)
    pdr_set_warnings(pdr-schedule-configuration-smoke)
    add_test(NAME schedule-configuration-smoke
        COMMAND pdr-schedule-configuration-smoke)
    set_tests_properties(schedule-configuration-smoke PROPERTIES
        LABELS "scheduling;configuration;transaction;concurrency;rollback;release")
endif()

install(TARGETS PDRSchedulingCore PDRSchedulingAPI PDRSchedulingConfiguration
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
