# Every direct child with a CMakeLists.txt is an independently owned service.
# New services are discovered automatically; service-local CMake owns sources,
# tests, Bundle packaging and install rules.
pdr_add_component_directories("${CMAKE_CURRENT_SOURCE_DIR}"
    FOLDER "Services")

pdr_add_component_group_target(PDRGovernanceServices
    COMPONENT governance-services
    FOLDER "Component Groups/Services"
    DEPENDS
        PDR_CapabilityManagement_Bundle
        PDR_CapabilityRuntime_Bundle
        PDR_ConfigurationRuntime_Bundle
        PDRHttpInvocationProviderCore
        PDR_HttpInvocationProvider_Bundle
        PDR_LifecycleRuntime_Bundle
        PDR_MembershipRuntime_Bundle
        PDR_OutboxRuntime_Bundle
        PDR_ResourceGovernor_Bundle
        PDR_SchedulerRuntime_Bundle
        PDR_SchemaRegistryRuntime_Bundle
        PDRServiceClientTraceAdapter
        PDRServiceClientJournalAdapter
        PDR_ServiceClientRuntime_Bundle
        PDR_ServiceDependencyRuntime_Bundle
        PDR_ServiceDirectoryRuntime_Bundle
        PDR_TransportRegistryRuntime_Bundle
        PDR_WorkflowRuntime_Bundle)

pdr_add_component_group_target(PDRGatewayServices
    COMPONENT gateway-services
    FOLDER "Component Groups/Services"
    DEPENDS
        PDR_BuiltinDeviceFactories_Bundle
        PDR_BuiltinProtocolFactories_Bundle
        PDR_BuiltinTransportFactories_Bundle
        PDR_DeviceGateway_Bundle
        PDR_ProtocolGateway_Bundle)

pdr_add_component_group_target(PDRUtilityServices
    COMPONENT utility-services
    FOLDER "Component Groups/Services"
    DEPENDS
        PDRDeviceStatus
        PDRMobileConnection
        PDRNetworkEnvironment
        PDRUnitsOfMeasure
        PDRWebEvent
        PDR_DeviceStatus_Bundle
        PDR_MobileConnection_Bundle
        PDR_NetworkEnvironment_Bundle
        PDR_UnitsOfMeasure_Bundle
        PDR_WebEvent_Bundle)

pdr_write_component_group_manifest(
    "${CMAKE_BINARY_DIR}/reports/framework-component-build-groups.json")
