# FIX JSON Parser

This repository contains `fix_codesets_scraper.py`, a small scraper that fetches FIX code-sets and their standard values from http://fiximate.fixtrading.org and writes them to `fix_code_sets.json`.

Contents
- `fix_codesets_scraper.py` — main script (uses `requests` + `beautifulsoup4`).
- `requirements.txt` — Python dependencies.
- `.env` — optional configuration (not checked into source control by default).

Prerequisites
- Python 3.8+ (this workspace uses a configured venv with Python 3.14)

Recommended quick setup (create a venv, install deps)

1) Create a virtual environment (recommended):

```bash
python3 -m venv .venv
```

2) Activate the venv (bash):

```bash
source .venv/bin/activate
```

3) Upgrade pip and install requirements:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Alternative: if you already have the project's configured venv, use that directly (example from this workspace):

```bash
/path/to/venv/bin/python -m pip install -r requirements.txt
```

Run the script

With the venv active:

```bash
python fix_codesets_scraper.py
```

Or using the workspace venv directly:

```bash
/path/to/venv/bin/python fix_codesets_scraper.py
```

The script writes `fix_code_sets.json` into the current directory. When it finishes it prints a green success message.

Configuration via `.env`
Create a file named `.env` in the project root (the repo already includes one in the workspace). Supported keys:

- `VERSION_NAME` — base name for generated version (the script appends timestamp). Example: `VERSION_NAME=1.0.0`.
- `AUTHOR` — author name to include in the JSON output. Example: `AUTHOR=Pico`.
- `PER_REQUEST_TIMEOUT` — per-request timeout in seconds (default 15).
- `TOTAL_TIMEOUT` — global timeout for all detail-page fetches in seconds (default 400).
- `MAX_WORKERS` — thread pool size (default derived from CPUs, capped by code).

Notes on parsing
- `stdValues` are extracted only from the detected "description" column in a detail page.
- Inside the description cell the script expects a nested table with rows like:

  `<tr><td>1</td><td>=</td><td>Some description</td></tr>`

  The script will only accept rows where the middle TD contains `=` and will use the first TD as the `id` and the third TD as the `description`.

Troubleshooting
- If you see `ModuleNotFoundError` for `bs4` or `tqdm`, make sure you installed requirements into the active Python environment:

```bash
python -m pip install -r requirements.txt
```

- If the site is unreachable or the script hangs, increase `TOTAL_TIMEOUT` in `.env` or check your network.

- The script will print progress while fetching detail pages using a progress bar (requires `tqdm`).

