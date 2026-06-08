from __future__ import annotations

from quoll.ci.detect import detect
from tests.helpers import runs, steps, workflow
from tests.samples import RAILS, RUBY_GEM


def test_gem(make_project) -> None:
    det = detect(make_project(RUBY_GEM))
    assert det.stack == "ruby"
    assert (det.version_file, det.version) == (".ruby-version", "3.3")
    assert det.matrix_versions == ["3.3", "3.4"]
    assert det.lint_tools == ["rubocop"]
    assert det.test_runner == "rspec"
    assert det.coverage is True  # simplecov
    assert det.build_command == "gem build *.gemspec"
    doc = workflow(make_project, RUBY_GEM)
    # setup-ruby reads .ruby-version and runs bundle install itself.
    assert steps(doc, "test")[1]["with"] == {"bundler-cache": True}
    assert "bundle exec rspec" in runs(doc, "test")
    assert "coverage/.last_run.json" in runs(doc, "test")


def test_rails(make_project) -> None:
    det = detect(make_project(RAILS))
    assert det.framework == "rails"
    # ruby "3.4.1" from the Gemfile, not the rails gem version.
    assert det.version == "3.4"
    assert det.lint_tools == ["rubocop", "brakeman"]
    assert det.test_runner == "rails"
    assert det.coverage is False
    doc = workflow(make_project, RAILS)
    assert doc["env"] == {"RAILS_ENV": "test"}
    assert "bundle exec brakeman --no-pager" in runs(doc, "lint")
    assert "bin/rails db:test:prepare test" in runs(doc, "test")


def test_rails_with_rspec(make_project) -> None:
    files = {**RAILS, "Gemfile": RAILS["Gemfile"] + 'gem "rspec-rails"\n'}
    assert detect(make_project(files)).test_runner == "rails-rspec"
    assert "bin/rails db:test:prepare\nbundle exec rspec" in runs(workflow(make_project, files), "test")
