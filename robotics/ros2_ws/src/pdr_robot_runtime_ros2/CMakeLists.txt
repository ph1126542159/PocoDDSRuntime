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
target_link_libraries(pdr_robot_runtime_node PRIVATE
  PocoDDS::RoboticsRuntime
  geometry_msgs::geometry_msgs
  lifecycle_msgs::lifecycle_msgs
  pdr_robot_msgs::pdr_robot_msgs
  rclcpp::rclcpp
  rclcpp_action::rclcpp_action
  rclcpp_lifecycle::rclcpp_lifecycle
  std_msgs::std_msgs)

install(TARGETS pdr_robot_runtime_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(pdr_robot_contract_test test/RobotContractTest.cpp)
  target_link_libraries(pdr_robot_contract_test
    PocoDDS::RoboticsRuntime
    pdr_robot_msgs::pdr_robot_msgs)
endif()
ament_package()
