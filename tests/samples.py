"""Representative projects, one per package manager. Paths ending in "/" are directories."""

PYTHON_UV = {
    "pyproject.toml": """
[project]
name = "app"
requires-python = ">=3.11"
dependencies = ["fastapi"]

[dependency-groups]
dev = ["pytest", "ruff"]

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
strict = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""",
    "uv.lock": "",
    "src/app/__init__.py": "",
    "tests/": "",
}

PYTHON_PIP = {
    "requirements.txt": "flask\n",
    "requirements-dev.txt": "pytest\nblack\n",
    ".flake8": "[flake8]\n",
    ".python-version": "3.12.4\n",
    "tests/": "",
}

PYTHON_POETRY = {
    "pyproject.toml": """
[tool.poetry]
name = "svc"

[tool.poetry.dependencies]
python = "^3.10"

[tool.poetry.group.dev.dependencies]
pytest = "*"
""",
    "poetry.lock": "",
    "svc/__init__.py": "",
}

NODE_PNPM = {
    "package.json": {
        "name": "web",
        "scripts": {"build": "vite build", "lint": "eslint ."},
        "devDependencies": {
            "vite": "6",
            "vitest": "3",
            "@vitest/coverage-v8": "3",
            "typescript": "5",
            "prettier": "3",
        },
    },
    "pnpm-lock.yaml": "",
    "tsconfig.json": "{}",
    ".nvmrc": "v22.11.0\n",
}

NODE_NPM_JEST = {
    "package.json": {"name": "api", "engines": {"node": ">=22"}, "devDependencies": {"jest": "29", "eslint": "9"}},
    "package-lock.json": "{}",
}

NODE_YARN_BERRY = {
    "package.json": {"name": "lib", "packageManager": "yarn@4.5.0", "scripts": {"test": "node --test"}},
    "yarn.lock": "",
    ".yarnrc.yml": "",
}

NODE_BUN = {
    "package.json": {"name": "tool", "devDependencies": {"@biomejs/biome": "2"}},
    "bun.lock": "",
}

GO = {
    "go.mod": "module example.com/svc\n\ngo 1.23.4\n",
    "go.sum": "",
    "Dockerfile": "FROM golang\n",
}

RUST = {
    "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\nrust-version = "1.80"\n',
    "Cargo.lock": "",
    "src/main.rs": "fn main() {}\n",
}

JAVA_MAVEN = {
    "pom.xml": (
        "<project><properties><maven.compiler.release>17</maven.compiler.release></properties>"
        "<build><plugins><plugin><artifactId>spotless-maven-plugin</artifactId></plugin></plugins></build></project>"
    ),
    "mvnw": "",
    "src/test/java/AppTest.java": "",
}

JAVA_GRADLE_KOTLIN = {
    "build.gradle.kts": 'plugins { id("org.jlleitschuh.gradle.ktlint") }\nkotlin { jvmToolchain(21) }\n',
    "settings.gradle.kts": "",
    "gradlew": "",
    "src/test/kotlin/AppTest.kt": "",
}

PHP_COMPOSER = {
    "composer.json": {
        "require": {"php": ">=8.3"},
        "require-dev": {"phpunit/phpunit": "^11", "phpstan/phpstan": "^2", "friendsofphp/php-cs-fixer": "^3"},
    },
    "composer.lock": "{}",
}

RUBY_GEM = {
    "Gemfile": 'source "https://rubygems.org"\ngem "rubocop"\ngem "rspec-core"\ngem "simplecov"\n',
    "Gemfile.lock": "",
    ".ruby-version": "3.3.6\n",
    "mylib.gemspec": "",
}

DOTNET = {
    "App.sln": "",
    "src/App/App.csproj": "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
    "src/App/packages.lock.json": "{}",
    "tests/App.Tests/App.Tests.csproj": (
        "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup><ItemGroup>"
        '<PackageReference Include="Microsoft.NET.Test.Sdk" /><PackageReference Include="coverlet.msbuild" />'
        "</ItemGroup></Project>"
    ),
}

# --------------------------------------------------------------------------- frameworks

NEXTJS = {
    "package.json": {
        "scripts": {"build": "next build", "lint": "eslint ."},
        "dependencies": {"next": "16", "react": "19"},
        "devDependencies": {"typescript": "5", "vitest": "3", "@vitest/coverage-v8": "3"},
    },
    "package-lock.json": "{}",
    "tsconfig.json": "{}",
}

NUXT = {
    "package.json": {
        "scripts": {"build": "nuxt build"},
        "dependencies": {"nuxt": "4"},
        "devDependencies": {"vue-tsc": "2", "typescript": "5"},
    },
    "pnpm-lock.yaml": "",
    "tsconfig.json": "{}",
}

SVELTEKIT = {
    "package.json": {
        "scripts": {"build": "vite build", "check": "svelte-kit sync && svelte-check"},
        "devDependencies": {"@sveltejs/kit": "2", "svelte-check": "4", "typescript": "5"},
    },
    "package-lock.json": "{}",
    "tsconfig.json": "{}",
}

ASTRO = {
    "package.json": {
        "scripts": {"build": "astro build"},
        "dependencies": {"astro": "5", "@astrojs/check": "0.9", "typescript": "5"},
    },
    "package-lock.json": "{}",
    "tsconfig.json": "{}",
}

ANGULAR = {
    "package.json": {
        "scripts": {"build": "ng build", "test": "ng test", "lint": "ng lint"},
        "dependencies": {"@angular/core": "20"},
        "devDependencies": {"karma": "6", "jasmine-core": "5", "typescript": "5"},
    },
    "package-lock.json": "{}",
    "tsconfig.json": "{}",
}

NESTJS = {
    "package.json": {
        "scripts": {"build": "nest build", "lint": "eslint ."},
        "dependencies": {"@nestjs/core": "11"},
        "devDependencies": {"jest": "29"},
    },
    "package-lock.json": "{}",
}

DJANGO = {"requirements.txt": "django>=5.2\n", "manage.py": "", "shop/__init__.py": ""}

FASTAPI = {"requirements.txt": "fastapi\nuvicorn\npytest\n", "app/__init__.py": ""}

FLASK = {"requirements.txt": "flask\npytest\n", "app/__init__.py": ""}

SYMFONY = {
    "composer.json": {
        "require": {"php": ">=8.2", "symfony/framework-bundle": "7.3.*", "symfony/twig-bundle": "7.3.*"},
        "require-dev": {"phpunit/phpunit": "^11"},
    },
    "composer.lock": "{}",
    "bin/console": "",
    "config/": "",
    "templates/": "",
}

LARAVEL = {
    "composer.json": {
        "require": {"php": "^8.2", "laravel/framework": "^12.0"},
        "require-dev": {"laravel/pint": "^1.0", "phpunit/phpunit": "^11"},
    },
    "composer.lock": "{}",
    "artisan": "",
}

RAILS = {
    "Gemfile": 'source "https://rubygems.org"\nruby "3.4.1"\ngem "rails", "~> 8.0.1"\ngem "brakeman"\n',
    "Gemfile.lock": "GEM\n  specs:\n    rails (8.0.1)\n    rubocop (1.70.0)\n",
    "bin/rails": "",
    "test/": "",
}

SPRING_BOOT = {
    "pom.xml": "<project><parent><artifactId>spring-boot-starter-parent</artifactId></parent></project>",
    "mvnw": "",
    "src/test/java/AppTest.java": "",
}

# One sample per language and per framework, used by the plugin contract tests.
CPP_CMAKE = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.25)\nproject(calc CXX)\nadd_executable(calc src/main.cpp)\n"
    "enable_testing()\nadd_executable(calc_tests tests/test.cpp)\nadd_test(NAME calc COMMAND calc_tests)\n",
    ".clang-format": "BasedOnStyle: Google\n",
    "src/main.cpp": "int main() { return 0; }\n",
    "tests/test.cpp": "int main() { return 0; }\n",
}

CPP_CONAN = {
    "CMakeLists.txt": "project(svc)\nfind_package(PostgreSQL REQUIRED)\nadd_executable(svc main.cpp)\n",
    "conanfile.txt": "[requires]\nlibpq/15.4\n",
    "conan.lock": "{}",
}

C_MESON = {
    "meson.build": "project('tool', 'c')\nexe = executable('tool', 'main.c')\ntest('basic', exe)\n",
    "main.c": "int main(void) { return 0; }\n",
}

SAMPLE_BY_LANGUAGE = {
    "go": GO,
    "rust": RUST,
    "java": JAVA_MAVEN,
    "dotnet": DOTNET,
    "php": PHP_COMPOSER,
    "ruby": RUBY_GEM,
    "python": PYTHON_POETRY,
    "node": NODE_PNPM,
    "cpp": CPP_CMAKE,
}

SAMPLE_BY_FRAMEWORK = {
    "nextjs": NEXTJS,
    "nuxt": NUXT,
    "sveltekit": SVELTEKIT,
    "astro": ASTRO,
    "angular": ANGULAR,
    "nestjs": NESTJS,
    "django": DJANGO,
    "fastapi": FASTAPI,
    "flask": FLASK,
    "symfony": SYMFONY,
    "laravel": LARAVEL,
    "rails": RAILS,
    "spring-boot": SPRING_BOOT,
}

ALL_PROJECTS = {
    "python-uv": PYTHON_UV,
    "python-pip": PYTHON_PIP,
    "python-poetry": PYTHON_POETRY,
    "node-pnpm": NODE_PNPM,
    "node-npm-jest": NODE_NPM_JEST,
    "node-yarn-berry": NODE_YARN_BERRY,
    "node-bun": NODE_BUN,
    "go": GO,
    "rust": RUST,
    "java-maven": JAVA_MAVEN,
    "java-gradle-kotlin": JAVA_GRADLE_KOTLIN,
    "php": PHP_COMPOSER,
    "ruby": RUBY_GEM,
    "dotnet": DOTNET,
    "cpp-cmake": CPP_CMAKE,
    "cpp-conan": CPP_CONAN,
    "c-meson": C_MESON,
    **SAMPLE_BY_FRAMEWORK,
}
