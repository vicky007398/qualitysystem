# Your Company QMS — QMS 1.4.0

This independent system retains the full forms from `vicky007398/qms`, with generic company branding and the navy, emerald, and cyan theme. It uses its own local database and does not connect to the original installation.

## Demo scope

- Separate IPQC and CTQ main tabs, summaries, records and daily PDF downloads.
- The original 36 process stages, plus Basic Information and Review, with the original sliding navigation.
- Full IPQC: 166 parameters and 860 observation fields across 36 stages, including all Stringer tables, three chambers across four Laminators, and the HV / IR / Ground Continuity matrix.
- Full CTQ: five Gel samples; Ribbon Peel with six tracks, both sides, 16 positions and seven peaks; four Adhesion readings per group; 16 Busbar readings per enabled interconnector.
- Original sidebar, theme switch, account menu, password change, draft deletion and audit history.
- Red accents on a dark background are the default. Every account can choose Red, Blue, Green, or Purple and light/dark mode under Account menu → Appearance & colours. Settings are saved to the account and follow the user across devices.
- Field labels, criteria, supplier options, sample counts, and calculations are preserved from the original QMS. Company identifiers use generic QMS branding.

## Windows

Install Python 3.12 or newer, extract this project into its own folder, then run `start_demo.bat`. The first run needs internet to install dependencies.

Open `http://127.0.0.1:8080`; other devices on the same network use `http://SERVER-IP:8080`.

## Accounts

Password for all demo accounts: `Demo123`.

| Employee ID | Role |
|---|---|
| OP100 | Operator — entry and drafts |
| IC100 | Shift incharge — assigned approvals |
| AD100 | Administrator — review and monitoring |
| 0001 | Super User — account management only |

## Render or Railway

Build: `pip install -r requirements.txt`

Start: `python app.py`

The server binds to `0.0.0.0` and uses the host-provided `PORT`, or local port 8080.

Use a persistent writable directory and set `QUALITYSYSTEM_DATA` to that directory. Set `QUALITYSYSTEM_HTTPS=1` when the site uses HTTPS.

## Updating the earlier demo

Stop the demo server. Back up its `data` folder, then replace only application files. Keep the `data` folder in the new demo folder.

The new database is `data/commercial-demo.db`. On first startup, an existing `data/qualitysystem.db` is imported without modifying or deleting it. Earlier record values, accounts and audit history are retained. No production database or production QMS environment variables are used.

Existing records retain their saved values. Earlier reduced drafts must have the restored required fields completed before submission.

## Validation

Run `.venv/bin/python tools/smoke_test.py` from the project directory. The suite uses a temporary database and checks full IPQC fields, CTQ calculations and submissions, approvals, access controls, dashboards, and PDFs.

## Separate customer landing page

`marketing/SolarQMS-Landing.html` is a standalone presentation page with embedded assets. Download and open it separately or host it as a separate website. The QMS application opens directly at login; the supplied factory photograph is used only on its login screen.
