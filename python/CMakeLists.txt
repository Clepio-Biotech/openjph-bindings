cmake_minimum_required(VERSION 3.18)

project(pyopenjph LANGUAGES C CXX)

include(FetchContent)

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
find_package(nanobind CONFIG REQUIRED)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(OJPH_ENABLE_TIFF_SUPPORT OFF CACHE BOOL "" FORCE)
set(OJPH_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(OJPH_BUILD_EXECUTABLES OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
  openjph
  GIT_REPOSITORY https://github.com/aous72/OpenJPH.git
  GIT_TAG 0.27.0
  GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(openjph)

nanobind_add_module(_openjph src/openjph/_openjph.cpp)
target_compile_features(_openjph PRIVATE cxx_std_17)
target_link_libraries(_openjph PRIVATE openjph)

install(TARGETS _openjph LIBRARY DESTINATION openjph)
