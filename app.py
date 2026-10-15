import os
import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Pre-loaded realistic solar manufacturing inspection logs for pitch demo
inspection_logs = [
    {"serial": "SLR-9985-NX", "batch": "BTC-2026-OCT-1", "cell_type": "TopCon 580W Bifacial", "defect": "None (EL Clear)", "status": "PASSED", "inspector": "R. Sharma", "time": "10:52 AM"},
    {"serial": "SLR-9984-NX", "batch": "BTC-2026-OCT-1", "cell_type": "TopCon 580W Bifacial", "defect": "Micro-crack (Zone B2)", "status": "REWORK", "inspector": "R. Sharma", "time": "10:49 AM"},
    {"serial": "SLR-9983-NX", "batch": "BTC-2026-OCT-1", "cell_type": "Mono PERC 540W", "defect": "None (EL Clear)", "status": "PASSED", "inspector": "A. Patel", "time": "10:45 AM"},
    {"serial": "SLR-9982-NX", "batch": "BTC-2026-OCT-1", "cell_type": "Mono PERC 540W", "defect": "Busbar Misalignment", "status": "REWORK", "inspector": "A. Patel", "time": "10:41 AM"},
    {"serial": "SLR-9981-NX", "batch": "BTC-2026-OCT-1", "cell_type": "HJT 600W Pro", "defect": "None (EL Clear)", "status": "PASSED", "inspector": "V. Kumar", "time": "10:38 AM"},
    {"serial": "SLR-9980-NX", "batch": "BTC-2026-OCT-1", "cell_type": "TopCon 580W Bifacial", "defect": "EVA Delamination / Bubble", "status": "REJECTED", "inspector": "R. Sharma", "time": "10:34 AM"},
    {"serial": "SLR-9979-NX", "batch": "BTC-2026-OCT-1", "cell_type": "Mono PERC 540W", "defect": "None (EL Clear)", "status": "PASSED", "inspector": "A. Patel", "time": "10:30 AM"}
]

@app.route('/')
def dashboard():
    return render_template('index.html', logs=inspection_logs)

@app.route('/api/inspect', methods=['POST'])
def add_inspection():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid data"}), 400
    
    new_entry = {
        "serial": data.get("serial", "SLR-9990-NX").strip().upper(),
        "batch": data.get("batch", "BTC-2026-OCT-1").strip().upper(),
        "cell_type": data.get("cell_type", "TopCon 580W Bifacial"),
        "defect": data.get("defect", "None (EL Clear)"),
        "status": data.get("status", "PASSED"),
        "inspector": data.get("inspector", "Plant QA"),
        "time": datetime.datetime.now().strftime("%I:%M %p")
    }
    inspection_logs.insert(0, new_entry)
    return jsonify({"success": True, "entry": new_entry})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
