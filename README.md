# Cellar Notes

Cellar Notes is a self-hosted, local-first wine cellar and tasting journal. It
provides a responsive web app for managing bottles and storage locations,
scanning labels, exploring wine catalogs, and recording tasting notes. The app
runs with FastAPI and SQLite; optional external services provide catalog data,
email, and cloud vision.

See [`wine-app/README.md`](./wine-app/README.md) for detailed feature
documentation, provider configuration, account management, QR label generation,
and systemd deployment.

## Features

- Manage bottle records and nested storage locations, individually or in
  batches.
- Scan bottle labels using local Ollama vision, with optional OpenRouter and
  WineAPI.io fallbacks.
- Search WineAPI.io and Grapeminds catalogs and apply wine details to bottle
  records.
- Track purchase and market prices, drinking windows, and bottle checkout
  history.
- Browse the collection as cards or a sortable table; filter, search, and
  export visible bottles to CSV.
- Record personal tasting notes and keep catalog notes and food pairings with
  each wine.
- Use QR codes to identify bottles and generate printable bottle labels.
- Protect cellar access with user accounts, roles, and administrator controls.

## Requirements

- Python 3.10 or newer.
- Ollama with a vision-capable model for local label scanning, or configure
  OpenRouter and/or WineAPI.io for cloud-based scanning.
- Optional API keys for WineAPI.io and Grapeminds to use live catalog lookups.
  Grapeminds mock mode is available for development.

## Run locally

Create a virtual environment and install dependencies:

```sh
cd wine-app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the sample configuration and edit `wine-app/.env`:

```sh
cp .env.example .env
```

Set a unique `CELLAR_PASSWORD` with at least 10 characters and a
`CELLAR_SESSION_SECRET` with at least 32 random characters. Add provider API
keys only for services you plan to use. `.env.auth` is also supported for
secrets; its values fill in keys not set in `.env`. See
[`wine-app/.env.example`](./wine-app/.env.example) for the complete list of
settings, including session lifetime, storage paths, provider limits, and
network timeouts.

Start the app from `wine-app/`:

```sh
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open <http://127.0.0.1:8000/> on the host computer. To use the app from another
device on the same network, open `http://<host-computer-ip>:8000/`; allow
inbound connections on port 8000 in the host firewall. Set
`CELLAR_COOKIE_SECURE=true` when serving the app over HTTPS; use `false` only
for local HTTP development.

## Data and tests

The SQLite database is stored in `wine-app/wine_cellar.db`. Label images and
provider cache and usage data are stored alongside the app. Database files,
uploads, and environment files are excluded from Git; back up the database and
label images separately to preserve your cellar.

Run the test suite from `wine-app/`:

```sh
.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

## Acknowledgments

Development of Cellar Notes was assisted by Google Gemini, MiniMax-M3,
GitHub Copilot, and Qwen 2.5 Coder. We thank the teams behind these tools for
their contributions to the project.

## License

This project is licensed under the GNU General Public License, version 3 or
(at your option) any later version. See [LICENSE](./LICENSE) for the full text.
