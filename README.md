# Portfolio Radar

A private, dependency-free local investment research workspace. Start the server with `python server.py` and open <http://127.0.0.1:8000>. Press Ctrl+C to stop it.

## What works

- Monitoring dashboard with sample priorities, data freshness, upcoming events, coverage and monitoring status.
- Search and category filters for discovery cards, with expandable evidence trails.
- Company trackers with theses, sample metrics, risks, evidence provenance and change history.
- Consistent discovery, earnings, deterioration and weekly-review outlines.
- Local notes and watchlist toggles persisted in `data/user_state.json`.
- Responsive desktop/mobile interface.
- A tested metric-change calculation exposed as a backend research tool.
- Manual, per-company OpenAI analysis of the supplied tracker data when locally configured.
- Opt-in local scheduler: once daily at 09:00 local time, analyzing saved-watchlist companies only.
- Monitoring controls for enabling, pausing and running immediately, with timestamps and per-company outcomes.

## What is simulated

Every company, metric, finding, event, evidence source, timestamp and history entry in `data/seed.json` is fictional sample content. It is not live research, a recommendation, or a real portfolio. The OpenAI integration performs a real model call only when manually triggered or when you explicitly enable the daily monitor; analysis is limited to supplied tracker content, fictional in this starter dataset. It does not browse or fetch current facts. Broker data remains disabled. The dashboard's sample dates are illustrative and should not be relied on.

No trading functionality is implemented. Without manually triggering analysis or explicitly enabling monitoring, the app makes no outbound provider calls. It does not collect credentials in the UI or chat.

## OpenAI research provider

Set `OPENAI_API_KEY` in the local environment before starting the app; optionally set `OPENAI_MODEL` (default `gpt-4.1-mini`). For example, in PowerShell, set `$env:OPENAI_API_KEY` in the same terminal session used to run `python server.py`. Never paste credentials into chat or commit them.

Before each manual run or monitoring opt-in, the interface asks for confirmation and explains that company name, ticker, sector, thesis, metrics, risks and evidence are sent to OpenAI. Notes and watchlist membership are not sent. Manual runs are per-company. The opt-in scheduler checks daily at 09:00 local time while the app server is running, and analyzes the saved watchlist sequentially. Enable/pause and “Run now” controls are on the dashboard. The next run is shown with the local timezone; runs while the app is stopped are not queued, and an enabled schedule resumes when the app restarts. Reports distinguish supplied facts, assumptions, interpretation, risks and open questions; they are stored locally in `data/user_state.json` with provider, model, trigger, scope and timestamp. The app does not independently verify model output. Per-company provider errors appear in monitoring outcomes; failed reports are not saved as successful results.

This app is local-first and binds only to `127.0.0.1` by default. A single-user password gate is available for a private reverse-proxy deployment:

- Set `PORTFOLIO_RADAR_PASSWORD` in the server environment to a unique password of at least 12 characters. It is never stored in source or JSON. The app checks it with PBKDF2, issues an HttpOnly/SameSite session cookie, enforces CSRF tokens on state-changing requests, expires idle sessions and throttles repeated failed logins. Sessions are in memory and end when the server restarts.
- Set `PORTFOLIO_RADAR_SECURE_COOKIES=true` when HTTPS terminates at the reverse proxy.
- Keep this Python server bound to loopback (`PORTFOLIO_RADAR_HOST=127.0.0.1`) and place it behind a TLS reverse proxy on the selected host. A direct non-loopback bind requires a strong local password and secure cookies, but the app itself does not provide TLS. Never expose its development HTTP server directly to the public internet.
- Baseline CSP, anti-framing, MIME-sniffing and referrer headers are set by the app. Configure HTTPS/HSTS at the TLS proxy, backups, host updates/firewall, monitoring and secure environment-variable handling before launch.

No cloud deployment has been performed yet. This remains a single-user service; it does not provide multi-user accounts, persistent session storage, database backups or production operations tooling. Treat this hardening as a starting point, not a claim of deployment readiness.

## Render private deployment preparation

`render.yaml` prepares a Render web service in Frankfurt with HTTPS cookies, a single-user password gate, an unauthenticated `/healthz` check, and a 1 GB persistent disk for `data/user_state.json`. The app binds to Render's injected `PORT`; local runs still default to `127.0.0.1:8000`. `TZ=Europe/Copenhagen` keeps the opt-in 09:00 monitoring schedule aligned with Copenhagen time (including daylight-saving changes). The `starter` instance and persistent disk are paid Render resources—review current pricing before creating them.

To deploy, push this folder to a private GitHub repository and create a Render Blueprint from it. During setup, enter a unique `PORTFOLIO_RADAR_PASSWORD` of at least 12 characters into Render's secret prompt; never put it in this repository or chat. After creation, verify the generated HTTPS URL, login, note/watchlist persistence across a service restart, and sign-out. `OPENAI_API_KEY` is optional and should only be added through Render's secret manager if you explicitly want live OpenAI analysis; otherwise research stays fictional/demo-only. No Render service has been created from this workspace.

`BrokerDataProvider` in `server.py` remains an unconfigured seam and fails explicitly. The scheduler is opt-in, local-process-bound, and records run state, time and per-company failures. Keep calculations in explicit tested tools and label any future data with its actual source and retrieval timestamp.

User notes and watchlists are written as plain JSON to `data/user_state.json`; avoid storing confidential information in this demo. Delete that specific file to reset local user state (the app recreates the starter watchlist on next launch).

## Tests

Run `python -m unittest discover -s tests -v` using Python 3.10 or newer. The app itself uses only the Python standard library.
