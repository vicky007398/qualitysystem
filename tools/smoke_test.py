"""End-to-end smoke test using a temporary QMS database."""
import io
import json
import os
import struct
import sys
import tempfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

test_data = tempfile.TemporaryDirectory(prefix="company-qms-test-")
os.environ["QUALITYSYSTEM_DATA"] = test_data.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.security import generate_password_hash

from app import (CTQ_DEF, CTQ_MATERIAL_OPTIONS, FORMS, IPQC_DEF, MATERIAL_FIELD_OPTIONS, app, ctq_default_values,
                 ctq_field_map, db, display_observation_value, ipqc_stage_progress, observation_unit,
                 prepare_ctq_payload, refreshed_ctq_payload)


class ObservationFieldParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("input", "select"):
            return
        attributes = dict(attrs)
        if attributes.get("data-item-id"):
            self.fields.append((
                attributes["data-item-id"],
                attributes.get("data-observation-index"),
                attributes.get("data-field-label"),
            ))


def csrf(client):
    with client.session_transaction() as session:
        return session["csrf"]


def login(client, employee, password):
    client.get("/login")
    response = client.post("/login", data={"employee": employee, "password": password, "csrf": csrf(client)})
    assert response.status_code == 302


def assert_complete_png(path):
    """Reject a truncated PNG even when a browser can decode its first rows."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    found_iend = False
    while offset < len(data):
        assert offset + 12 <= len(data)
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_end = offset + 12 + length
        assert chunk_end <= len(data)
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        stored_crc = struct.unpack(">I", data[offset + 8 + length:chunk_end])[0]
        assert zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF == stored_crc
        offset = chunk_end
        if chunk_type == b"IEND":
            found_iend = True
            break
    assert found_iend and offset == len(data)


with app.app_context():
    with db():
        db().execute("DELETE FROM users")
        for employee, name, role in [
            ("OP001", "Operator One", "operator"),
            ("OP002", "Operator Two", "operator"),
            ("IC001", "Incharge One", "incharge"),
            ("IC002", "Incharge Two", "incharge"),
            ("AD001", "Admin One", "admin"),
            ("0001", "User Custodian", "admin"),
        ]:
            db().execute(
                "INSERT INTO users(employee,name,password,role) VALUES (?,?,?,?)",
                (employee, name, generate_password_hash("Qms55"), role),
            )

client = app.test_client()
login_page = client.get("/login")
assert login_page.status_code == 200
assert b"login-shell" in login_page.data and b"data-theme-color" in login_page.data
assert b"Controlled inspection" in login_page.data
assert b"style.css?v=login-photo-1" in login_page.data and b"app.js?v=qms-appearance-1" in login_page.data
login_style = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(encoding="utf-8")
assert "v1.23 — edge-to-edge login photograph" in login_style
assert "v1.24 — keep every login element above one complete full-screen photograph" in login_style
assert "background-image:url('login-background.webp')" in login_style
assert "position:fixed;inset:0;width:100vw" in login_style
assert "height:100dvh" in login_style and "background-size:cover" in login_style
assert_complete_png(Path(__file__).resolve().parents[1] / "static" / "login-factory.png")
assert b"theme.css?v=qms-appearance-1" in login_page.data
assert b"Navitas" not in login_page.data
versioned_static = client.get("/static/style.css?v=1.27")
assert versioned_static.status_code == 200
assert "max-age=31536000" in versioned_static.headers["Cache-Control"]
assert "immutable" in versioned_static.headers["Cache-Control"]
assert "Server-Timing" in versioned_static.headers
assert login_page.headers["Cache-Control"] == "no-store"
assert "https://cdn.jsdelivr.net" in login_page.headers["Content-Security-Policy"]
assert "https://tessdata.projectnaptha.com" in login_page.headers["Content-Security-Policy"]
assert "worker-src 'self' blob:" in login_page.headers["Content-Security-Policy"]
assert "'wasm-unsafe-eval'" in login_page.headers["Content-Security-Policy"]
login(client, "OP001", "Qms55")
assert client.get("/users").status_code == 403

# Progress must be derived from saved observation values. Legacy drafts use
# "Not evaluated" even when some or all observation fields have been entered.
progress_sample = ipqc_stage_progress({"sections": [{"name": "Sample stage", "items": [
    {"result": "Not evaluated", "observations": [{"values": {"A": "OK", "B": ""}}]},
]}]})
assert progress_sample == [{"name": "Sample stage", "status": "In progress", "percent": 50}]
completed_progress = ipqc_stage_progress({"sections": [{"name": "Legacy filled stage", "items": [
    {"result": "Not evaluated", "observations": [{"values": {"A": "0", "B": "OK"}}]},
]}]})
assert completed_progress[0]["status"] == "Completed" and completed_progress[0]["percent"] == 100

home = client.get("/")
assert home.status_code == 200
assert b"desktop-sidebar" in home.data and b"Your Company Portal" in home.data
assert b'data-sidebar-toggle' in home.data and b'aria-controls="desktop-sidebar"' in home.data
assert b"QUALITY CONTROL</span>" not in home.data
assert b"IPQC ENTRY" in home.data and b"My IPQC records" in home.data
assert b"My IPQC summary" in home.data and b"0 IPQC records" in home.data
assert b"CTQ Test" in home.data and b"Gel Test" in home.data and b"Adhesion Test" in home.data
assert b"Ribbon Peel Test" in home.data and b"Busbar Peel Test" in home.data
assert b"DataPAQ Test" not in home.data
home_html = home.get_data(as_text=True)
assert home_html.index("Gel Test") < home_html.index("Ribbon Peel Test") < home_html.index("Adhesion Test") < home_html.index("Busbar Peel Test")
assert client.get("/new/stringer").status_code == 404
for ctq_kind in ["gel", "ribbon_peel", "adhesion", "busbar_peel"]:
    ctq_entry = client.get(f"/new/{ctq_kind}")
    assert ctq_entry.status_code == 200 and FORMS[ctq_kind][0].encode() in ctq_entry.data
    assert b"data-ctq-form" in ctq_entry.data
    assert b"data-ctq-pdf-import" in ctq_entry.data and b"Upload PDF" in ctq_entry.data
assert client.get("/new/datapaq").status_code == 404
assert client.get("/new/peel").status_code == 404
ribbon_entry = client.get("/new/ribbon_peel")
assert b"QMS/QAD/FM/L3/007" in ribbon_entry.data and b"Cell To Ribbon Peel Test Report" in ribbon_entry.data
assert b"Submit to incharge" in ribbon_entry.data and b"No test fields added" not in ribbon_entry.data
assert b"Average (N) \xc3\xb7 0.24 mm" in ribbon_entry.data and b"0.26 mm" not in ribbon_entry.data
assert ribbon_entry.data.count(b"data-ribbon-position") == 6 * 2 * 16
assert ribbon_entry.data.count(b"data-ribbon-peak") == 6 * 2 * 16 * 7
assert b"class=\"ribbon-nr\"" not in ribbon_entry.data
assert b"SolarSpace Technology (Laos) Sole Co., Ltd." in ribbon_entry.data
assert b"Taicang Juren PV Material Co., Ltd." in ribbon_entry.data
assert len(ctq_field_map("ribbon_peel")) == 1346
assert "rp_1a_front_s6_p2" in ctq_field_map("ribbon_peel")
busbar_entry = client.get("/new/busbar_peel")
assert b'data-ctq-calc="long_n_per_mm"' in busbar_entry.data
assert b'data-ctq-field="long_n_per_mm"' not in busbar_entry.data
assert b"Average (N) \xc3\xb7 0.24 mm" in busbar_entry.data

gel_rows = {"format": "ctq-v1", "values": ctq_default_values("gel")}
gel_rows["values"]["eva_manufacturer"] = "Trial Encapsulant Supplier"
gel_draft = client.post("/new/gel", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps(gel_rows),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "",
    "inspection_time": "2026-09-12T08:00",
    "approver": "",
    "remarks": "",
    "action": "draft",
})
assert gel_draft.status_code == 302
gel_detail = client.get(gel_draft.headers["Location"])
assert gel_detail.status_code == 200 and b"Gel Test" in gel_detail.data and b"Delete draft" in gel_detail.data
gel_id = int(gel_draft.headers["Location"].rstrip("/").split("/")[-1])
gel_edit = client.get(f"/edit/{gel_id}")
assert b'Trial Encapsulant Supplier' in gel_edit.data and b'value="__other__" selected' in gel_edit.data
with app.app_context():
    gel_version = db().execute("SELECT version FROM reports WHERE id=?", (gel_id,)).fetchone()["version"]
gel_removed = client.post(f"/report/{gel_id}/delete", data={"csrf": csrf(client), "version": gel_version})
assert gel_removed.status_code == 302 and client.get(gel_draft.headers["Location"]).status_code == 404

entry = client.get("/new/ipqc")
assert entry.status_code == 200
assert b"parameter-strip" in entry.data and b"viewport-fit=cover" in entry.data
assert b'data-page-scroll="up"' in entry.data and b'data-page-scroll="down"' in entry.data
assert b"data-material-select" in entry.data
assert b">Others</option>" in entry.data and b"data-material-other" in entry.data
assert b'name="meta_customer_name"' in entry.data and b"Customer name" in entry.data
assert b"Customer Specification Available" not in entry.data
assert b"Specification Signed Off With Customer" not in entry.data
assert entry.data.count(b"data-material-select") == 16
assert b"Reality Chemicals Pvt. Ltd." in entry.data
assert b"RC PV 44M" not in entry.data
assert b"data-result" not in entry.data and b"check-result" not in entry.data
assert b"stringer-matrix" in entry.data and b"lamp-matrix" in entry.data
assert b"Six-track process matrix" in entry.data and b"17 set-power fields" in entry.data
assert b"Set power" in entry.data and b"Standby power" in entry.data
assert b"Four-laminator matrix" in entry.data and b">Parameter</th>" in entry.data
app_script = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
assert "Copy selection" in app_script and "Paste table" in app_script and "Clear cells" in app_script and "enhanceEntryMatrix" in app_script
assert "if (!table.closest('[data-ctq-form]')) enhanceEntryMatrix(table)" in app_script
assert "data-ctq-pdf-import" in app_script and "Review detected PDF values" in app_script
assert "enhanceObservationArrowNavigation" in app_script and "spatialTarget" in app_script
assert "const peelDivisorMm = 0.24" in app_script
for laminator in [b"Laminator 1A", b"Laminator 1B", b"Laminator 2A", b"Laminator 2B"]:
    assert laminator in entry.data
laminator_item = next(item for section in IPQC_DEF["sections"] if section["name"] == "Laminator" for item in section["items"])
assert [observation["label"] for observation in laminator_item["observations"]] == [
    "Laminator 1A", "Laminator 1B", "Laminator 2A", "Laminator 2B"
]
assert all("Laminator number" not in observation["fields"] for observation in laminator_item["observations"])
expected_laminator_fields = [
    f"Chamber {chamber} · {field}"
    for chamber in range(1, 4)
    for field in [
        "Total Vacuum Time (s)", "Total Vacuum Delay (s)", "Upper Vacuum Time (s)",
        "Pressure 1 (kPa)", "Pressure 1 Hold (s)", "Pressure 2 (kPa)",
        "Pressure 2 Hold (s)", "Pressure 3 (kPa)", "Lamination (s)",
        "Lower Vacuum Time (s)", "Lower Vent Time (s)", "Temperature Setting (°C)",
        "Temperature Upper Limit (°C)", "Temperature Lower Limit (°C)", "Temperature Range",
        *(["Recipe Selection", "Upper Temp Setting"] if chamber == 1 else []),
    ]
]
assert all(observation["fields"] == expected_laminator_fields
           for observation in laminator_item["observations"])
assert b"Chamber 1" in entry.data and b"Chamber 3" in entry.data
assert entry.data.count(b'class="laminator-chamber-title"') == 3
assert b"<strong>Total Vacuum Time (s)</strong>" in entry.data
assert b"<strong>Chamber 1" not in entry.data
assert entry.data.count(b'data-photo-import=') == 2
assert b'data-photo-import="stringer"' in entry.data and b'data-photo-import="laminator"' in entry.data
assert b'Paste detected values' in entry.data and b'data-parameter-label=' in entry.data
assert b"Read the fixed machine screen from a scanned PDF" in entry.data and b"Upload PDF" in entry.data
assert "tesseract.js@5" in app_script and "findOcrCandidates" in app_script
assert "findBestTableValue" in app_script and "positionedOcrLines" in app_script
assert "findActValuesColumn" not in app_script
assert "worker.recognize(ocrPhoto, {rotateAuto: true}, {blocks: true})" in app_script
assert "prepareOcrPhoto" in app_script and "tessedit_pageseg_mode:'4'" in app_script
assert "Detecting PDF page direction" in app_script and "automatic orientation correction" in app_script
assert "Review detected table values" in app_script and "ACT Values column not found" not in app_script
assert "stringerPowerGrid" in app_script and "Standby Power" in app_script
assert "stringerActualGrid" in app_script and "laminatorTemplateGrid" in app_script
assert "renderPdfFirstPage" in app_script and "application/pdf" in entry.get_data(as_text=True)
assert "/api/render-pdf" in app_script and "pdfjsLib" not in app_script and "cdnjs.cloudflare.com" not in app_script
from reportlab.pdfgen import canvas
scanner_pdf = io.BytesIO()
scanner_page = canvas.Canvas(scanner_pdf, pagesize=(640, 480))
scanner_page.drawString(40, 420, "Drying Base 1    52.4")
scanner_page.showPage(); scanner_page.save(); scanner_pdf.seek(0)
rendered_page = client.post('/api/render-pdf', data={
    'csrf': csrf(client), 'pdf': (scanner_pdf, 'machine-screen.pdf', 'application/pdf')
}, content_type='multipart/form-data')
assert rendered_page.status_code == 200 and rendered_page.mimetype == 'image/png'
assert rendered_page.data.startswith(b'\x89PNG\r\n\x1a\n') and len(rendered_page.data) > 1000
invalid_pdf = client.post('/api/render-pdf', data={
    'csrf': csrf(client), 'pdf': (io.BytesIO(b'not a pdf'), 'machine-screen.pdf', 'application/pdf')
}, content_type='multipart/form-data')
assert invalid_pdf.status_code == 400
assert b"observation-count-2" in entry.data and b'data-unit="mm"' in entry.data
stringer_item_names = [
    item["parameter"]
    for section in IPQC_DEF["sections"] if section["name"] == "Stringer/Cell cutting section"
    for item in section["items"]
]
assert "Solder Base 1" in stringer_item_names and "Solder Base 2" in stringer_item_names
assert "Holding Base Plate" not in stringer_item_names and "Combined Plate" not in stringer_item_names
assert [name for name in stringer_item_names if "Drying Base" in name] == [
    "Drying Base 1", "Drying Base 2", "Drying Base 3", "Drying Base 4", "Drying Base 5",
]
assert "Auto-Flux" in stringer_item_names and "Manual-Flux" in stringer_item_names
assert "Cooling Base Temp" in stringer_item_names
assert "Set Power # 1" in stringer_item_names and "Set Power # 17" in stringer_item_names
assert "Standby Power # 1" in stringer_item_names and "Standby Power # 17" in stringer_item_names
assert "Light Intensity # 1" not in stringer_item_names
assert "Solder Time" not in stringer_item_names and "Groove laser 1-Head Groove (%)" not in stringer_item_names
assert stringer_item_names.index("Set Power # 1") < stringer_item_names.index("Standby Power # 1")
entry_html = entry.get_data(as_text=True)
solder_matrix_start = entry_html.index('class="stringer-matrix process-matrix"')
solder_matrix_end = entry_html.index('</table>', solder_matrix_start)
solder_matrix_html = entry_html[solder_matrix_start:solder_matrix_end]
assert solder_matrix_html.index("Solder Base 1") < solder_matrix_html.index("Solder Base 2")
assert entry_html.count('data-ipqc-item="R27B"') == 1
assert observation_unit("Glass dimension (L x W x T) (mm)", "L") == "mm"
assert observation_unit("String Length", "Observation") == "mm"
assert observation_unit("Anodizing thickness", "Observation") == "µm"
assert observation_unit("Light Intensity # 1", "Stringer 1 - Track A") == ""
assert display_observation_value("String Length", "Observation", "1200") == "1200 mm"
assert display_observation_value("String Length", "Observation", "1200 mm") == "1200 mm"
assert display_observation_value("Anodizing thickness", "Observation", "16") == "16 µm"
assert b'data-unit="\xc2\xb5m"' in entry.data
assert IPQC_DEF["document_no"] == "Master list : QMS/QAD/FM/L3/004"
assert IPQC_DEF["issue_date"] == "01-02-2026"
assert IPQC_DEF["revision_no"] == "00" and IPQC_DEF["revision_date"] == "00/00/0000"
assert next(section for section in IPQC_DEF["sections"] if section["name"] == "Laminator")["items"][0]["frequency"] == "Twice Per Shift"
assert any(section["name"] == "Post lam EL and Visual" for section in IPQC_DEF["sections"])
assert any(section["name"] == "Final EL and Visual" for section in IPQC_DEF["sections"])
assert not any(section["name"] in {"Post EL and Visual", "Post EL/Visual"} for section in IPQC_DEF["sections"])
all_items = {item["id"]: item for section in IPQC_DEF["sections"] for item in section["items"]}
assert "Ref: QMS/QAD/QP/L3/001" in all_items["R32"]["acceptance"]
assert "Ref: QMS/QAD/QP/L3/002" in all_items["R126"]["acceptance"]
assert "Ref:" not in all_items["R113"]["acceptance"]
assert "Ref:" not in all_items["R116"]["acceptance"]
assert "Ref:" not in all_items["R119"]["acceptance"]
assert "Ref: QMS/QAD/QP/L3/004" in all_items["R120"]["acceptance"]
assert "Ref: QMS/QAD/QP/L3/004" in all_items["R151"]["acceptance"]
assert "Ref: QMS/QAD/QP/FM/L3/006" in all_items["R156B"]["acceptance"]
assert "Ref: QMS/QAD/QP/FM/L3/006" in all_items["R167B"]["acceptance"]
assert "Ref: QMS/QAD/QP/FM/L3/006" in all_items["R173B"]["acceptance"]
assert "Ref: QMS/QAD/QP/L3/005" in all_items["R183"]["acceptance"]
assert all(f"{number}. Module No." in all_items["R183"]["observations"][0]["fields"] for number in range(1, 6))

# The HV / IR / Ground Continuity checkpoint is presented as two five-row,
# four-column matrices while retaining the original compatible field names.
hv_edit = client.get("/new/ipqc")
assert hv_edit.status_code == 200
assert b"hv-matrix-card" in hv_edit.data
assert hv_edit.data.count(b"<th>Module No.</th><th>IR</th><th>HV</th><th>GND</th>") == 2
app_script = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
assert "const host = scroll?.parentElement" in app_script
assert "host.insertBefore(tools, scroll)" in app_script
assert "Ref: QMS/QAD/QP/L3/004" in all_items["R195"]["acceptance"]
assert all_items["R167B"]["frequency"] == "Once Per Shift" and len(all_items["R167B"]["observations"]) == 1
assert all_items["R173B"]["frequency"] == "Once Per Shift" and len(all_items["R173B"]["observations"]) == 1
assert all_items["R156C"]["parameter"] == "Frame Sealant Ratio" and all_items["R156C"]["frequency"] == "Once Per Shift"
assert all_items["R173C"]["parameter"] == "Potting Weight"
assert all_items["R173C"]["observations"][0]["fields"] == ["Positive", "Negative", "Middle"]
for item_id in ["R13", "R18", "R85", "R87", "R94", "R103", "R103L", "R108", "R111", "R166"]:
    assert all("L x W x T" in observation["fields"] for observation in all_items[item_id]["observations"])
    assert all(not {"L", "W", "T"}.intersection(observation["fields"]) for observation in all_items[item_id]["observations"])
assert [section["name"] for section in IPQC_DEF["sections"]][3:11] == [
    "Cell Loading", "Stringer/Cell cutting section", "Auto Bussing", "String Rework",
    "Auto Barcode Placing", "Auto Tapping", "Auto Middle Patch Cutting", "Auto Long-Length Patch Cutting",
]
assert any(section["name"] == "JB Dispensing" for section in IPQC_DEF["sections"])
stage_names = [section["name"] for section in IPQC_DEF["sections"]]
assert stage_names[25:28] == ["Edge Milling", "Cleaning Stage", "Sun Simulator"]
assert "Cleaning" not in stage_names and "Auto Shorter" not in stage_names
assert stage_names[32:36] == ["Auto Sorter", "Auto Backlabel", "Auto Corner", "Packaging"]
assert all_items["R182A"]["acceptance"] == "Should be smooth and visually OK"
assert all_items["R182B"]["acceptance"] == "Should be free from dust, no marks on glass, no residue on glass"
assert all_items["R204A"]["observations"][0]["fields"] == ["Visual OK", "Position OK"]
assert all_items["R204B"]["acceptance"] == "As per module design"
parser = ObservationFieldParser()
parser.feed(entry.get_data(as_text=True))
expected_fields = {
    (item["id"], str(index), field)
    for section in IPQC_DEF["sections"]
    for item in section["items"]
    for index, observation in enumerate(item["observations"])
    for field in observation["fields"]
}
assert set(parser.fields) == expected_fields
assert len(parser.fields) == len(expected_fields)

custom_material = client.post("/new/ipqc", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps([{
        "id": "R12",
        "observations": {"0": {"values": {
            "Supplier name": "New Trial Glass Supplier",
            "Lot Number": "",
            "EXP date": "",
        }}},
        "result": "Not evaluated",
        "remarks": "",
    }]),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "",
    "inspection_time": "2026-09-12T08:00",
    "approver": "",
    "remarks": "",
    "action": "draft",
})
assert custom_material.status_code == 302
custom_material_id = int(custom_material.headers["Location"].rstrip("/").split("/")[-1])
with app.app_context():
    custom_record = db().execute(
        "SELECT payload,version FROM reports WHERE id=?", (custom_material_id,)
    ).fetchone()
    custom_payload = json.loads(custom_record["payload"])
custom_r12 = next(item for section in custom_payload["sections"] for item in section["items"] if item["id"] == "R12")
assert custom_r12["observations"][0]["values"]["Supplier name"] == "New Trial Glass Supplier"
custom_edit = client.get(f"/edit/{custom_material_id}")
assert b"New Trial Glass Supplier" in custom_edit.data and b'value="__other__" selected' in custom_edit.data
assert client.post(f"/report/{custom_material_id}/delete", data={
    "csrf": csrf(client), "version": custom_record["version"],
}).status_code == 302

ipqc_draft = client.post("/new/ipqc", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": "[]",
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "IPQC shop floor",
    "inspection_time": "2026-09-12T08:00",
    "approver": "",
    "remarks": "",
    "action": "draft",
})
assert ipqc_draft.status_code == 302
ipqc_detail = client.get(ipqc_draft.headers["Location"])
assert ipqc_detail.status_code == 200
assert b"IPQC audit stages" in ipqc_detail.data and b"stage-not-started" in ipqc_detail.data
assert b"Delete draft" in ipqc_detail.data and b"Draft preview" in ipqc_detail.data
draft_url = ipqc_draft.headers["Location"]
draft_id = int(draft_url.rstrip("/").split("/")[-1])
draft_listing = client.get("/")
assert b"Delete draft" in draft_listing.data
with app.app_context():
    draft_version = db().execute("SELECT version FROM reports WHERE id=?", (draft_id,)).fetchone()["version"]

# An incharge and another operator cannot delete an operator's draft.
client.post("/logout", data={"csrf": csrf(client)})
login(client, "IC001", "Qms55")
assert client.post(f"/report/{draft_id}/delete", data={"csrf": csrf(client), "version": draft_version}).status_code == 403
client.post("/logout", data={"csrf": csrf(client)})
login(client, "OP002", "Qms55")
assert client.post(f"/report/{draft_id}/delete", data={"csrf": csrf(client), "version": draft_version}).status_code == 404
client.post("/logout", data={"csrf": csrf(client)})
login(client, "OP001", "Qms55")
assert client.post(f"/report/{draft_id}/delete", data={"csrf": csrf(client), "version": draft_version + 1}).status_code == 409
removed = client.post(f"/report/{draft_id}/delete", data={"csrf": csrf(client), "version": draft_version})
assert removed.status_code == 302 and removed.headers["Location"].endswith("#records")
assert client.get(draft_url).status_code == 404
assert b"Delete draft" not in client.get("/").data
with app.app_context():
    retained = db().execute("SELECT status,version FROM reports WHERE id=?", (draft_id,)).fetchone()
    actions = [row["action"] for row in db().execute("SELECT action FROM history WHERE report=?", (draft_id,))]
    assert retained["status"] == "Deleted" and retained["version"] == draft_version + 1
    assert "Draft deleted" in actions

with app.app_context():
    incharge_id = db().execute("SELECT id FROM users WHERE employee='IC001'").fetchone()["id"]

gel_values = ctq_default_values("gel")
for key, field in ctq_field_map("gel").items():
    if key in CTQ_MATERIAL_OPTIONS.get("gel", {}):
        gel_values[key] = CTQ_MATERIAL_OPTIONS["gel"][key][0]
    elif field.get("type") == "select":
        gel_values[key] = field["options"][0]
    elif field.get("type") == "date":
        gel_values[key] = "2026-09-12"
    elif field.get("type") == "datetime-local":
        gel_values[key] = "2026-09-12T08:00"
    elif field.get("type") == "number":
        gel_values[key] = "10"
    elif field.get("required"):
        gel_values[key] = "Test value"
for sample in range(1, 6):
    gel_values[f"sample_{sample}_w1"] = "1"
    gel_values[f"sample_{sample}_w2"] = "1"
    gel_values[f"sample_{sample}_w3"] = "1.8"
gel_submitted_rows = {"format": "ctq-v1", "values": gel_values}
gel_submitted = client.post("/new/gel", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps(gel_submitted_rows),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "CTQ laboratory",
    "inspection_time": "2026-09-12T08:15",
    "approver": str(incharge_id),
    "remarks": "CTQ workflow test",
    "action": "submit",
})
assert gel_submitted.status_code == 302 and "/report/" in gel_submitted.headers["Location"]
gel_report_url = gel_submitted.headers["Location"]
gel_report_id = int(gel_report_url.rstrip("/").split("/")[-1])
assert b"Gel Test" in client.get(gel_report_url).data
gel_pdf = client.get(f"/report/{gel_report_id}.pdf")
assert gel_pdf.status_code == 200 and gel_pdf.data.startswith(b"%PDF")

# Keep a second pending record to prove an Administrator can return it for
# operator correction even though it is assigned to a shift incharge.
gel_return_submitted = client.post("/new/gel", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps(gel_submitted_rows),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "CTQ laboratory",
    "inspection_time": "2026-09-12T08:16",
    "approver": str(incharge_id),
    "remarks": "Administrator return workflow test",
    "action": "submit",
})
assert gel_return_submitted.status_code == 302
gel_return_url = gel_return_submitted.headers["Location"]
gel_return_id = int(gel_return_url.rstrip("/").split("/")[-1])

# The controlled Ribbon Peel sheet contains six Stringer tracks, two sides,
# 16 serial positions, seven editable peaks at every position, automatic
# average/N/mm calculations, and a per-peak acceptance rule of >= 0.8 N.
ribbon_values = {
    "cell_make": CTQ_MATERIAL_OPTIONS["ribbon_peel"]["cell_make"][0],
    "ribbon_make": CTQ_MATERIAL_OPTIONS["ribbon_peel"]["ribbon_make"][0],
}
for key, field in ctq_field_map("ribbon_peel").items():
    if field.get("type") == "number":
        ribbon_values[key] = "1.2"
ribbon_payload, ribbon_result = prepare_ctq_payload(
    "ribbon_peel", {"format": "ctq-v1", "values": ribbon_values}, "submit"
)
assert ribbon_result == "PASS"
assert ribbon_payload["calculated"]["rp_1a_front_s6_average"] == "1.2"
assert ribbon_payload["calculated"]["rp_1a_front_s6_n_per_mm"] == "5"
assert ribbon_payload["calculated"]["rp_2b_front_s6_n_per_mm"] == "5"
assert all(track["ribbon_width_mm"] == 0.24 for section in CTQ_DEF["ribbon_peel"]["sections"]
           if section["type"] == "ribbon_peel_matrix" for track in section["tracks"])

busbar_values = {
    "cell_ribbon": "Test cell ribbon",
    "busbar": "Test busbar",
    "autobussing_number": "AB-01",
    "ribbon_spec": "0.24 mm",
    **{f"long_r{reading}": "2.4" for reading in range(1, 17)},
}
busbar_payload, busbar_result = prepare_ctq_payload(
    "busbar_peel", {"format": "ctq-v1", "values": busbar_values}, "submit"
)
assert busbar_result == "PASS"
assert busbar_payload["calculated"]["long_average"] == "2.4"
assert busbar_payload["calculated"]["long_n_per_mm"] == "10"
assert "long_n_per_mm" not in busbar_payload["values"]
legacy_busbar = {
    **busbar_payload,
    "values": {**busbar_payload["values"], "long_n_per_mm": "999"},
    "calculated": {"long_average": "2.4"},
}
assert refreshed_ctq_payload("busbar_peel", legacy_busbar)["calculated"]["long_n_per_mm"] == "10"
ribbon_fail_values = dict(ribbon_values)
ribbon_fail_values["rp_2a_front_s1_p1"] = "0.5"
_, ribbon_fail_result = prepare_ctq_payload(
    "ribbon_peel", {"format": "ctq-v1", "values": ribbon_fail_values}, "submit"
)
assert ribbon_fail_result == "FAIL"
ribbon_missing_values = dict(ribbon_values)
del ribbon_missing_values["rp_3b_back_s16_p7"]
try:
    prepare_ctq_payload("ribbon_peel", {"format": "ctq-v1", "values": ribbon_missing_values}, "submit")
except ValueError as error:
    assert "Stringer 3B Back, Serial 16" in str(error)
else:
    raise AssertionError("An incomplete controlled Ribbon Peel row was accepted.")

ribbon_submitted = client.post("/new/ribbon_peel", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps({"format": "ctq-v1", "values": ribbon_values}),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "CTQ laboratory",
    "inspection_time": "2026-09-12T08:20",
    "approver": str(incharge_id),
    "remarks": "Controlled Ribbon Peel workflow test",
    "action": "submit",
})
assert ribbon_submitted.status_code == 302 and "/report/" in ribbon_submitted.headers["Location"]
ribbon_report_url = ribbon_submitted.headers["Location"]
ribbon_report_id = int(ribbon_report_url.rstrip("/").split("/")[-1])
ribbon_detail = client.get(ribbon_report_url)
assert b"Stringer 1A" in ribbon_detail.data and b"Front + Back" in ribbon_detail.data
assert b"N/mm divisor 0.24 mm" in ribbon_detail.data and b"0.26 mm" not in ribbon_detail.data
ribbon_pdf = client.get(f"/report/{ribbon_report_id}.pdf")
assert ribbon_pdf.status_code == 200 and ribbon_pdf.data.startswith(b"%PDF") and len(ribbon_pdf.data) > 30000

busbar_submitted = client.post("/new/busbar_peel", data={
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps({"format": "ctq-v1", "values": busbar_values}),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "CTQ laboratory",
    "inspection_time": "2026-09-12T08:25",
    "approver": str(incharge_id),
    "remarks": "Busbar automatic N/mm workflow test",
    "action": "submit",
})
assert busbar_submitted.status_code == 302 and "/report/" in busbar_submitted.headers["Location"]
busbar_report_url = busbar_submitted.headers["Location"]
busbar_report_id = int(busbar_report_url.rstrip("/").split("/")[-1])
busbar_detail = client.get(busbar_report_url)
assert b"Avg \xc3\xb7 0.24" in busbar_detail.data and b">10</td>" in busbar_detail.data
busbar_pdf = client.get(f"/report/{busbar_report_id}.pdf")
assert busbar_pdf.status_code == 200 and busbar_pdf.data.startswith(b"%PDF")

rows = []
for section in IPQC_DEF["sections"]:
    for item in section["items"]:
        observations = {}
        for index, observation in enumerate(item["observations"]):
            observations[str(index)] = {
                "label": observation["label"],
                "values": {
                    field: MATERIAL_FIELD_OPTIONS.get(item["id"], {}).get(field, ["OK"])[0]
                    for field in observation["fields"]
                },
            }
        rows.append({"id": item["id"], "observations": observations})
report_form = {
    "csrf": csrf(client),
    "version": "0",
    "rows": json.dumps(rows),
    "day": "2026-09-12",
    "shift": "A",
    "line": "Line 2",
    "machine": "IPQC shop floor",
    "inspection_time": "2026-09-12T08:30",
    "approver": str(incharge_id),
    "remarks": "",
    "action": "submit",
    "meta_production_order": "PO-TEST-001",
    "meta_customer_name": "Example Solar Customer",
    "meta_module_type": "G12R 630 Wp",
}
missing_customer = client.post("/new/ipqc", data={**report_form, "meta_customer_name": ""})
assert missing_customer.status_code == 200 and b"Complete Customer name" in missing_customer.data
created = client.post("/new/ipqc", data=report_form)
assert created.status_code == 302 and "/report/" in created.headers["Location"]
report_url = created.headers["Location"]
report_id = int(report_url.rstrip("/").split("/")[-1])
created_detail = client.get(report_url)
assert b"Delete draft" not in created_detail.data
assert client.post(f"/report/{report_id}/delete", data={"csrf": csrf(client), "version": "1"}).status_code == 403
assert b"Overall result" not in created_detail.data
assert b"stringer-matrix" in created_detail.data and b"Set power" in created_detail.data
assert b"Standby power" in created_detail.data
assert b"Four-laminator matrix" in created_detail.data and b"Laminator 2B" in created_detail.data
assert created_detail.data.count(b'class="laminator-chamber-title"') == 3
assert b" mm" in created_detail.data
assert created_detail.data.count(b"100%") == len(IPQC_DEF["sections"])
with app.app_context():
    saved_report = db().execute("SELECT result,payload FROM reports WHERE id=?", (report_id,)).fetchone()
    assert saved_report["result"] == "Completed"
    saved_payload = json.loads(saved_report["payload"])
    assert saved_payload["metadata"]["customer_name"] == "Example Solar Customer"
    saved_items = [item for section in saved_payload["sections"] for item in section["items"]]
    assert len(saved_items) == sum(len(section["items"]) for section in IPQC_DEF["sections"])
    assert all(item["result"] == "Completed" for item in saved_items)

# Keep a second pending IPQC checksheet to prove it reaches the administrator
# approval list even though its primary assignee is a shift incharge.
admin_ipqc_created = client.post("/new/ipqc", data={
    **report_form,
    "inspection_time": "2026-09-12T08:31",
    "meta_production_order": "PO-ADMIN-APPROVAL",
})
assert admin_ipqc_created.status_code == 302 and "/report/" in admin_ipqc_created.headers["Location"]
admin_ipqc_url = admin_ipqc_created.headers["Location"]
admin_ipqc_id = int(admin_ipqc_url.rstrip("/").split("/")[-1])
admin_ipqc_record_key = f"QMS-{admin_ipqc_id:06d}".encode()

# Dashboard module tabs must never merge IPQC and CTQ summaries or record lists.
ipqc_dashboard = client.get("/?module=ipqc")
ctq_dashboard = client.get("/?module=ctq")
ipqc_record_key = f"QMS-{report_id:06d}".encode()
gel_record_key = f"QMS-{gel_report_id:06d}".encode()
assert b"My IPQC summary" in ipqc_dashboard.data and b"IPQC AUDIT LIST" in ipqc_dashboard.data
assert ipqc_record_key in ipqc_dashboard.data and gel_record_key not in ipqc_dashboard.data
assert b"My CTQ summary" in ctq_dashboard.data and b"CTQ AUDIT LIST" in ctq_dashboard.data
assert gel_record_key in ctq_dashboard.data and ipqc_record_key not in ctq_dashboard.data
assert b'name="module" value="ctq"' in ctq_dashboard.data and b"All CTQ tests" in ctq_dashboard.data

pdf = client.get(f"/report/{report_id}.pdf")
assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
assert "QMS-" not in pdf.headers["Content-Disposition"]
assert "IPQC-checksheet-2026-09-12-Shift-A.pdf" in pdf.headers["Content-Disposition"]

client.post("/logout", data={"csrf": csrf(client)})
login(client, "IC002", "Qms55")
assert client.get(report_url).status_code == 404
assert client.post(
    f"/report/{report_id}/review",
    data={"csrf": csrf(client), "version": "1", "action": "Approved", "comment": ""},
).status_code == 404

client.post("/logout", data={"csrf": csrf(client)})
login(client, "IC001", "Qms55")
gel_review_page = client.get(gel_report_url)
assert b"Incharge verification" in gel_review_page.data and b'value="Rejected"' in gel_review_page.data

review_page = client.get(report_url)
assert b"Incharge verification" in review_page.data and b"signature-panel" in review_page.data
with app.app_context():
    version = db().execute("SELECT version FROM reports WHERE id=?", (report_id,)).fetchone()["version"]
approved = client.post(
    f"/report/{report_id}/review",
    data={"csrf": csrf(client), "version": version, "action": "Approved", "comment": ""},
)
assert approved.status_code == 302
with app.app_context():
    status = db().execute("SELECT status FROM reports WHERE id=?", (report_id,)).fetchone()["status"]
assert status == "Approved"
assert b"Delete draft" not in client.get(report_url).data

incharge_ipqc_dashboard = client.get("/?module=ipqc")
incharge_ctq_dashboard = client.get("/?module=ctq")
assert b"Quality IPQC summary" in incharge_ipqc_dashboard.data
assert ipqc_record_key in incharge_ipqc_dashboard.data and gel_record_key not in incharge_ipqc_dashboard.data
assert b"Quality CTQ summary" in incharge_ctq_dashboard.data
assert gel_record_key in incharge_ctq_dashboard.data and ipqc_record_key not in incharge_ctq_dashboard.data

approved_pdf = client.get(f"/report/{report_id}.pdf")
assert approved_pdf.status_code == 200 and approved_pdf.data.startswith(b"%PDF")
if os.environ.get("QMS_TEST_PDF"):
    sample_path = Path(os.environ["QMS_TEST_PDF"])
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_bytes(approved_pdf.data)

client.post("/logout", data={"csrf": csrf(client)})
login(client, "AD001", "Qms55")
assert client.get("/users").status_code == 403
admin_ipqc_dashboard = client.get("/?module=ipqc")
assert admin_ipqc_record_key in admin_ipqc_dashboard.data
assert b"Admin review" in admin_ipqc_dashboard.data
admin_ipqc_review_page = client.get(admin_ipqc_url)
assert b"Administrator verification" in admin_ipqc_review_page.data
assert b"assigned incharge remains Incharge One" in admin_ipqc_review_page.data
assert b'value="Approved with remarks"' in admin_ipqc_review_page.data
assert b"Return for correction" in admin_ipqc_review_page.data and b'value="Rejected"' in admin_ipqc_review_page.data
with app.app_context():
    admin_ipqc_version = db().execute(
        "SELECT version FROM reports WHERE id=?", (admin_ipqc_id,)
    ).fetchone()["version"]
admin_ipqc_approved = client.post(
    f"/report/{admin_ipqc_id}/review",
    data={"csrf": csrf(client), "version": admin_ipqc_version,
          "action": "Approved", "comment": ""},
)
assert admin_ipqc_approved.status_code == 302
with app.app_context():
    admin_ipqc_status = db().execute(
        "SELECT status FROM reports WHERE id=?", (admin_ipqc_id,)
    ).fetchone()["status"]
    admin_ipqc_history = db().execute(
        "SELECT h.action,u.name,u.role FROM history h JOIN users u ON h.actor=u.id "
        "WHERE h.report=? ORDER BY h.id DESC LIMIT 1", (admin_ipqc_id,),
    ).fetchone()
assert admin_ipqc_status == "Approved"
assert admin_ipqc_history["action"] == "Approved"
assert admin_ipqc_history["name"] == "Admin One" and admin_ipqc_history["role"] == "admin"

admin_gel_review_page = client.get(gel_report_url)
assert b"Administrator verification" in admin_gel_review_page.data
assert b"assigned incharge remains Incharge One" in admin_gel_review_page.data
assert b'value="Rejected"' in admin_gel_review_page.data and b"Return for correction" in admin_gel_review_page.data
with app.app_context():
    gel_review_version = db().execute("SELECT version FROM reports WHERE id=?", (gel_report_id,)).fetchone()["version"]
gel_approved = client.post(
    f"/report/{gel_report_id}/review",
    data={"csrf": csrf(client), "version": gel_review_version, "action": "Approved", "comment": ""},
)
assert gel_approved.status_code == 302
with app.app_context():
    gel_status = db().execute("SELECT status FROM reports WHERE id=?", (gel_report_id,)).fetchone()["status"]
    gel_history = db().execute(
        "SELECT h.action,u.name,u.role FROM history h JOIN users u ON h.actor=u.id "
        "WHERE h.report=? ORDER BY h.id DESC LIMIT 1", (gel_report_id,),
    ).fetchone()
assert gel_status == "Approved"
assert gel_history["action"] == "Approved" and gel_history["name"] == "Admin One" and gel_history["role"] == "admin"
approved_gel_detail = client.get(gel_report_url)
assert b"Admin One" in approved_gel_detail.data and b"Administrator" in approved_gel_detail.data
gel_pdf = client.get(f"/report/{gel_report_id}.pdf")
assert gel_pdf.status_code == 200 and gel_pdf.data.startswith(b"%PDF")

# Admin return is editable and resubmittable by the operator.
with app.app_context():
    gel_return_version = db().execute("SELECT version FROM reports WHERE id=?", (gel_return_id,)).fetchone()["version"]
gel_returned = client.post(
    f"/report/{gel_return_id}/review",
    data={"csrf": csrf(client), "version": gel_return_version,
          "action": "Returned for correction", "comment": "Correct the recorded batch reference."},
)
assert gel_returned.status_code == 302
with app.app_context():
    returned_status = db().execute("SELECT status FROM reports WHERE id=?", (gel_return_id,)).fetchone()["status"]
assert returned_status == "Returned for correction"
returned_detail = client.get(gel_return_url)
assert b"Admin One" in returned_detail.data and b"Returned for correction" in returned_detail.data

# Admin rejection is a separate final, locked outcome.
with app.app_context():
    ribbon_review_version = db().execute("SELECT version FROM reports WHERE id=?", (ribbon_report_id,)).fetchone()["version"]
ribbon_rejected = client.post(
    f"/report/{ribbon_report_id}/review",
    data={"csrf": csrf(client), "version": ribbon_review_version,
          "action": "Rejected", "comment": "Controlled readings require a new report."},
)
assert ribbon_rejected.status_code == 302
with app.app_context():
    rejected_status = db().execute("SELECT status FROM reports WHERE id=?", (ribbon_report_id,)).fetchone()["status"]
    rejected_history = db().execute(
        "SELECT h.action,u.name,u.role FROM history h JOIN users u ON h.actor=u.id "
        "WHERE h.report=? ORDER BY h.id DESC LIMIT 1", (ribbon_report_id,),
    ).fetchone()
assert rejected_status == "Rejected"
assert rejected_history["action"] == "Rejected" and rejected_history["name"] == "Admin One"
rejected_detail = client.get(ribbon_report_url)
assert b"status-rejected" in rejected_detail.data and b"Admin One" in rejected_detail.data
rejected_pdf = client.get(f"/report/{ribbon_report_id}.pdf")
assert rejected_pdf.status_code == 200 and rejected_pdf.data.startswith(b"%PDF")

admin_ctq_dashboard = client.get("/?module=ctq")
assert b"Rejected</span><strong>1</strong>" in admin_ctq_dashboard.data

daily = client.get("/daily.pdf?day=2026-09-12")
assert daily.status_code == 200 and daily.mimetype == "application/pdf" and daily.data.startswith(b"%PDF")

# Employee 0001 is the only user-management custodian and has no report access.
client.post("/logout", data={"csrf": csrf(client)})
login(client, "0001", "Qms55")
users_page = client.get("/users")
assert users_page.status_code == 200 and b"SUPER USER CONTROL" in users_page.data
assert b"Deactivate" in users_page.data and b"Delete user" in users_page.data
assert admin_ipqc_record_key not in client.get("/?module=ipqc").data
assert client.get(admin_ipqc_url).status_code == 404
assert client.get("/daily.pdf?day=2026-09-12").status_code == 403
with app.app_context():
    operator_two_id = db().execute("SELECT id FROM users WHERE employee='OP002'").fetchone()["id"]
deactivated_user = client.post(f"/users/{operator_two_id}/deactivate", data={"csrf": csrf(client)})
assert deactivated_user.status_code == 302
assert b"Activate" in client.get("/users").data
with app.app_context():
    assert db().execute("SELECT active FROM users WHERE id=?", (operator_two_id,)).fetchone()["active"] == 0
activated_user = client.post(f"/users/{operator_two_id}/activate", data={"csrf": csrf(client)})
assert activated_user.status_code == 302
deleted_user = client.post(f"/users/{operator_two_id}/delete", data={"csrf": csrf(client)})
assert deleted_user.status_code == 302
with app.app_context():
    assert db().execute("SELECT active FROM users WHERE id=?", (operator_two_id,)).fetchone()["active"] == -1
    assert db().execute("SELECT id FROM users WHERE id=?", (operator_two_id,)).fetchone() is not None
disabled_client = app.test_client()
disabled_client.get("/login")
disabled_login = disabled_client.post("/login", data={
    "employee": "OP002", "password": "Qms55", "csrf": csrf(disabled_client),
})
assert disabled_login.status_code == 200

client.post("/logout", data={"csrf": csrf(client)})
login(client, "OP001", "Qms55")
assert client.get(f"/edit/{gel_return_id}").status_code == 200
assert client.get(f"/edit/{ribbon_report_id}").status_code == 403

print("QMS smoke test passed: Laminator fields, admin IPQC/CTQ approvals, progress, peel calculations, PDFs, and dashboard.")
