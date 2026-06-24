cmake_minimum_required(VERSION 3.18)
project(openjph-native LANGUAGES C CXX)

include(FetchContent)

set(BUILD_SHARED_LIBS         OFF CACHE BOOL "" FORCE)
set(OJPH_ENABLE_TIFF_SUPPORT  OFF CACHE BOOL "" FORCE)
set(OJPH_BUILD_TESTS          OFF CACHE BOOL "" FORCE)
set(OJPH_BUILD_EXECUTABLES    OFF CACHE BOOL "" FORCE)

FetchContent_Declare(openjph
  GIT_REPOSITORY https://github.com/aous72/OpenJPH.git
  GIT_TAG        0.29.0
  GIT_SHALLOW    TRUE)
FetchContent_MakeAvailable(openjph)

add_library(openjph_c SHARED src/openjph_c.cpp)

target_include_directories(openjph_c PRIVATE
  include
  $<TARGET_PROPERTY:openjph,INTERFACE_INCLUDE_DIRECTORIES>)

target_compile_features(openjph_c PRIVATE cxx_std_17)
target_compile_options(openjph_c PRIVATE -fvisibility=hidden -O2)

# Embed the entire static OpenJPH archive so libopenjph_c.so has no runtime
# dependency on a separate libopenjph.so.
add_dependencies(openjph_c openjph)
target_link_options(openjph_c PRIVATE
  "-Wl,--whole-archive"
  "$<TARGET_FILE:openjph>"
  "-Wl,--no-whole-archive")

install(TARGETS openjph_c LIBRARY DESTINATION lib)
install(FILES include/openjph_c.h DESTINATION include)
