"""JVM projects (Java, Kotlin) built with Maven or Gradle."""

from quoll.languages.base import Language
from quoll.languages.java.ci import JavaCI
from quoll.languages.java.detect import detect
from quoll.languages.java.docker import JavaImage
from quoll.languages.java.frameworks import spring_boot

language = Language(
    name="java",
    markers=("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"),
    # The -wrapper variants run the committed ./mvnw or ./gradlew.
    package_managers=("maven", "maven-wrapper", "gradle", "gradle-wrapper"),
    lint_tools=("spotless", "checkstyle", "ktlint", "detekt", "spotbugs", "pmd"),
    test_runners=("junit",),
    detect=detect,
    ci=JavaCI(),
    frameworks=(spring_boot.framework,),
    docker=JavaImage(),
)
