# Repository Guidelines

## Project Structure & Module Organization
- `src/`: application package
  - `routers/`: FastAPI routes (e.g., `base.py`, `stock.py`).
  - `multi_agent/`: LangGraph agents; each agent has `agent.py`, `prompt.py`, and a `tools/` folder.
  - `frontend/`: Streamlit demos (e.g., `streamlit_app.py`).
- `tests/`: mirrors `src/` (e.g., `tests/routers/test_stock.py`).
- `assets/`: images for docs/UI; `docs/`: design notes.
- Tooling/config: `pyproject.toml`, `docker-compose.yml`, `Dockerfile`.

## Build, Test, and Development Commands
- Setup (Python 3.12; uv): `uv sync --dev` installs all deps.
- Run API: `uv run python src/main.py` or `uv run uvicorn src.main:app --reload --port 21009`.
- Run Streamlit: `uv run streamlit run src/frontend/streamlit_app.py`.
- Tests: `uv run pytest -q` (add `-k name` to filter).
- Format/Lint/Type-check: `uv run black . && uv run isort . && uv run flake8 && uv run mypy src`.
- Docker (optional): first `docker network create stockelper`, then `docker compose up --build -d`.

## Coding Style & Naming Conventions
- Python 3.12, 4-space indentation. Black line length 88; isort profile "black".
- Naming: modules/functions `snake_case`; classes `PascalCase`.
- Agent layout: `src/multi_agent/<agent_name>/` with `agent.py`, `prompt.py`, and `tools/`.

## Testing Guidelines
- Frameworks: `pytest`, `pytest-asyncio` for async routes/agents.
- Place tests under `tests/` mirroring `src/`. Name files `test_*.py`.
- Prefer small, isolated cases; include async tests where applicable.
- Focus: routers, agent workflows, tool functions. No strict coverage gate yet—add tests for new code.

## Commit & Pull Request Guidelines
- Commits: concise, imperative subjects; optional scope, e.g., `feat(router): add /health`.
- PRs: clear description, linked issues, test steps, and screenshots for UI changes.
- Before opening: run formatters/linters/tests and update docs if behavior changes.

## Security & Configuration Tips
- Use `.env` (see `.env.example`); never commit secrets.
- Services (Postgres/Mongo/Neo4j/Langfuse) are wired via `docker-compose.yml`; keep ports/keys in env vars.
