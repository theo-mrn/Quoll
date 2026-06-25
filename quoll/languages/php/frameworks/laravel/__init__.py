"""Laravel: tests run through artisan, which needs an .env and an application key."""

from quoll.languages.base import Framework
from quoll.languages.php.frameworks.laravel.ci import LaravelCI
from quoll.languages.php.frameworks.laravel.detect import detect
from quoll.languages.php.frameworks.laravel.docker import LaravelImage
from quoll.languages.php.frameworks.laravel.services import service_env

framework = Framework(
    name="laravel",
    language="php",
    detect=detect,
    ci=LaravelCI(),
    test_runners=("artisan",),
    docker=LaravelImage(),
    service_env=service_env,
)
