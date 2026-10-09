# Quality System Demo

A generic commercial demonstration of digital quality-process documentation for manufacturing companies. The interface uses **Your Company** and contains no customer-specific brand.

## Version 1.2.0

Bright day theme with JetBrains Mono / Consolas, separate IPQC and CTQ workspaces and separate summaries. CTQ reports appear in order: Gel, Ribbon Peel, Adhesion, Busbar Peel. The IPQC checkpoint strip supports direct selection, mobile swipe and completion tracking. Checkpoints and limits are illustrative demo content, not a customer production specification. Existing databases are preserved.

## Demonstrated workflow

1. Operator creates a report or saves a draft.
2. Operator submits the completed record to a selected incharge or administrator.
3. The reviewer approves, approves with remarks, returns for correction, or rejects it.
4. Every action is stored in the audit history.
5. The controlled record can be downloaded as a PDF.

## Demo reports

- IPQC Checksheet — 37 illustrative checkpoints with sliding Previous/Next navigation
- Gel Content Test — one controlled percentage result
- Adhesion Test — one controlled strength result
- Ribbon Peel Test — one average force with automatic N/mm calculation
- Busbar Peel Test — one average force with automatic N/mm calculation

## Demo accounts

All three accounts use password `Demo123`.

| Role | Employee ID |
|---|---|
| Operator | `OP100` |
| Shift incharge | `IC100` |
| Administrator | `AD100` |

These credentials are for demonstration only and must not be used for a live production installation.

## Run on Windows

Install Python 3.12 or newer, extract the complete project and double-click:

```text
start_demo.bat
```

Open on the server:

```text
http://127.0.0.1:8080
```

Other computers on the same network open:

```text
http://SERVER-IP:8080
```

Allow inbound TCP port 8080 in Windows Firewall and configure a static IP or DHCP reservation for the server computer.

## Manual start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Linux/macOS activation uses `source .venv/bin/activate`.

## Railway

The included `railway.json` starts the Flask application through Waitress. Attach a persistent volume at `/app/data` and set:

```text
QUALITYSYSTEM_DATA=/app/data
QUALITYSYSTEM_SECRET=<a-long-random-secret>
QUALITYSYSTEM_HTTPS=1
```

## Storage

The application stores its SQLite database at `data/qualitysystem.db`. Keep it on the same computer as the application. Back up the `data` directory regularly; never replace the live database during an application update.

## Commercialisation note

This repository is a demonstration, not a validated production QMS. A customer deployment should add company configuration, controlled master-data management, HTTPS, automated backups, a signed installer/service, licence controls, validation documentation and an agreed retention policy.

