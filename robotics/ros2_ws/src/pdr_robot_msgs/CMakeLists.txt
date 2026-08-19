cmake_minimum_required(VERSION 3.16)
project(pdr_robot_msgs)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/RobotState.msg"
  "msg/JointCommand.msg"
  "msg/RobotCommand.msg"
  "msg/SensorSample.msg"
  "msg/ContactState.msg"
  "msg/RobotFrame.msg"
  "msg/SafetyState.msg"
  "srv/SetEmergencyStop.srv"
  "action/ExecuteBehavior.action"
  DEPENDENCIES builtin_interfaces geometry_msgs sensor_msgs std_msgs)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
