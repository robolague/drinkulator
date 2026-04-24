# Drink Calculator

Switches single-drink measurements to ones that work in a 5-gallon cooler.

## Modern Python setup (uv)

This project uses [`uv`](https://docs.astral.sh/uv/) for environment and
dependency management.

### 1) Install uv

Use your package manager, or:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2) Create/sync the project environment

From the repository root:

```bash
uv sync
```

This will create a local virtual environment at `.venv` and install project
dependencies.

### 3) Run the app

```bash
uv run python main.py
```
