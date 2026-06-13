""".NET: C#, F# and VB projects and solutions."""

from quoll.languages.base import Language
from quoll.languages.dotnet.ci import DotnetCI
from quoll.languages.dotnet.detect import detect
from quoll.languages.dotnet.docker import DotnetImage

language = Language(
    name="dotnet",
    markers=("*.sln", "*.slnx", "*.csproj", "*.fsproj", "*.vbproj"),
    package_managers=("dotnet",),
    lint_tools=("dotnet-format",),
    test_runners=("dotnet",),
    detect=detect,
    ci=DotnetCI(),
    docker=DotnetImage(),
)
