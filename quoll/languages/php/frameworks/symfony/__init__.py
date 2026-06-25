"""Symfony: the console's linters catch broken services, config and templates before the tests do."""

from quoll.languages.base import Framework
from quoll.languages.php.frameworks.symfony.ci import SymfonyCI
from quoll.languages.php.frameworks.symfony.detect import detect
from quoll.languages.php.frameworks.symfony.docker import SymfonyImage

framework = Framework(
    name="symfony",
    language="php",
    detect=detect,
    ci=SymfonyCI(),
    lint_tools=("symfony-container", "symfony-yaml", "symfony-twig"),
    docker=SymfonyImage(),
)
