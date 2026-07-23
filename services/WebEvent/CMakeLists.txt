add_library(PDRWebEvent src/WebEventService.cpp)
target_include_directories(PDRWebEvent
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRWebEvent PUBLIC Poco::OSP Poco::Foundation)
pdr_set_warnings(PDRWebEvent)

myiot_add_osp_bundle(PDR_WebEvent_Bundle "pdr.service.webEvent"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS PDRWebEvent PocoDDS::FastDDS Poco::OSP Poco::JSON Poco::Util Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/WebEvent.bndlspec)
pdr_set_warnings(PDR_WebEvent_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-web-event-smoke tests/WebEventSmoke.cpp)
    target_link_libraries(pdr-web-event-smoke PRIVATE PDRWebEvent)
    pdr_set_warnings(pdr-web-event-smoke)
    add_test(NAME web-event-smoke COMMAND pdr-web-event-smoke)
endif()

install(TARGETS PDRWebEvent ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
