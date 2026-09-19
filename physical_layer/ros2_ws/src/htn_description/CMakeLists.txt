cmake_minimum_required(VERSION 3.8)
project(htn_description)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config urdf meshes
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
