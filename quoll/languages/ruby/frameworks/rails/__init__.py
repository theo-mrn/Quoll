"""Ruby on Rails: tests need the test database prepared; Brakeman scans the app for vulnerabilities."""

from quoll.languages.base import Framework
from quoll.languages.ruby.frameworks.rails.ci import RailsCI
from quoll.languages.ruby.frameworks.rails.detect import detect
from quoll.languages.ruby.frameworks.rails.docker import RailsImage
from quoll.languages.ruby.frameworks.rails.services import service_env

framework = Framework(
    name="rails",
    language="ruby",
    detect=detect,
    ci=RailsCI(),
    lint_tools=("brakeman",),
    test_runners=("rails", "rails-rspec"),
    docker=RailsImage(),
    service_env=service_env,
)
