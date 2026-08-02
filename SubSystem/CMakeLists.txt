# Subprocess implementations live below this directory and are independently
# selectable by deployment profile.
if(PDR_BUILD_LAUNCHER)
    add_subdirectory(launcher)
endif()
if(PDR_BUILD_PLUGIN_HOST)
    add_subdirectory(plugin-host)
endif()
if(PDR_BUILD_QT3D)
    add_subdirectory(qt3d)
endif()
