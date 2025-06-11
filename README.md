# Stangent

**Version:** 0.1.0
**License:** MIT (or choose your own)

A CLI tool to automatically analyze and fix PHPStan issues in Laravel projects by leveraging AI agents.

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [How It Works](#how-it-works)
- [Configuration](#configuration)
- [Development](#development)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

---

## Features

- Generates a project structure overview.
- Runs PHPStan at incremental strictness levels.
- Reads and writes source files via tool functions.
- Applies fixes to PHP code in the `App\` namespace only.
- Fully automated “agent” workflow using [openai-agents](https://openai.github.io/openai-agents-python/).

---

## Prerequisites

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (for CLI tooling)
- A Laravel project with PHPStan installed (`vendor/bin/phpstan`)

---

## Installation

1. **Clone the repository**
   Replace `<repo-url>` with your git remote:
   ```bash
   git clone <repo-url>
   cd stangent
   ```

2. **Install dependencies**
   ```bash
   uv sync
   ```

---

## Usage

Run the tool against your Laravel project directory (defaults to `app/`):

```bash
cd your-laravel-project
source /path/to/stangent/.venv/bin/activate

uv run /path/to/stangent/main.py \
  --initial-stan-level 0 \
  --max-stan-level 10 \
  --directories app \
  --model gpt-4.1 \
  --max-turns 10
```

- `--initial-stan-level`: PHPStan level to start from (0–8).
- `--max-stan-level`: Highest PHPStan level to attempt.
- `--directories`: Target directories (comma-separated - currently ignored - uses the config in your phpstan.neon file).
- `--model`: OpenAI model to use (default: gpt-4.1).
- `--max-turns`: Max AI “turns” (iterations) per run of the agent (default 10).

Upon completion, the tool will have written PHP code fixes directly into your files for your review.

---

## How It Works

1. **Project Structure**
   `get_project_structure()` scans non-hidden files/dirs and reports a tree with counts.
2. **Prompt Generation**
   A Jinja2 template (`prompts/fix.jinja`) is rendered with the structure.
3. **Agent Setup**
   An AI “Agent” (from `openai-agents`) is created with:
   - Name: **PHPStan Fix**
   - Instructions from the rendered prompt
   - Tools: `read_file`, `write_file`, `run_phpstan`
4. **Automated Loop**
   - Run PHPStan at the current level
   - Parse errors (only `App\` namespace)
   - Read, edit, and rewrite files to resolve each error
   - Increment level and repeat until success or reaching `--max-stan-level`

Core logic in `main.py` orchestrates this process.

---

## Configuration

- **PHPStan path**
  Adjust `PHPSTAN_PATH` in `main.py` if needed (default `./vendor/bin/phpstan`).
- **Template tweaks**
  Edit `prompts/fix.jinja` to modify AI instructions or error-filter rules.

---

## Development

- The entry point is `main.py`.
- Key functions are decorated with `@function_tool` for AI invocation:
  - `read_file(file_path: str) → str`
  - `write_file(file_path: str, content: str) → str`
  - `run_phpstan(level: int, directories: str) → str`
- Project metadata in `pyproject.toml`.

To run tests or experiment interactively:

```bash
uv run main.py --help
```

---

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Make your changes and add tests if applicable.
4. Open a pull request.

Please ensure that all code changes maintain compatibility with Python 3.13 and the existing CLI interface.

---

## Acknowledgments

- [openai-agents](https://pypi.org/project/openai-agents)
- Jinja2 for templating
