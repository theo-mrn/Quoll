"""Django: system checks and missing migrations fail the lint job; tests run through manage.py or pytest-django."""

from quoll.languages.base import Framework
from quoll.languages.python.frameworks.django.ci import DjangoCI
from quoll.languages.python.frameworks.django.detect import detect
from quoll.languages.python.frameworks.django.docker import DjangoImage

framework = Framework(
    name="django",
    language="python",
    detect=detect,
    ci=DjangoCI(),
    lint_tools=("django-check", "django-migrations"),
    test_runners=("django",),
    docker=DjangoImage(),
)
