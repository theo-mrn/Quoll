"""Spring Boot: Maven/Gradle already run its tests; the image ships the jar as cache-friendly layers."""

from quoll.languages.base import Framework
from quoll.languages.java.frameworks.spring_boot.detect import detect
from quoll.languages.java.frameworks.spring_boot.docker import SpringBootImage
from quoll.languages.java.frameworks.spring_boot.services import service_env

framework = Framework(
    name="spring-boot", language="java", detect=detect, docker=SpringBootImage(), service_env=service_env
)
