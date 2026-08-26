add_library(PDRMembershipCore src/Membership.cpp)
add_library(PocoDDS::MembershipCore ALIAS PDRMembershipCore)
set_target_properties(PDRMembershipCore PROPERTIES EXPORT_NAME MembershipCore)
target_include_directories(PDRMembershipCore PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRMembershipCore PUBLIC Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRMembershipCore PUBLIC PDR_MEMBERSHIP_STATIC)
endif()
pdr_set_warnings(PDRMembershipCore)

add_library(PDRMembershipPersistence src/SqliteIncarnationStore.cpp)
add_library(PocoDDS::MembershipPersistence ALIAS PDRMembershipPersistence)
set_target_properties(PDRMembershipPersistence PROPERTIES
    EXPORT_NAME MembershipPersistence)
target_include_directories(PDRMembershipPersistence PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRMembershipPersistence PUBLIC
    Poco::Data Poco::DataSQLite Poco::Foundation)
if(NOT BUILD_SHARED_LIBS)
    target_compile_definitions(PDRMembershipPersistence PUBLIC
        PDR_MEMBERSHIP_PERSISTENCE_STATIC)
endif()
pdr_set_warnings(PDRMembershipPersistence)

add_library(PDRMembershipAPI INTERFACE)
add_library(PocoDDS::MembershipAPI ALIAS PDRMembershipAPI)
set_target_properties(PDRMembershipAPI PROPERTIES EXPORT_NAME MembershipAPI)
target_include_directories(PDRMembershipAPI INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRMembershipAPI INTERFACE
    PocoDDS::MembershipCore Poco::OSP Poco::Foundation)
target_compile_definitions(PDRMembershipAPI INTERFACE POCO_NO_AUTOMATIC_LIBS)

if(BUILD_TESTING)
    add_executable(pdr-membership-smoke tests/MembershipSmoke.cpp)
    target_link_libraries(pdr-membership-smoke PRIVATE PocoDDS::MembershipCore)
    pdr_set_warnings(pdr-membership-smoke)
    add_test(NAME membership-smoke COMMAND pdr-membership-smoke)
    set_tests_properties(membership-smoke PROPERTIES
        LABELS "membership;cluster;concurrency;reliability;release")

    add_executable(pdr-membership-incarnation-store-smoke
        tests/IncarnationStoreSmoke.cpp)
    target_link_libraries(pdr-membership-incarnation-store-smoke PRIVATE
        PocoDDS::MembershipPersistence)
    pdr_set_warnings(pdr-membership-incarnation-store-smoke)
    add_test(NAME membership-incarnation-store-smoke
        COMMAND pdr-membership-incarnation-store-smoke)
    set_tests_properties(membership-incarnation-store-smoke PROPERTIES
        LABELS "membership;persistence;transaction;recovery;release")
endif()

install(TARGETS PDRMembershipCore PDRMembershipPersistence PDRMembershipAPI
    EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
