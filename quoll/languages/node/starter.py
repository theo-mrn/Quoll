"""A new Node.js API: Express 5 and TypeScript, tested with Vitest and Supertest, linted with ESLint.

Copied from templates/express/, then `npm install` resolves the current version of each dependency (Express's
major can be chosen: `express@4`). The Node.js version goes to .nvmrc, which the CI and the Dockerfile follow.
"""
from __future__ import annotations

from pathlib import Path

from quoll.languages.base import Starter
from quoll.starters import from_template

# Node.js version when none is asked for: the active LTS.
NODE_DEFAULT = "24"

DEPENDENCIES = ["express@{{version}}"]
DEV_DEPENDENCIES = [
    "typescript", "tsx", "@types/express@{{version}}",
    "vitest", "@vitest/coverage-v8", "supertest", "@types/supertest",
    "eslint", "@eslint/js", "typescript-eslint", "globals", "prettier",
]

starter = Starter(
    name="express",
    label="Express (TypeScript)",
    role="back",
    create=from_template(
        Path(__file__).parent / "templates" / "express",
        [
            ["npm", "install", "--save", *DEPENDENCIES],
            # Types of the Node.js the project runs on.
            ["npm", "install", "--save-dev", *DEV_DEPENDENCIES, "@types/node@{{runtime}}"],
            ["npx", "prettier", "--write", "."],
        ],
        runtime="node",
        runtime_default=NODE_DEFAULT,
        local_install=["npm", "ci"],
        local_folder="node_modules",
    ),
    dev="npm run dev",
    # Both maintained (https://expressjs.com/en/support).
    versions=("5", "4"),
    runtime="node",
    runtime_default=NODE_DEFAULT,
)
