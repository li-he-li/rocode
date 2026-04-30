cmake_minimum_required(VERSION 3.10)
project(ikfast_python_wrapper)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Build as a shared library for Python
# Note: The solver cpp is included directly in ikfast_wrapper.cpp (same as MoveIt does)
add_library(ikfast_wrapper SHARED
    ikfast_wrapper.cpp
)

# Suppress warnings from IKFast generated code
target_compile_options(ikfast_wrapper PRIVATE
    -Wno-unused-variable
    -Wno-unused-parameter
    -fPIC
)

# Include directories
target_include_directories(ikfast_wrapper PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

# Link with LAPACK (required by IKFast solver)
find_package(LAPACK REQUIRED)
target_link_libraries(ikfast_wrapper ${LAPACK_LIBRARIES})

# Install the library
install(TARGETS ikfast_wrapper
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin
)
