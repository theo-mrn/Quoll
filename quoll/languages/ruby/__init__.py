"""Ruby: Bundler projects and gems."""

from quoll.languages.base import Language
from quoll.languages.ruby.ci import RubyCI
from quoll.languages.ruby.detect import detect
from quoll.languages.ruby.docker import RubyImage
from quoll.languages.ruby.frameworks import rails

language = Language(
    name="ruby",
    markers=("Gemfile",),
    package_managers=("bundler",),
    lint_tools=("rubocop", "standard"),
    test_runners=("rspec", "minitest"),
    detect=detect,
    ci=RubyCI(),
    frameworks=(rails.framework,),
    docker=RubyImage(),
)
