cmake_minimum_required(VERSION 3.16)
project(pdr_robot_runtime_ros2)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(lifecycle_msgs REQUIRED)
find_package(PDRRoboticsRuntime CONFIG REQUIRED)
find_package(pdr_robot_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(rclcpp_lifecycle REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(pdr_robot_runtime_node src/RobotRuntimeNode.cpp)
target_compile_features(pdr_robot_runtime_node PRIVATE cxx_std_17)
target_link_libraries(pdr_robot_runtime_node PRIVATE PocoDDS::RoboticsRuntime)
ament_target_dependencies(pdr_robot_runtime_node
  geometry_msgs lifecycle_msgs pdr_robot_msgs rclcpp rclcpp_action rclcpp_lifecycle std_msgs)

install(TARGETS pdr_robot_runtime_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
ament_package()
