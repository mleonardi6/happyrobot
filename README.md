# happyrobot

Small Python service for working with load data and PostHog instrumentation.

Repository contents
- `Dockerfile` — Docker image definition for the app
- `fly.toml` — example Fly deployment configuration
- `loads.json` — sample load data used by the service
- `main.py` — application entrypoint
- `posthog-setup-report.md` — notes about PostHog setup and instrumentation
- `requirements.txt` — Python dependencies

Getting started

Prerequisites
- Python 3.9+ (or your preferred 3.x from `requirements.txt`)
- pip
- Docker (optional, for containerized run)

Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run locally

The project entrypoint is `main.py`. Start it with:

```bash
python main.py
```

If the app listens on a port, it will be shown in the process output. Adjust commands as needed for your environment.

Using Docker

Build and run the container locally:

```bash
docker build -t happyrobot .
docker run -p 8000:8000 happyrobot
```

Deployment

This repo includes a `fly.toml` for deploying to Fly.io. Use the Fly CLI to deploy if desired.

Configuration & secrets

- The app may require API keys or PostHog credentials. Do NOT commit secrets to the repository. Set environment variables before running, for example:

```bash
export CARRIER_API_KEY="your-carrier-api-key"
export POSTHOG_API_KEY="your-posthog-api-key"
```

Inspecting sample data

- `loads.json` contains example load entries used by the service. Modify or replace this file to test with different input.

Example request

Replace `<API_KEY>` and any other placeholders before running:

```bash
curl -X POST https://carrier-api.example.com/check-carrier \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_KEY>" \
  -d '{"mc_number": "1647339"}'
```

**Main.py Overview**

- The service is a FastAPI app defined in `main.py` and exposes three primary endpoints:
  - `POST /check-carrier`: accepts `{mc_number}` and an `X-API-Key` header, queries the FMCSA API, evaluates whether the carrier can book loads, returns an evaluation object, and emits PostHog events.
  - `POST /load`: returns a load from `loads.json` selected by `load_id`, by `state`, or randomly; requires the API key and emits PostHog events for not-found or retrieval.
  - `POST /analytics`: accepts analytics payloads (rate, classifications, `mc_number`, `carrier_name`, `load_id`, etc.), enriches with load metadata when available, and captures a `call_completed` event in PostHog.

- Configuration is read from environment variables (`FMCSA_WEB_KEY`, `API_KEY`, `POSTHOG_PROJECT_TOKEN`, `POSTHOG_HOST`). The app uses the PostHog Python client to send events and flushes them after actions.

- To run the API server locally use an ASGI server, for example:

```bash
uvicorn main:app --reload --port 8000
```

Notes
- See `posthog-setup-report.md` for background on how PostHog was configured and any tracking decisions.

Contributing

- Open an issue or submit a pull request. Keep changes minimal and focused.

License

- No license specified. Add a `LICENSE` file if you intend to open-source the project.

Contact

- Maintainer: Mark Leonardi
