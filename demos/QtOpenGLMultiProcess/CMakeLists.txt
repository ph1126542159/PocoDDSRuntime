if(NOT PDR_ENABLE_FASTDDS OR NOT PDR_ENABLE_OPENTELEMETRY)
    message(FATAL_ERROR "QtOpenGLMultiProcess requires Fast-DDS and OpenTelemetry")
endif()

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets OpenGL OpenGLWidgets)

add_executable(pdr-qt-opengl-host HostMain.cpp)
target_link_libraries(pdr-qt-opengl-host PRIVATE PocoDDS::Core PocoDDSFastDDS
    PocoDDS::Observability Qt6::Core Qt6::Gui Qt6::Widgets)
target_compile_definitions(pdr-qt-opengl-host PRIVATE
    PDR_QT_CHILD_PATH="$<TARGET_FILE:pdr-qt-opengl-child>")
pdr_set_warnings(pdr-qt-opengl-host)

add_executable(pdr-qt-opengl-child ChildMain.cpp)
target_link_libraries(pdr-qt-opengl-child PRIVATE PocoDDS::Core PocoDDSFastDDS
    PocoDDS::Observability Qt6::Core Qt6::Gui Qt6::Widgets Qt6::OpenGL Qt6::OpenGLWidgets)
pdr_set_warnings(pdr-qt-opengl-child)

add_dependencies(pdr-qt-opengl-host pdr-qt-opengl-child)

if(PDR_BUILD_TESTS)
    add_test(NAME QtOpenGLMultiProcessAcceptance
        COMMAND pdr-qt-opengl-host --acceptance
            "${CMAKE_CURRENT_BINARY_DIR}/qt-acceptance.txt" 188)
    set_tests_properties(QtOpenGLMultiProcessAcceptance PROPERTIES
        TIMEOUT 45
        PASS_REGULAR_EXPRESSION "QT_DDS_TRACE_CRASH_RESTART_PASS"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        ENVIRONMENT_MODIFICATION
            "PATH=path_list_prepend:$<TARGET_FILE_DIR:Qt6::Core>")
endif()
