<!-- Repository-specific test guidance for Copilot -->

# Copilot test instructions for this repository

## Goal

Validate changes with the **smallest relevant check** that matches the files touched.

This repository does not currently have a standard automated unit test suite. Most validation is a mix of:

- Python syntax checks
- import checks for core modules
- formatting and lint checks
- targeted manual/integration scripts such as `test_filters_quick.py` and `test_video_controls.py`

## Default validation order

1. Run a **targeted syntax check** for edited Python files when possible.
2. Run a **targeted import check** for the module(s) you changed.
3. If formatting or import order may have changed, run the repo-standard style checks.
4. Only run one of the `test_*.py` scripts when the change directly affects that workflow and the script is relevant.

## Preferred commands

Use the same tools and conventions already defined in CI and pre-commit.

### Syntax check

```bash
python -m py_compile <changed_python_files>
```

If a broader syntax pass is needed, CI uses:

```bash
python -m py_compile $(find . -name "*.py" -not -path "./.venv/*" -not -path "./__pycache__/*")
```

### Import checks

For core-module changes, prefer targeted import validation such as:

```bash
python -c "import config; print('ok')"
python -c "import instagram_manager; print('ok')"
python -c "import account_manager; print('ok')"
python -c "import content_database_manager; print('ok')"
python -c "import database_manager_sqlserver; print('ok')"
```

### Lint and formatting checks

Use the repo-standard commands from CI:

```bash
ruff check . --line-length=120 --ignore=E501,F401,F841
black --check --line-length=120 --diff .
isort --check-only --profile=black --line-length=120 .
```

When a change is small, prefer running these against only the touched files if the tool supports it.

### Security/dependency check

Only run this when dependency or packaging changes are relevant:

```bash
safety check --ignore=70612
```

## Change-specific guidance

### `gui.py` changes

- At minimum, run syntax validation.
- Prefer a targeted import or launch sanity check over unrelated scripts.
- Only run `test_video_controls.py` when the change affects video playback or related GUI controls.

### Database and account persistence changes

- At minimum, run syntax validation and targeted imports.
- Be careful with scripts that depend on a live SQL Server or real account data.
- Do not assume local database-backed integration scripts are portable or safe to run in every environment.

### Instagram/session/download changes

- At minimum, run syntax validation and targeted imports.
- Avoid validation that requires real Instagram credentials unless the task explicitly depends on that flow.

### Docs-only changes

- No code checks are required unless the documentation changes command examples or developer workflow instructions that should be verified.

## Existing test scripts

These files exist, but they are better treated as **manual or environment-dependent validation scripts** than as a baseline automated suite:

- `test_filters_quick.py`
- `test_filter_pagination.py`
- `test_filter_recalculation.py`
- `test_new_filters.py`
- `test_video_controls.py`

Only run one when it directly matches the changed behavior.

## Pre-commit alignment

If pre-commit is being used for the task, align with `.pre-commit-config.yaml`, which includes:

- AST validation
- docstring-first check
- debug-statement detection
- Black
- isort
- Ruff
- detect-secrets

## Avoid

- Do not invent a new test framework for routine changes.
- Do not run broad integration scripts when a syntax/import check is sufficient.
- Do not require live Instagram access, browser state, or SQL Server connectivity unless the change specifically targets that integration.
- Do not claim full test coverage when only syntax or import checks were run.
