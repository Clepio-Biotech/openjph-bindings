# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file Copyright.txt or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION 3.5)

file(MAKE_DIRECTORY
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-src"
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-build"
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix"
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix/tmp"
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix/src/openjph-populate-stamp"
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix/src"
  "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix/src/openjph-populate-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix/src/openjph-populate-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "/home/dariosarra/Documents/Limen/My_Zepio/openjph-bindings/julia/OpenJPH.jl/deps/native_cmake_build/_deps/openjph-subbuild/openjph-populate-prefix/src/openjph-populate-stamp${cfgdir}") # cfgdir has leading slash
endif()
