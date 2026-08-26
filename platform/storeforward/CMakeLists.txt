add_library(PDRStoreForwardAPI INTERFACE)
add_library(PocoDDS::StoreForwardAPI ALIAS PDRStoreForwardAPI)
set_target_properties(PDRStoreForwardAPI PROPERTIES EXPORT_NAME StoreForwardAPI)
target_include_directories(PDRStoreForwardAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRStoreForwardAPI INTERFACE Poco::OSP Poco::Foundation)
target_compile_definitions(PDRStoreForwardAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

add_library(PDRStoreForwardCore
    src/OutboxEngine.cpp
    src/SqliteOutboxStore.cpp)
add_library(PocoDDS::StoreForwardCore ALIAS PDRStoreForwardCore)
set_target_properties(PDRStoreForwardCore PROPERTIES EXPORT_NAME StoreForwardCore)
target_include_directories(PDRStoreForwardCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRStoreForwardCore
    PUBLIC PocoDDS::StoreForwardAPI Poco::Data Poco::DataSQLite Poco::JSON Poco::Foundation)
pdr_set_warnings(PDRStoreForwardCore)

if(BUILD_TESTING)
    add_executable(pdr-store-forward-smoke tests/StoreForwardSmoke.cpp)
    target_link_libraries(pdr-store-forward-smoke PRIVATE PocoDDS::StoreForwardCore)
    pdr_set_warnings(pdr-store-forward-smoke)
    add_test(NAME store-forward-smoke COMMAND pdr-store-forward-smoke)
    set_tests_properties(store-forward-smoke PROPERTIES
        LABELS "store-forward;recovery;release")
endif()

install(TARGETS PDRStoreForwardAPI PDRStoreForwardCore
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
