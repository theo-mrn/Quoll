"""C and C++: CMake (plain, Conan or vcpkg) and Meson."""

from quoll.languages.base import Language
from quoll.languages.cpp.ci import CppCI
from quoll.languages.cpp.detect import detect
from quoll.languages.cpp.docker import CppImage

language = Language(
    name="cpp",
    markers=("CMakeLists.txt", "meson.build"),
    package_managers=("cmake", "conan", "vcpkg", "meson"),
    lint_tools=("clang-format", "clang-tidy", "cppcheck"),
    test_runners=("ctest", "meson"),
    detect=detect,
    ci=CppCI(),
    docker=CppImage(),
)
