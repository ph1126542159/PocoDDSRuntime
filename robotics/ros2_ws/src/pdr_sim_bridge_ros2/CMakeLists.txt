cmake_minimum_required(VERSION 3.16)
project(pdr_sim_bridge_ros2)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(pdr_robot_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(pdr_sim_bridge_node src/SimulationBridgeNode.cpp)
target_compile_features(pdr_sim_bridge_node PRIVATE cxx_std_17)
target_link_libraries(pdr_sim_bridge_node PRIVATE
  geometry_msgs::geometry_msgs
  nav_msgs::nav_msgs
  pdr_robot_msgs::pdr_robot_msgs
  rclcpp::rclcpp
  sensor_msgs::sensor_msgs
  std_msgs::std_msgs)

install(TARGETS pdr_sim_bridge_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})
ament_package()
