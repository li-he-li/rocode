#!/bin/bash
# Build script for IKFast Python wrapper

set -e  # Exit on error

echo "Building IKFast Python Wrapper Library"
echo "======================================="

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLUGIN_DIR="$SCRIPT_DIR/.."

echo "Script directory: $SCRIPT_DIR"
echo "Plugin directory: $PLUGIN_DIR"

# Create build directory
BUILD_DIR="$SCRIPT_DIR/build"
mkdir -p "$BUILD_DIR"

cd "$BUILD_DIR"

echo ""
echo "Running CMake..."
cmake ..

echo ""
echo "Building library..."
make -j$(nproc)

echo ""
echo "Build completed successfully!"
echo ""
echo "Shared library location: $BUILD_DIR/libikfast_wrapper.so"
echo ""
echo "To run the test, execute:"
echo "  cd $SCRIPT_DIR"
echo "  python3 test_fk_ik.py"
