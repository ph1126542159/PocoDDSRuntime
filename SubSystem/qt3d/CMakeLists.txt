option(PDR_ENABLE_QT3D_SUBPROCESS
    "Build the Qt3D architecture-validation subprocess" ON)

if(NOT PDR_ENABLE_QT3D_SUBPROCESS)
    return()
endif()

find_package(Qt6 QUIET COMPONENTS Core Gui 3DCore 3DRender 3DExtras)
if(NOT Qt6_FOUND)
    message(STATUS
        "Qt6 Qt3D was not found; pdr-qt3d-subprocess is disabled. "
        "Set CMAKE_PREFIX_PATH to a Qt 6 installation to enable it.")
    return()
endif()

add_executable(pdr-qt3d-subprocess
    src/Qt3DSubprocess.cpp)
target_link_libraries(pdr-qt3d-subprocess PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::3DCore
    Qt6::3DRender
    Qt6::3DExtras
    PocoDDS::Observability
    PocoDDS::FastDDS
    Poco::OSP
    Poco::Util
    Poco::JSON
    Poco::Foundation)
target_compile_definitions(pdr-qt3d-subprocess PRIVATE
    QT_NO_KEYWORDS)
pdr_set_warnings(pdr-qt3d-subprocess)
pdr_configure_subprocess(pdr-qt3d-subprocess)
add_dependencies(pdr-qt3d-subprocess OSP_Core_Bundle_Package)

add_custom_command(TARGET pdr-qt3d-subprocess POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/config/pdr-qt3d-subprocess.properties"
        "$<TARGET_FILE_DIR:pdr-qt3d-subprocess>/pdr-qt3d-subprocess.properties"
    COMMAND ${CMAKE_COMMAND} -E make_directory
        "$<TARGET_FILE_DIR:pdr-qt3d-subprocess>/bundles"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${PDR_BUNDLE_OUTPUT_DIRECTORY}/osp.core_1.7.0.bndl"
        "$<TARGET_FILE_DIR:pdr-qt3d-subprocess>/bundles/"
    VERBATIM)

if(WIN32 AND TARGET Qt6::windeployqt)
    add_custom_command(TARGET pdr-qt3d-subprocess POST_BUILD
        COMMAND $<TARGET_FILE:Qt6::windeployqt>
            --no-translations
            --no-system-d3d-compiler
            "$<TARGET_FILE:pdr-qt3d-subprocess>"
        VERBATIM)
endif()
if(WIN32 AND TARGET Qt6::QOffscreenIntegrationPlugin)
    add_custom_command(TARGET pdr-qt3d-subprocess POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:Qt6::QOffscreenIntegrationPlugin>
            "$<TARGET_FILE_DIR:pdr-qt3d-subprocess>/platforms/"
        VERBATIM)
endif()

if(BUILD_TESTING)
    add_executable(pdr-qt3d-multiprocess-test
        tests/Qt3DMultiprocessTest.cpp)
    target_link_libraries(pdr-qt3d-multiprocess-test PRIVATE
        PocoDDS::Observability
        PocoDDS::ProcessManagement
        Poco::Foundation)
    pdr_set_warnings(pdr-qt3d-multiprocess-test)

    add_test(NAME qt3d-multiprocess-business-trace
        COMMAND pdr-qt3d-multiprocess-test
            $<TARGET_FILE:pdr-qt3d-subprocess>)
    set_tests_properties(qt3d-multiprocess-business-trace PROPERTIES
        TIMEOUT 30)
    if(WIN32)
        set_tests_properties(qt3d-multiprocess-business-trace PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
        set_property(TEST qt3d-multiprocess-business-trace APPEND PROPERTY
            ENVIRONMENT_MODIFICATION
            "PATH=path_list_prepend:${CMAKE_BINARY_DIR}/bin"
            "PATH=path_list_prepend:$<TARGET_FILE_DIR:pdr-qt3d-subprocess>")
    endif()
endif()

install(TARGETS pdr-qt3d-subprocess
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-qt3d-subprocess")
install(FILES config/pdr-qt3d-subprocess.properties
    DESTINATION "${CMAKE_INSTALL_BINDIR}/processes/pdr-qt3d-subprocess")
