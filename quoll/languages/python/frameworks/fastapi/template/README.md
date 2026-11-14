# {{name}}

Python API: FastAPI, managed with uv.

```bash
uv sync
uv run fastapi dev app/main.py   # http://localhost:8000/health, reloads on change
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
```
