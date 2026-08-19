cmake_minimum_required(VERSION 3.16)
project(pdr_robot_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config launch worlds DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/gazebo_sil_check.py DESTINATION lib/${PROJECT_NAME})
ament_package()
