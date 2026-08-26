add_library(PDRSecurity
    src/DetachedSignatureVerifier.cpp
    src/PrincipalStore.cpp
    src/SecretFile.cpp)
add_library(PocoDDS::Security ALIAS PDRSecurity)
set_target_properties(PDRSecurity PROPERTIES EXPORT_NAME Security)
target_include_directories(PDRSecurity PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(PDRSecurity
    PUBLIC Poco::Util Poco::Foundation
    PRIVATE Poco::JSON OpenSSL::Crypto)
if(WIN32)
    target_link_libraries(PDRSecurity PRIVATE advapi32)
endif()
pdr_set_warnings(PDRSecurity)

add_executable(pdr-identity-check tools/IdentityCheck.cpp)
target_link_libraries(pdr-identity-check PRIVATE PocoDDS::Security Poco::JSON Poco::Util Poco::Foundation)
pdr_set_warnings(pdr-identity-check)

if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    add_executable(pdr-principal-store-smoke tests/PrincipalStoreSmoke.cpp)
    target_link_libraries(pdr-principal-store-smoke PRIVATE PocoDDS::Security)
    pdr_set_warnings(pdr-principal-store-smoke)
    add_test(NAME principal-store-smoke COMMAND pdr-principal-store-smoke)
    set_tests_properties(principal-store-smoke PROPERTIES LABELS "security;identity")
    if(Python3_Interpreter_FOUND)
        add_test(NAME identity-check-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/IdentityCheckIntegration.py"
                --checker "$<TARGET_FILE:pdr-identity-check>"
                --pdr "${CMAKE_SOURCE_DIR}/tools/pdr.py"
                --python "${Python3_EXECUTABLE}")
        set_tests_properties(identity-check-integration PROPERTIES LABELS "security;identity;release")
    endif()
endif()

install(TARGETS PDRSecurity EXPORT PocoDDSRuntimeTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(TARGETS pdr-identity-check RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
