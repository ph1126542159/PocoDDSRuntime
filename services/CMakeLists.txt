# Every direct child with a CMakeLists.txt is an independently owned service.
# New services are discovered automatically; service-local CMake owns sources,
# tests, Bundle packaging and install rules.
pdr_add_component_directories("${CMAKE_CURRENT_SOURCE_DIR}"
    FOLDER "Services")
