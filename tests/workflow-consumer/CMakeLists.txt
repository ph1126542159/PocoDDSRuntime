cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntimeWorkflowConsumer LANGUAGES CXX)

find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS
    WorkflowAPI WorkflowCore StoreForwardAPI StoreForwardCore
    TransportProviderAPI TransportProviderCore
    CapabilitiesAPI CapabilitiesCore CapabilitiesPersistence
    ConfigTransactionAPI ConfigTransactionCore
    ResourceGovernanceAPI ResourceGovernanceCore
    SchedulingAPI SchedulingCore SchedulingConfiguration
    ServiceDependencyAPI ServiceDependencyCore
    LifecycleAPI LifecycleCore LifecyclePersistence
    SchemaRegistryAPI SchemaRegistryCore)

add_library(pdr-workflow-provider STATIC provider.cpp)
target_compile_features(pdr-workflow-provider PRIVATE cxx_std_17)
target_link_libraries(pdr-workflow-provider PRIVATE PocoDDS::WorkflowAPI)

add_executable(pdr-workflow-api-consumer api_main.cpp)
target_compile_features(pdr-workflow-api-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-workflow-api-consumer
    PRIVATE PocoDDS::WorkflowAPI pdr-workflow-provider)

add_library(pdr-delivery-provider STATIC delivery_provider.cpp)
target_compile_features(pdr-delivery-provider PRIVATE cxx_std_17)
target_link_libraries(pdr-delivery-provider PRIVATE PocoDDS::StoreForwardAPI)

add_executable(pdr-store-forward-api-consumer outbox_api_main.cpp)
target_compile_features(pdr-store-forward-api-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-store-forward-api-consumer
    PRIVATE PocoDDS::StoreForwardAPI pdr-delivery-provider)

add_library(pdr-transport-provider STATIC transport_provider.cpp)
target_compile_features(pdr-transport-provider PRIVATE cxx_std_17)
target_link_libraries(pdr-transport-provider PRIVATE PocoDDS::TransportProviderAPI)

add_executable(pdr-transport-provider-api-consumer transport_api_main.cpp)
target_compile_features(pdr-transport-provider-api-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-transport-provider-api-consumer PRIVATE
    PocoDDS::TransportProviderCore pdr-transport-provider)

add_executable(pdr-config-transaction-api-consumer config_transaction_main.cpp)
target_compile_features(pdr-config-transaction-api-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-config-transaction-api-consumer PRIVATE
    PocoDDS::ConfigTransactionCore)

add_executable(pdr-scheduling-configuration-consumer
    scheduling_configuration_main.cpp)
target_compile_features(pdr-scheduling-configuration-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-scheduling-configuration-consumer PRIVATE
    PocoDDS::SchedulingConfiguration)

add_executable(pdr-service-dependency-consumer service_dependency_main.cpp)
target_compile_features(pdr-service-dependency-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-service-dependency-consumer PRIVATE
    PocoDDS::ServiceDependencyCore)

add_executable(pdr-lifecycle-consumer lifecycle_main.cpp)
target_compile_features(pdr-lifecycle-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-lifecycle-consumer PRIVATE PocoDDS::LifecycleCore)

add_executable(pdr-lifecycle-persistence-consumer lifecycle_persistence_main.cpp)
target_compile_features(pdr-lifecycle-persistence-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-lifecycle-persistence-consumer PRIVATE
    PocoDDS::LifecyclePersistence)

add_executable(pdr-schema-registry-api-consumer schema_registry_main.cpp)
target_compile_features(pdr-schema-registry-api-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-schema-registry-api-consumer PRIVATE
    PocoDDS::SchemaRegistryCore)

add_executable(pdr-capabilities-api-consumer capabilities_main.cpp)
target_compile_features(pdr-capabilities-api-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-capabilities-api-consumer PRIVATE
    PocoDDS::CapabilitiesPersistence)

add_executable(pdr-workflow-consumer main.cpp)
target_compile_features(pdr-workflow-consumer PRIVATE cxx_std_17)
target_link_libraries(pdr-workflow-consumer
    PRIVATE PocoDDS::WorkflowCore PocoDDS::StoreForwardCore pdr-workflow-provider)
