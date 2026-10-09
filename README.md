# Your Company QMS — Commercial Demo 1.3.0

This independent demo uses the original QMS interface, navigation, tables, approval workflow and PDF formatting. It contains generic company branding and reduced example fields. It does not connect to the Navitas production installation.

## Demo scope

- Separate IPQC and CTQ main tabs, summaries, records and daily PDF downloads.
- The original 36 process stages, plus Basic Information and Review, with the original sliding navigation.
- One representative parameter in most stages; three small Stringer tables and two recipe parameters across four Laminators.
- CTQ in order: Gel, Ribbon Peel, Adhesion, Busbar Peel. Reduced sample counts retain the same table layouts, approval controls and calculations.
- Original sidebar, theme switch, account menu, password change, draft deletion and audit history.
- Light theme is the default; the original dark theme remains selectable.
- All values and criteria are demonstration content rather than a validated customer specification.

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

Earlier drafts can be updated using the new reduced form, which requires the current demo fields before resubmission.
