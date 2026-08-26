add_library(PDRBundleManagement SHARED
    src/BundleDeploymentCoordinator.cpp
    src/BundleRepositoryAuthorization.cpp
    src/BundleRepositoryFingerprint.cpp
    src/BundleRepositoryRolloutGuard.cpp
    src/BundleManager.cpp)
add_library(PocoDDS::BundleManagement ALIAS PDRBundleManagement)

target_include_directories(PDRBundleManagement
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
target_compile_definitions(PDRBundleManagement
    PRIVATE PDR_BUNDLE_MANAGEMENT_EXPORTS)
target_link_libraries(PDRBundleManagement
    PUBLIC Poco::OSP
    PRIVATE PocoDDS::Security Poco::JSON Poco::Foundation)
pdr_isolate_embedded_static_dependencies(PDRBundleManagement)
pdr_set_warnings(PDRBundleManagement)

add_executable(pdr-bundle-repository-check
    tools/BundleRepositoryCheck.cpp)
target_link_libraries(pdr-bundle-repository-check PRIVATE
    PocoDDS::BundleManagement
    Poco::JSON
    Poco::Foundation)
pdr_set_warnings(pdr-bundle-repository-check)

if(BUILD_TESTING)
    find_package(Python3 3.9 QUIET COMPONENTS Interpreter)
    if(Python3_Interpreter_FOUND)
        add_test(NAME bundle-repository-publisher-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/tests/test_bundle_repository_publisher.py"
                --publisher "${CMAKE_SOURCE_DIR}/tools/bundle_repository_publisher.py"
                --checker "$<TARGET_FILE:pdr-bundle-repository-check>"
                --verifier "$<TARGET_FILE:pdr-signature-check>"
                --python "${Python3_EXECUTABLE}")
        set_tests_properties(bundle-repository-publisher-integration PROPERTIES
            LABELS "security;bundle;bundle-deployment;supply-chain;integration"
            TIMEOUT 30)
        add_test(NAME bundle-repository-break-glass-integration
            COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_SOURCE_DIR}/tools/tests/test_bundle_repository_break_glass.py"
                --python "${Python3_EXECUTABLE}"
                --tool "${CMAKE_SOURCE_DIR}/tools/bundle_repository_break_glass.py"
                --publisher "${CMAKE_SOURCE_DIR}/tools/bundle_repository_publisher.py"
                --checker "$<TARGET_FILE:pdr-bundle-repository-check>"
                --verifier "$<TARGET_FILE:pdr-signature-check>")
        set_tests_properties(bundle-repository-break-glass-integration PROPERTIES
            LABELS "security;bundle;bundle-deployment;supply-chain;recovery;integration"
            TIMEOUT 60)
        if(WIN32)
            set_property(TEST bundle-repository-publisher-integration PROPERTY
                ENVIRONMENT_MODIFICATION
                    "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                    "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
            set_property(TEST bundle-repository-break-glass-integration PROPERTY
                ENVIRONMENT_MODIFICATION
                    "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                    "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
        endif()
    endif()

    add_executable(pdr-bundle-repository-authorization-smoke
        tests/BundleRepositoryAuthorizationSmoke.cpp)
    target_link_libraries(pdr-bundle-repository-authorization-smoke PRIVATE
        PocoDDS::BundleManagement
        PocoDDS::Security
        Poco::Foundation
        OpenSSL::Crypto)
    pdr_set_warnings(pdr-bundle-repository-authorization-smoke)
    add_test(NAME bundle-repository-authorization-smoke
        COMMAND pdr-bundle-repository-authorization-smoke)
    set_tests_properties(bundle-repository-authorization-smoke PROPERTIES
        LABELS "security;bundle;bundle-deployment;supply-chain"
        TIMEOUT 15)
    if(WIN32)
        set_property(TEST bundle-repository-authorization-smoke PROPERTY
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-bundle-repository-rollout-guard-smoke
        tests/BundleRepositoryRolloutGuardSmoke.cpp)
    target_link_libraries(pdr-bundle-repository-rollout-guard-smoke PRIVATE
        PocoDDS::BundleManagement
        Poco::Foundation)
    pdr_set_warnings(pdr-bundle-repository-rollout-guard-smoke)
    add_test(NAME bundle-repository-rollout-guard-smoke
        COMMAND pdr-bundle-repository-rollout-guard-smoke)
    set_tests_properties(bundle-repository-rollout-guard-smoke PROPERTIES
        LABELS "security;bundle;bundle-deployment;supply-chain;rollback"
        TIMEOUT 15)
    if(WIN32)
        set_property(TEST bundle-repository-rollout-guard-smoke PROPERTY
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-bundle-deployment-coordinator-smoke
        tests/BundleDeploymentCoordinatorSmoke.cpp)
    target_link_libraries(pdr-bundle-deployment-coordinator-smoke PRIVATE
        PocoDDS::BundleManagement
        Poco::Foundation)
    pdr_set_warnings(pdr-bundle-deployment-coordinator-smoke)
    add_test(NAME bundle-deployment-coordinator-smoke
        COMMAND pdr-bundle-deployment-coordinator-smoke)
    set_tests_properties(bundle-deployment-coordinator-smoke PROPERTIES
        LABELS "fault-injection;process;reliability;bundle-deployment"
        TIMEOUT 15)
    if(WIN32)
        set_property(TEST bundle-deployment-coordinator-smoke PROPERTY
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()

    add_executable(pdr-bundle-deployment-lease-process-smoke
        tests/BundleDeploymentLeaseProcessSmoke.cpp)
    target_link_libraries(pdr-bundle-deployment-lease-process-smoke PRIVATE
        PocoDDS::BundleManagement
        Poco::Foundation)
    pdr_set_warnings(pdr-bundle-deployment-lease-process-smoke)
    add_test(NAME bundle-deployment-lease-process-smoke
        COMMAND pdr-bundle-deployment-lease-process-smoke)
    set_tests_properties(bundle-deployment-lease-process-smoke PROPERTIES
        LABELS "fault-injection;process;reliability;bundle-deployment;concurrency"
        TIMEOUT 15)
    if(WIN32)
        set_property(TEST bundle-deployment-lease-process-smoke PROPERTY
            ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
                "PATH=path_list_prepend:${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
    endif()
endif()

install(TARGETS PDRBundleManagement
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(TARGETS pdr-bundle-repository-check
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY include/ DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
