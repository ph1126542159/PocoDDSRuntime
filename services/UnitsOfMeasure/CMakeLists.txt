add_library(PDRUnitsOfMeasure
    src/UCUMEssenceParser.cpp
    src/UnitsOfMeasureService.cpp
    src/UnitsOfMeasureServiceImpl.cpp)

target_include_directories(PDRUnitsOfMeasure
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRUnitsOfMeasure PUBLIC Poco::OSP Poco::XML Poco::Foundation)
pdr_set_warnings(PDRUnitsOfMeasure)

myiot_add_osp_bundle(PDR_UnitsOfMeasure_Bundle "pdr.service.units"
    SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/src/BundleActivator.cpp
    LINK_LIBS
        PDRUnitsOfMeasure
        PocoDDS::FastDDS
        Poco::OSP
        Poco::JSON
        Poco::Util
        Poco::XML
        Poco::Foundation
    INCLUDE_DIRS ${MYIOT_OSP_BUNDLE_INCLUDE_DIRS}
    BUNDLE_SPEC ${CMAKE_CURRENT_SOURCE_DIR}/UnitsOfMeasure.bndlspec)
pdr_set_warnings(PDR_UnitsOfMeasure_Bundle)

if(BUILD_TESTING)
    add_executable(pdr-units-smoke tests/UnitsOfMeasureSmoke.cpp)
    target_link_libraries(pdr-units-smoke PRIVATE PDRUnitsOfMeasure)
    pdr_set_warnings(pdr-units-smoke)
    add_test(NAME units-smoke COMMAND pdr-units-smoke)
endif()

install(TARGETS PDRUnitsOfMeasure ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
