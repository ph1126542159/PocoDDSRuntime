# Subprocess implementations live below this directory.  Known framework
# processes retain profile switches; project-specific children are discovered
# automatically and own any additional enable switch in their local CMake.
set(pdr_disabled_subsystems)
if(NOT PDR_BUILD_LAUNCHER)
    list(APPEND pdr_disabled_subsystems launcher)
endif()
if(NOT PDR_BUILD_PLUGIN_HOST)
    list(APPEND pdr_disabled_subsystems plugin-host)
endif()
if(NOT PDR_BUILD_QT3D)
    list(APPEND pdr_disabled_subsystems qt3d)
endif()

pdr_add_component_directories("${CMAKE_CURRENT_SOURCE_DIR}"
    FOLDER "SubSystem"
    EXCLUDE ${pdr_disabled_subsystems})
