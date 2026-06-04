"""PHP: Composer projects."""

from quoll.languages.base import Language
from quoll.languages.php.ci import PhpCI
from quoll.languages.php.detect import detect
from quoll.languages.php.docker import PhpImage
from quoll.languages.php.frameworks import laravel, symfony

language = Language(
    name="php",
    markers=("composer.json",),
    package_managers=("composer",),
    lint_tools=("php-cs-fixer", "phpcs", "pint", "phpstan", "psalm", "rector"),
    test_runners=("phpunit", "pest"),
    detect=detect,
    ci=PhpCI(),
    frameworks=(symfony.framework, laravel.framework),
    docker=PhpImage(),
)
