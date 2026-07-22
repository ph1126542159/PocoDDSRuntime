find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets OpenGL OpenGLWidgets)

add_executable(pdr-qt-opengl-host HostMain.cpp)
target_link_libraries(pdr-qt-opengl-host PRIVATE PocoDDS::Core Qt6::Core Qt6::Gui Qt6::Widgets)
pdr_set_warnings(pdr-qt-opengl-host)

add_executable(pdr-qt-opengl-child ChildMain.cpp)
target_link_libraries(pdr-qt-opengl-child PRIVATE PocoDDS::Core Qt6::Core Qt6::Gui
    Qt6::Widgets Qt6::OpenGL Qt6::OpenGLWidgets)
pdr_set_warnings(pdr-qt-opengl-child)

