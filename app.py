import io
import json
import os
import secrets
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("QUALITYSYSTEM_DATA", ROOT / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "qualitysystem.db"

app = Flask(__name__)
app.secret_key = os.environ.get("QUALITYSYSTEM_SECRET", "qualitysystem-demo-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("QUALITYSYSTEM_HTTPS") == "1",
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)


REPORTS = {
    "ipqc": {
        "title": "IPQC Checksheet",
        "short": "IPQC",
        "description": "A compact in-process inspection flow covering the production line.",
        "sections": [
            {"name": "Material Verification", "parameter": "Front glass condition", "criterion": "Clean and free from damage", "fields": [
                {"key": "glass_condition", "label": "Observation", "type": "select", "options": ["OK", "Not OK"]}
            ]},
            {"name": "Stringing", "parameter": "Soldering temperature", "criterion": "380 ± 20 °C", "fields": [
                {"key": "soldering_temperature", "label": "Temperature", "type": "number", "unit": "°C", "min": 360, "max": 400}
            ]},
            {"name": "Lamination", "parameter": "Lamination temperature", "criterion": "145 ± 5 °C", "fields": [
                {"key": "lamination_temperature", "label": "Temperature", "type": "number", "unit": "°C", "min": 140, "max": 150}
            ]},
            {"name": "Final Inspection", "parameter": "Module visual condition", "criterion": "No visible defect", "fields": [
                {"key": "final_visual", "label": "Observation", "type": "select", "options": ["OK", "Not OK"]}
            ]},
        ],
    },
    "stringer": {
        "title": "Stringer Parameter Report",
        "short": "Stringer",
        "description": "One representative process parameter across six stringer tracks.",
        "sections": [{
            "name": "Stringer Process Matrix",
            "parameter": "Solder base plate temperature",
            "criterion": "100 ± 30 °C",
            "layout": "matrix",
            "fields": [
                {"key": key, "label": label, "type": "number", "unit": "°C", "min": 70, "max": 130}
                for key, label in [
                    ("stringer_1a", "Stringer 1A"), ("stringer_1b", "Stringer 1B"),
                    ("stringer_2a", "Stringer 2A"), ("stringer_2b", "Stringer 2B"),
                    ("stringer_3a", "Stringer 3A"), ("stringer_3b", "Stringer 3B"),
                ]
            ],
        }],
    },
    "gel": {
        "title": "Gel Content Test",
        "short": "Gel Test",
        "description": "A one-value CTQ demonstration with automatic acceptance evaluation.",
        "sections": [{"name": "Gel Content", "parameter": "Average gel content", "criterion": "75–95%", "fields": [
            {"key": "gel_content", "label": "Gel content", "type": "number", "unit": "%", "min": 75, "max": 95}
        ]}],
    },
    "adhesion": {
        "title": "Adhesion Test",
        "short": "Adhesion",
        "description": "A single adhesion-strength result with controlled minimum criteria.",
        "sections": [{"name": "Adhesion Strength", "parameter": "Encapsulant-to-glass adhesion", "criterion": "≥ 60 N/cm", "fields": [
            {"key": "adhesion_strength", "label": "Average strength", "type": "number", "unit": "N/cm", "min": 60}
        ]}],
    },
    "ribbon_peel": {
        "title": "Ribbon Peel Test",
        "short": "Ribbon Peel",
        "description": "A representative peel reading with automatic N/mm calculation.",
        "sections": [{"name": "Ribbon Peel Strength", "parameter": "Average ribbon peel force", "criterion": "≥ 0.80 N", "fields": [
            {"key": "ribbon_average_n", "label": "Average force", "type": "number", "unit": "N", "min": 0.8, "calculation": "n_per_mm"}
        ]}],
    },
    "busbar_peel": {
        "title": "Busbar Peel Test",
        "short": "Busbar Peel",
        "description": "A representative busbar peel reading with automatic N/mm calculation.",
        "sections": [{"name": "Busbar Peel Strength", "parameter": "Average busbar peel force", "criterion": "≥ 2.00 N", "fields": [
            {"key": "busbar_average_n", "label": "Average force", "type": "number", "unit": "N", "min": 2, "calculation": "n_per_mm"}
        ]}],
    },
}

STATUSES = ["Draft", "Pending Approval", "Returned for Correction", "Approved", "Approved with Remarks", "Rejected"]
FINAL_STATUSES = {"Approved", "Approved with Remarks", "Rejected"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA busy_timeout=5000")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    with app.app_context():
        db().executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, employee TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('operator','incharge','admin')),
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS reports (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, day TEXT NOT NULL, shift TEXT NOT NULL,
          line TEXT NOT NULL, reference TEXT NOT NULL, customer TEXT NOT NULL,
          owner INTEGER NOT NULL REFERENCES users(id), approver INTEGER REFERENCES users(id),
          status TEXT NOT NULL, result TEXT NOT NULL, payload TEXT NOT NULL,
          remarks TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
          created TEXT NOT NULL, updated TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY, report INTEGER NOT NULL REFERENCES reports(id),
          actor INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
          comment TEXT NOT NULL, time TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS reports_owner ON reports(owner,updated);
        CREATE INDEX IF NOT EXISTS reports_approver ON reports(approver,status);
        CREATE INDEX IF NOT EXISTS reports_kind ON reports(kind,day);
        """)
        users = db().execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if not users:
            demo_password = generate_password_hash("Demo123")
            db().executemany(
                "INSERT INTO users(employee,name,password,role) VALUES (?,?,?,?)",
                [
                    ("OP100", "Demo Operator", demo_password, "operator"),
                    ("IC100", "Demo Incharge", demo_password, "incharge"),
                    ("AD100", "Demo Administrator", demo_password, "admin"),
                ],
            )
        db().commit()


def csrf():
    session.setdefault("csrf", secrets.token_urlsafe(32))
    return session["csrf"]


@app.before_request
def security():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    csrf()
    if request.method == "POST" and not secrets.compare_digest(request.form.get("csrf", ""), session["csrf"]):
        abort(400, "Session expired. Reload the page and try again.")


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def template_context():
    return {"user": g.user, "csrf": csrf(), "reports_def": REPORTS, "statuses": STATUSES}


def require(*roles):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for("login"))
            if roles and g.user["role"] not in roles:
                abort(403)
            return function(*args, **kwargs)
        return wrapped
    return decorate


def field_definitions(kind):
    return [field for section in REPORTS[kind]["sections"] for field in section["fields"]]


def evaluate(kind, values):
    outcomes = []
    calculations = {}
    for field in field_definitions(kind):
        value = values.get(field["key"], "")
        if value == "":
            continue
        if field["type"] == "select":
            outcomes.append(value == field["options"][0])
        elif field["type"] == "number":
            try:
                number = float(value)
            except (TypeError, ValueError):
                outcomes.append(False)
                continue
            outcomes.append(("min" not in field or number >= field["min"]) and ("max" not in field or number <= field["max"]))
            if field.get("calculation") == "n_per_mm":
                calculations[field["key"] + "_n_per_mm"] = round(number / 0.24, 3)
    total = len(field_definitions(kind))
    completed = sum(values.get(field["key"], "") != "" for field in field_definitions(kind))
    result = "Not evaluated" if not outcomes else "PASS" if completed == total and all(outcomes) else "FAIL" if completed == total else "In progress"
    return result, calculations, completed, total


def visible_reports():
    if g.user["role"] == "admin":
        where, params = "1=1", []
    elif g.user["role"] == "incharge":
        where, params = "(r.approver=? OR r.owner=?)", [g.user["id"], g.user["id"]]
    else:
        where, params = "r.owner=?", [g.user["id"]]
    return db().execute(f"""
      SELECT r.*, o.name AS owner_name, a.name AS approver_name
      FROM reports r JOIN users o ON o.id=r.owner LEFT JOIN users a ON a.id=r.approver
      WHERE {where} ORDER BY r.updated DESC, r.id DESC
    """, params).fetchall()


def get_report(report_id):
    report = db().execute("""
      SELECT r.*, o.name AS owner_name, a.name AS approver_name
      FROM reports r JOIN users o ON o.id=r.owner LEFT JOIN users a ON a.id=r.approver
      WHERE r.id=?
    """, (report_id,)).fetchone()
    if not report:
        abort(404)
    allowed = g.user["role"] == "admin" or report["owner"] == g.user["id"] or report["approver"] == g.user["id"]
    if not allowed:
        abort(403)
    return report


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("home"))
    if request.method == "POST":
        employee = request.form.get("employee", "").strip().upper()
        user = db().execute("SELECT * FROM users WHERE employee=? AND active=1", (employee,)).fetchone()
        if user and check_password_hash(user["password"], request.form.get("password", "")):
            session.clear()
            session["uid"] = user["id"]
            csrf()
            return redirect(url_for("home"))
        flash("Employee ID or password is incorrect.")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@require()
def home():
    rows = visible_reports()
    counts = {status: sum(row["status"] == status for row in rows) for status in STATUSES}
    kind_counts = {kind: sum(row["kind"] == kind for row in rows) for kind in REPORTS}
    return render_template("home.html", rows=rows, counts=counts, kind_counts=kind_counts)


def clean_values(kind, submitted, require_all):
    values = {}
    for field in field_definitions(kind):
        value = submitted.get(field["key"], "").strip()
        if len(value) > 100:
            raise ValueError("A value is too long.")
        if require_all and not value:
            raise ValueError(f"Complete {field['label']} before submission.")
        if value and field["type"] == "number":
            try:
                float(value)
            except ValueError as error:
                raise ValueError(f"{field['label']} must be numeric.") from error
        if value and field["type"] == "select" and value not in field["options"]:
            raise ValueError(f"Select a valid value for {field['label']}.")
        values[field["key"]] = value
    return values


@app.route("/new/<kind>", methods=["GET", "POST"])
@require("operator", "admin")
def new_report(kind):
    if kind not in REPORTS:
        abort(404)
    approvers = db().execute("SELECT id,name,employee,role FROM users WHERE active=1 AND role IN ('incharge','admin') ORDER BY role DESC,name").fetchall()
    current = {"day": date.today().isoformat(), "shift": "A", "line": "Line 1", "reference": "", "customer": "", "approver": "", "values": {}}
    if request.method == "POST":
        action = request.form.get("action", "draft")
        try:
            values = clean_values(kind, request.form, action == "submit")
            approver = int(request.form.get("approver", "0")) if request.form.get("approver") else None
            if action == "submit" and not approver:
                raise ValueError("Select an approver before submission.")
            day = request.form.get("day", "").strip()
            datetime.strptime(day, "%Y-%m-%d")
            shift = request.form.get("shift", "")
            if shift not in ("A", "B", "C"):
                raise ValueError("Select a valid shift.")
            line = request.form.get("line", "").strip()
            reference = request.form.get("reference", "").strip()
            customer = request.form.get("customer", "").strip()
            if action == "submit" and not all([line, reference, customer]):
                raise ValueError("Complete line, reference number and customer name.")
            result, calculations, _completed, _total = evaluate(kind, values)
            payload = json.dumps({"version": "DEMO-1", "values": values, "calculations": calculations})
            status = "Pending Approval" if action == "submit" else "Draft"
            timestamp = now()
            with db():
                cursor = db().execute("""
                  INSERT INTO reports(kind,day,shift,line,reference,customer,owner,approver,status,result,payload,created,updated)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (kind, day, shift, line, reference, customer, g.user["id"], approver, status, result, payload, timestamp, timestamp))
                report_id = cursor.lastrowid
                db().execute("INSERT INTO history(report,actor,action,comment,time) VALUES (?,?,?,?,?)",
                             (report_id, g.user["id"], "Submitted" if action == "submit" else "Draft saved", "", timestamp))
            flash("Report submitted for approval." if action == "submit" else "Draft saved.")
            return redirect(url_for("report_detail", report_id=report_id))
        except (ValueError, TypeError) as error:
            flash(str(error))
            current = {**request.form, "values": request.form}
    return render_template("form.html", kind=kind, definition=REPORTS[kind], report=current, approvers=approvers, editing=False)


@app.route("/edit/<int:report_id>", methods=["GET", "POST"])
@require("operator", "admin")
def edit_report(report_id):
    stored = get_report(report_id)
    if stored["owner"] != g.user["id"] or stored["status"] not in {"Draft", "Returned for Correction"}:
        abort(403)
    kind = stored["kind"]
    payload = json.loads(stored["payload"])
    approvers = db().execute("SELECT id,name,employee,role FROM users WHERE active=1 AND role IN ('incharge','admin') ORDER BY role DESC,name").fetchall()
    current = {**dict(stored), "values": payload.get("values", {})}
    if request.method == "POST":
        action = request.form.get("action", "draft")
        try:
            values = clean_values(kind, request.form, action == "submit")
            approver = int(request.form.get("approver", "0")) if request.form.get("approver") else None
            if action == "submit" and not approver:
                raise ValueError("Select an approver before submission.")
            result, calculations, _completed, _total = evaluate(kind, values)
            timestamp = now()
            status = "Pending Approval" if action == "submit" else "Draft"
            payload = json.dumps({"version": "DEMO-1", "values": values, "calculations": calculations})
            with db():
                db().execute("""
                  UPDATE reports SET day=?,shift=?,line=?,reference=?,customer=?,approver=?,status=?,result=?,payload=?,remarks='',version=version+1,updated=? WHERE id=?
                """, (request.form["day"], request.form["shift"], request.form["line"].strip(), request.form["reference"].strip(), request.form["customer"].strip(), approver, status, result, payload, timestamp, report_id))
                db().execute("INSERT INTO history(report,actor,action,comment,time) VALUES (?,?,?,?,?)",
                             (report_id, g.user["id"], "Resubmitted" if action == "submit" else "Draft updated", "", timestamp))
            flash("Report updated.")
            return redirect(url_for("report_detail", report_id=report_id))
        except (ValueError, TypeError) as error:
            flash(str(error))
            current = {**current, **request.form, "values": request.form}
    return render_template("form.html", kind=kind, definition=REPORTS[kind], report=current, approvers=approvers, editing=True)


@app.get("/report/<int:report_id>")
@require()
def report_detail(report_id):
    report = get_report(report_id)
    payload = json.loads(report["payload"])
    result, calculations, completed, total = evaluate(report["kind"], payload.get("values", {}))
    history = db().execute("SELECT h.*,u.name AS actor_name FROM history h JOIN users u ON u.id=h.actor WHERE h.report=? ORDER BY h.id", (report_id,)).fetchall()
    may_review = report["status"] == "Pending Approval" and (g.user["role"] == "admin" or report["approver"] == g.user["id"])
    return render_template("detail.html", report=report, definition=REPORTS[report["kind"]], payload=payload,
                           calculations=calculations, completed=completed, total=total, history=history, may_review=may_review)


@app.post("/report/<int:report_id>/review")
@require("incharge", "admin")
def review_report(report_id):
    report = get_report(report_id)
    if report["status"] != "Pending Approval" or (g.user["role"] != "admin" and report["approver"] != g.user["id"]):
        abort(403)
    action = request.form.get("action")
    comment = request.form.get("comment", "").strip()
    if action not in {"approve", "return", "reject"}:
        abort(400)
    if action in {"return", "reject"} and not comment:
        flash("A comment is required when returning or rejecting a report.")
        return redirect(url_for("report_detail", report_id=report_id))
    status = {"approve": "Approved with Remarks" if comment else "Approved", "return": "Returned for Correction", "reject": "Rejected"}[action]
    timestamp = now()
    with db():
        db().execute("UPDATE reports SET status=?,remarks=?,version=version+1,updated=? WHERE id=?", (status, comment, timestamp, report_id))
        db().execute("INSERT INTO history(report,actor,action,comment,time) VALUES (?,?,?,?,?)", (report_id, g.user["id"], status, comment, timestamp))
    flash(f"Report marked {status}.")
    return redirect(url_for("report_detail", report_id=report_id))


@app.post("/report/<int:report_id>/delete")
@require("operator", "admin")
def delete_report(report_id):
    report = get_report(report_id)
    if report["owner"] != g.user["id"] or report["status"] not in {"Draft", "Returned for Correction"}:
        abort(403)
    with db():
        db().execute("DELETE FROM history WHERE report=?", (report_id,))
        db().execute("DELETE FROM reports WHERE id=?", (report_id,))
    flash("Draft deleted.")
    return redirect(url_for("home"))


def report_pdf_data(report):
    payload = json.loads(report["payload"])
    definition = REPORTS[report["kind"]]
    styles = getSampleStyleSheet()
    story = [Paragraph("YOUR COMPANY", styles["Title"]), Paragraph(definition["title"], styles["Heading1"]), Spacer(1, 5 * mm)]
    meta = [
        ["Production date", report["day"], "Shift", report["shift"]],
        ["Line", report["line"], "Reference", report["reference"]],
        ["Customer", report["customer"], "Status", report["status"]],
        ["Prepared by", report["owner_name"], "Reviewed by", report["approver_name"] or "-"],
    ]
    meta_table = Table(meta, colWidths=[28 * mm, 54 * mm, 28 * mm, 54 * mm])
    meta_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#9aa9b8")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eaf0f6")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eaf0f6")), ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [meta_table, Spacer(1, 6 * mm)]
    rows = [["Stage", "Parameter", "Acceptance criteria", "Recorded value"]]
    values = payload.get("values", {})
    for section in definition["sections"]:
        for field in section["fields"]:
            value = values.get(field["key"], "-") or "-"
            display = f"{value} {field.get('unit', '')}".strip()
            rows.append([section["name"], section["parameter"], section["criterion"], f"{field['label']}: {display}"])
    table = Table(rows, colWidths=[35 * mm, 55 * mm, 48 * mm, 42 * mm], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .45, colors.HexColor("#73879a")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2742")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, 1), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [table, Spacer(1, 6 * mm), Paragraph(f"Evaluation: {report['result']}", styles["Heading2"])]
    if report["remarks"]:
        story.append(Paragraph(f"Approval remarks: {report['remarks']}", styles["BodyText"]))
    output = io.BytesIO()
    SimpleDocTemplate(output, pagesize=A4, title=definition["title"], author="Your Company", leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm).build(story)
    output.seek(0)
    return output


@app.get("/report/<int:report_id>.pdf")
@require()
def report_pdf(report_id):
    report = get_report(report_id)
    output = report_pdf_data(report)
    safe_title = REPORTS[report["kind"]]["short"].replace(" ", "-")
    return send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"{safe_title}-{report['day']}-Shift-{report['shift']}.pdf")


@app.route("/users", methods=["GET", "POST"])
@require("admin")
def users():
    if request.method == "POST":
        employee = request.form.get("employee", "").strip().upper()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        try:
            if not employee or not name or role not in {"operator", "incharge", "admin"}:
                raise ValueError("Complete all user details.")
            if not 5 <= len(password) <= 12:
                raise ValueError("Password must contain 5 to 12 characters.")
            with db():
                db().execute("INSERT INTO users(employee,name,password,role) VALUES (?,?,?,?)", (employee, name, generate_password_hash(password), role))
            flash("User created.")
            return redirect(url_for("users"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash("Employee ID already exists." if isinstance(error, sqlite3.IntegrityError) else str(error))
    rows = db().execute("SELECT employee,name,role,active FROM users ORDER BY role,name").fetchall()
    return render_template("users.html", rows=rows)


init_db()

if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("QUALITYSYSTEM_BIND", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("QUALITYSYSTEM_PORT", "8080")))
    print(f"Quality System Demo listening on http://{host}:{port}")
    serve(app, host=host, port=port)
