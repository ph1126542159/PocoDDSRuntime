add_subdirectory(Devices)
add_subdirectory(CAN)
add_subdirectory(GNSS)
add_subdirectory(Linux)
add_subdirectory(Modbus)
add_subdirectory(Serial)
add_subdirectory(Simulation)
add_subdirectory(XBeeSensor)

# Stable aggregate target used by DeviceGateway and the Fast DDS bridge.
# Concrete device modules remain independently buildable and installable.
add_library(PDRDevices INTERFACE)
add_library(PocoDDS::Devices ALIAS PDRDevices)
target_link_libraries(PDRDevices INTERFACE
    PocoDDS::DeviceCore
    PocoDDS::CANDevice
    PocoDDS::GNSSDevice
    PocoDDS::LinuxDevices
    PocoDDS::ModbusDevice
    PocoDDS::SerialDevice
    PocoDDS::SimulationDevice
    PocoDDS::XBeeSensor)
