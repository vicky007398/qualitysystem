import importlib.util
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory()
os.environ["QUALITYSYSTEM_DATA"] = TEMP.name
os.environ["QUALITYSYSTEM_SECRET"] = "smoke-test-secret"
spec = importlib.util.spec_from_file_location("qualitysystem_app", ROOT / "app.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = module.app
db = module.db
app.config.update(TESTING=True)
client = app.test_client()


def token():
    with client.session_transaction() as session:
        return session["csrf"]


def login(employee):
    client.get("/login")
    response = client.post("/login", data={"csrf": token(), "employee": employee, "password": "Demo123"})
    assert response.status_code == 302


login_page = client.get("/login")
assert login_page.status_code == 200
assert b"Your Company" in login_page.data and b"OP100" in login_page.data
assert b"Navitas" not in login_page.data

login("OP100")
home = client.get("/")
assert home.status_code == 200
for title in [b"IPQC Checksheet", b"Stringer Parameter Report", b"Gel Content Test", b"Adhesion Test", b"Ribbon Peel Test", b"Busbar Peel Test"]:
    assert title in home.data

form = client.get("/new/stringer")
assert form.status_code == 200 and form.data.count(b"Stringer 1A") == 1 and b"Solder base plate temperature" in form.data

data = {
    "csrf": token(), "action": "submit", "day": "2026-10-08", "shift": "A", "line": "Demo Line",
    "reference": "ORDER-100", "customer": "Sample Customer", "approver": "2",
    "stringer_1a": "100", "stringer_1b": "101", "stringer_2a": "99", "stringer_2b": "100", "stringer_3a": "102", "stringer_3b": "98",
}
created = client.post("/new/stringer", data=data)
assert created.status_code == 302 and "/report/" in created.headers["Location"]
report_id = int(created.headers["Location"].rstrip("/").split("/")[-1])

detail = client.get(created.headers["Location"])
assert b"Pending Approval" in detail.data and b"PASS" in detail.data
pdf = client.get(f"/report/{report_id}.pdf")
assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and len(pdf.data) > 2000

client.post("/logout", data={"csrf": token()})
login("IC100")
review = client.get(f"/report/{report_id}")
assert b"Verify this report" in review.data
approved = client.post(f"/report/{report_id}/review", data={"csrf": token(), "action": "approve", "comment": "Verified for demonstration."})
assert approved.status_code == 302
with app.app_context():
    row = db().execute("SELECT status,remarks,payload FROM reports WHERE id=?", (report_id,)).fetchone()
    assert row["status"] == "Approved with Remarks"
    assert json.loads(row["payload"])["values"]["stringer_1a"] == "100"

client.post("/logout", data={"csrf": token()})
login("AD100")
users = client.get("/users")
assert users.status_code == 200 and b"Demo Operator" in users.data and b"Create user" in users.data
print("Quality System demo smoke test passed: reports, workflow, approval, PDF and users.")

TEMP.cleanup()
