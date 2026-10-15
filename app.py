"""Company QMS pilot. All application assets and records remain on this host."""
import io
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

# PyInstaller places bundled templates, static files, definitions and PDF assets in
# ``sys._MEIPASS`` while a one-file executable is running.  Development installs
# continue to use the project directory.  The writable database is deliberately
# outside the executable so an application update never replaces company records.
SOURCE_ROOT = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(getattr(sys, '_MEIPASS', SOURCE_ROOT)).resolve()
if FROZEN:
    PORTABLE_ROOT = Path(os.environ.get(
        'QMS_PORTABLE_ROOT', Path(sys.executable).resolve().parent.parent
    )).resolve()
    DEFAULT_DATA = PORTABLE_ROOT / '.qms_data'
else:
    PORTABLE_ROOT = SOURCE_ROOT
    DEFAULT_DATA = SOURCE_ROOT / 'data'
DATA = Path(os.environ.get('QUALITYSYSTEM_DATA', DEFAULT_DATA)).resolve()
DATA.mkdir(parents=True, exist_ok=True)
key_file = DATA / 'demo-session.key'
if not key_file.exists():
    try:
        with key_file.open('x') as f:
            f.write(secrets.token_hex(32))
        key_file.chmod(0o600)
    except FileExistsError:
        pass
app = Flask(
    __name__,
    template_folder=str(ROOT / 'templates'),
    static_folder=str(ROOT / 'static'),
)
app.config.update(SECRET_KEY=key_file.read_text().strip(), MAX_CONTENT_LENGTH=26 * 1024 * 1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.environ.get('QUALITYSYSTEM_HTTPS') == '1',
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
IST = timezone(timedelta(hours=5, minutes=30))
CTQ_DEF = json.loads((ROOT / 'definitions' / 'ctq_revision_1.json').read_text(encoding='utf-8'))
FORMS = {
    'ipqc': ('IPQC checksheet', ['Process / inspection item', 'Specification / reference', 'Observation / actual value', 'Unit']),
    'gel': (CTQ_DEF['gel']['name'], []),
    'ribbon_peel': (CTQ_DEF['ribbon_peel']['name'], []),
    'adhesion': (CTQ_DEF['adhesion']['name'], []),
    'busbar_peel': (CTQ_DEF['busbar_peel']['name'], []),
    # These two kinds are retained only so previously saved reports remain readable.
    'stringer': ('Stringer Parameter Report', ['Parameter','Reading']),
    'peel': ('Peel Test', ['Sample ID', 'Test position', 'Peel strength (N)', 'Acceptance criteria', 'Remarks']),
    'datapaq': ('DataPAQ Test', ['Profile ID', 'Sensor / channel', 'Minimum temperature (°C)', 'Maximum temperature (°C)', 'Duration (s)', 'Remarks']),
}
CTQ_KINDS = tuple(CTQ_DEF)
ACTIVE_KINDS = ('ipqc', *CTQ_KINDS)
MODULE_KINDS = {'ipqc': ('ipqc','stringer'), 'ctq': CTQ_KINDS}
FORM_DESCRIPTIONS = {
    'ipqc': 'Record the controlled in-process inspection checksheet.',
    **{key: definition['description'] for key, definition in CTQ_DEF.items()},
    'stringer': 'A preserved report from the earlier customer demo.',
    'peel': 'Record peel-strength readings by sample and test position.',
    'datapaq': 'Record thermal-profile channels, temperatures, and duration.',
}
RESULTS = ['Not evaluated', 'Completed', 'PASS', 'FAIL']
APPROVED = ['Approved', 'Approved with remarks']
REVIEW_OUTCOMES = [*APPROVED, 'Returned for correction', 'Rejected']
PEEL_DIVISOR_MM = 0.24
IPQC_DEF = json.loads((ROOT / 'definitions' / 'ipqc_revision_2.json').read_text(encoding='utf-8'))
MATERIALS = json.loads((ROOT / 'definitions' / 'material_suppliers.json').read_text(encoding='utf-8'))['categories']
MATERIAL_FIELD_CATEGORIES = {
    'R12': {'Supplier name': 'front_glass'},
    'R15': {'Supplier name': 'encapsulant'},
    'R78': {'Flux Supplier name': 'flux'},
    'R79': {'Cell Ribbon Supplier name': 'cell_connector'},
    'R83': {'Cell Supplier name': 'solar_cell'},
    'R86': {'Bus Ribbon Supplier name': 'string_connector'},
    'R101': {'Supplier name': 'encapsulant'},
    'R101L': {'Supplier name': 'encapsulant'},
    'R105': {'Supplier name': 'encapsulant'},
    'R110': {'Supplier name': 'rear_glass'},
    'R154': {'Supplier name': 'frame'},
    'R156': {'Supplier name': 'adhesive'},
    'R168': {'Supplier name': 'jb'},
    'R173': {'Supplier name (A)': 'potting', 'Supplier name (B)': 'potting'},
}
MATERIAL_FIELD_OPTIONS = {
    item_id: {field: MATERIALS[category] for field, category in fields.items()}
    for item_id, fields in MATERIAL_FIELD_CATEGORIES.items()
}
CTQ_MATERIAL_OPTIONS = {
    'gel': {'eva_manufacturer': MATERIALS['encapsulant']},
    'ribbon_peel': {
        'cell_make': MATERIALS['solar_cell'],
        'ribbon_make': MATERIALS['cell_connector'],
    },
    'adhesion': {
        'front_glass_supplier': MATERIALS['front_glass'],
        'eva_poe_supplier': MATERIALS['encapsulant'],
        'rear_side_supplier': MATERIALS['rear_glass'],
    },
}

def observation_unit(parameter, field):
    """Return the display unit for dimensional observation values."""
    parameter_text = str(parameter or '').casefold()
    field_text = str(field or '').strip().casefold()
    if 'anodizing thickness' in parameter_text:
        return 'µm'
    direct_fields = {'l', 'w', 't', 'length', 'width', 'thickness', 'height'}
    dimension_terms = ('dimension', 'length', 'width', 'thickness', 'height', 'size', 'gap', 'edge to')
    if field_text in direct_fields or '(mm)' in parameter_text:
        return 'mm'
    if field_text == 'observation' and any(term in parameter_text for term in dimension_terms):
        return 'mm'
    if any(term in field_text for term in ('length', 'width', 'thickness', 'height')):
        return 'mm'
    return ''

def display_observation_value(parameter, field, value):
    value = str(value or '').strip()
    if not value:
        return '-'
    unit = observation_unit(parameter, field)
    return value if not unit or value.casefold().endswith(unit.casefold()) else f'{value} {unit}'

def ribbon_not_required(track, position, peak):
    """Return whether a controlled Ribbon Peel cell is marked NR in the source workbook."""
    rule = track.get('not_required', {})
    return position in rule.get('positions', []) and peak in rule.get('peaks', [])

def ribbon_peak_key(track, side, position, peak):
    return f"rp_{track}_{side}_s{position}_p{peak}"

def ribbon_calculation_key(track, side, position, suffix):
    return f"rp_{track}_{side}_s{position}_{suffix}"

def ctq_field_map(kind):
    """Return every stored CTQ value key with its controlled field definition."""
    definition = CTQ_DEF[kind]
    fields = {}
    for section in definition['sections']:
        section_type = section['type']
        if section_type == 'fields':
            for field in section['fields']:
                fields[field['key']] = field
        elif section_type == 'matrix':
            for row in section['rows']:
                allowed_columns = row.get('columns')
                for column in section['columns']:
                    if allowed_columns and column['key'] not in allowed_columns:
                        continue
                    fields[f"{column['key']}_{row['key']}"] = {
                        **row, 'label': f"{column['label']} — {row['label']}"
                    }
        elif section_type == 'gel_samples':
            for sample in range(1, section['count'] + 1):
                fields[f'sample_{sample}_w1'] = {'label': f'Sample {sample} — W1', 'type': 'number', 'required': True}
                fields[f'sample_{sample}_w2'] = {'label': f'Sample {sample} — W2', 'type': 'number', 'required': True}
                fields[f'sample_{sample}_w3'] = {'label': f'Sample {sample} — W3', 'type': 'number', 'required': True}
                fields[f'sample_{sample}_remarks'] = {'label': f'Sample {sample} — Remarks', 'type': 'text'}
        elif section_type == 'adhesion_readings':
            for group in section['groups']:
                for reading in range(1, section['count'] + 1):
                    fields[f"{group['key']}_{reading}"] = {
                        'label': f"{group['label']} — Reading {reading}", 'type': 'number', 'required': True
                    }
        elif section_type == 'busbar_matrix':
            for row in section['rows']:
                fields[f"{row['key']}_enabled"] = {'label': row['label'], 'type': 'checkbox'}
                for reading in range(1, section['count'] + 1):
                    fields[f"{row['key']}_r{reading}"] = {
                        'label': f"{row['label']} — Ribbon {reading}", 'type': 'number'
                    }
        elif section_type == 'ribbon_peel_matrix':
            for track in section['tracks']:
                for side in section['sides']:
                    for position in range(1, section['count'] + 1):
                        for peak in range(1, section['peaks'] + 1):
                            if ribbon_not_required(track, position, peak):
                                continue
                            fields[ribbon_peak_key(track['key'], side['key'], position, peak)] = {
                                'label': f"Stringer {track['label']} {side['label']} — Serial {position}, Peak {peak}",
                                'type': 'number',
                            }
    return fields

def ctq_default_values(kind):
    values = {}
    for key, field in ctq_field_map(kind).items():
        if 'default' in field:
            values[key] = str(field['default'])
    for section in CTQ_DEF[kind]['sections']:
        if section['type'] == 'busbar_matrix':
            for row in section['rows']:
                if row.get('default_enabled'):
                    values[f"{row['key']}_enabled"] = '1'
    return values

def clean_number(value, label, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'Enter a valid number for {label}.')
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f'Enter a valid positive number for {label}.' if positive else f'Enter a valid number for {label}.')
    return number

def display_number(value):
    return f'{value:.3f}'.rstrip('0').rstrip('.')

def prepare_ctq_payload(kind, submitted, action):
    """Whitelist, validate, and calculate the controlled CTQ form payload."""
    if kind not in CTQ_DEF or not isinstance(submitted, dict):
        raise ValueError('Invalid CTQ test data.')
    definition = CTQ_DEF[kind]
    source = submitted.get('values', submitted)
    if not isinstance(source, dict):
        raise ValueError('Invalid CTQ test data.')
    field_map = ctq_field_map(kind)
    values = ctq_default_values(kind)
    for key, field in field_map.items():
        if field.get('type') == 'checkbox':
            values[key] = '1' if str(source.get(key, '')).lower() in ('1', 'true', 'yes', 'on') else ''
        elif key in source:
            value = str(source.get(key, '')).strip()
            if len(value) > 500:
                raise ValueError(field['label'] + ' is too long (maximum 500 characters).')
            values[key] = value

    if action == 'submit' and not definition.get('submit_enabled', True):
        raise ValueError('The Ribbon Peel Test sheet is blank and cannot be submitted until its controlled fields are supplied.')

    for key, field in field_map.items():
        value = values.get(key, '')
        if action == 'submit' and field.get('required') and not value:
            raise ValueError('Complete ' + field['label'] + '.')
        if value and field.get('type') == 'number':
            clean_number(value, field['label'])
        if value and field.get('type') == 'date':
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except ValueError:
                raise ValueError('Enter a valid date for ' + field['label'] + '.')

    calculated = {}
    assessed_result = None
    if kind == 'gel':
        sample_results = []
        sample_count = next(section['count'] for section in definition['sections'] if section['type'] == 'gel_samples')
        for sample in range(1, sample_count + 1):
            keys = [f'sample_{sample}_w1', f'sample_{sample}_w2', f'sample_{sample}_w3']
            if not all(values.get(key) for key in keys):
                continue
            w1 = clean_number(values[keys[0]], f'Sample {sample} — W1', positive=True)
            w2 = clean_number(values[keys[1]], f'Sample {sample} — W2')
            w3 = clean_number(values[keys[2]], f'Sample {sample} — W3')
            dried = w3 - w2
            if dried < 0:
                raise ValueError(f'Sample {sample}: W3 must be greater than or equal to W2.')
            gel = dried / w1 * 100
            calculated[f'sample_{sample}_dried'] = display_number(dried)
            calculated[f'sample_{sample}_gel'] = display_number(gel)
            sample_results.append(gel)
        if sample_results:
            average = sum(sample_results) / len(sample_results)
            calculated['average_gel'] = display_number(average)
            if len(sample_results) == sample_count:
                assessed_result = 'PASS' if 75 <= average <= 95 else 'FAIL'
    elif kind == 'ribbon_peel':
        matrix = next(section for section in definition['sections'] if section['type'] == 'ribbon_peel_matrix')
        completed_positions = 0
        position_passes = []
        expected_positions = len(matrix['tracks']) * len(matrix['sides']) * matrix['count']
        for track in matrix['tracks']:
            for side in matrix['sides']:
                for position in range(1, matrix['count'] + 1):
                    keys = [
                        ribbon_peak_key(track['key'], side['key'], position, peak)
                        for peak in range(1, matrix['peaks'] + 1)
                        if not ribbon_not_required(track, position, peak)
                    ]
                    entered = [values.get(key, '') for key in keys]
                    if action == 'submit' and not all(entered):
                        raise ValueError(
                            f"Complete all required peaks for Stringer {track['label']} "
                            f"{side['label']}, Serial {position}."
                        )
                    if not any(entered):
                        continue
                    numbers = []
                    for index, value in enumerate(entered):
                        if not value:
                            continue
                        number = clean_number(value, field_map[keys[index]]['label'])
                        if number < 0:
                            raise ValueError(field_map[keys[index]]['label'] + ' cannot be negative.')
                        numbers.append(number)
                    if len(numbers) != len(keys):
                        continue
                    completed_positions += 1
                    average = sum(numbers) / len(numbers)
                    calculated[ribbon_calculation_key(track['key'], side['key'], position, 'average')] = display_number(average)
                    calculated[ribbon_calculation_key(track['key'], side['key'], position, 'n_per_mm')] = display_number(average / PEEL_DIVISOR_MM)
                    position_passes.append(all(number >= matrix['minimum'] for number in numbers))
        if completed_positions == expected_positions:
            assessed_result = 'PASS' if all(position_passes) else 'FAIL'
    elif kind == 'adhesion':
        group_results = {}
        reading_count = next(section['count'] for section in definition['sections'] if section['type'] == 'adhesion_readings')
        for group, minimum in [('glass', 60), ('backsheet', 40)]:
            entered = [values.get(f'{group}_{reading}', '') for reading in range(1, reading_count + 1)]
            if all(entered):
                numbers = [clean_number(value, f'{group.title()} reading {index}') for index, value in enumerate(entered, 1)]
                average = sum(numbers) / len(numbers)
                calculated[f'{group}_average'] = display_number(average)
                group_results[group] = average >= minimum
        if len(group_results) == 2:
            assessed_result = 'PASS' if all(group_results.values()) else 'FAIL'
    elif kind == 'busbar_peel':
        matrix = next(section for section in definition['sections'] if section['type'] == 'busbar_matrix')
        active_rows = []
        row_passes = []
        for row in matrix['rows']:
            prefix = row['key']
            reading_values = [values.get(f'{prefix}_r{reading}', '') for reading in range(1, matrix['count'] + 1)]
            active = values.get(f'{prefix}_enabled') == '1' or any(reading_values)
            if not active:
                continue
            active_rows.append(prefix)
            values[f'{prefix}_enabled'] = '1'
            if action == 'submit' and not all(reading_values):
                raise ValueError(f"Complete all {matrix['count']} readings for {row['label']}.")
            if all(reading_values):
                numbers = [clean_number(value, f"{row['label']} — Ribbon {index}") for index, value in enumerate(reading_values, 1)]
                average = sum(numbers) / len(numbers)
                calculated[f'{prefix}_average'] = display_number(average)
                calculated[f'{prefix}_n_per_mm'] = display_number(average / PEEL_DIVISOR_MM)
                row_passes.append(all(number >= matrix['minimum'] for number in numbers))
        if action == 'submit' and not active_rows:
            raise ValueError('Select at least one busbar interconnector type and enter its readings.')
        if active_rows and len(row_passes) == len(active_rows):
            assessed_result = 'PASS' if all(row_passes) else 'FAIL'

    if assessed_result:
        calculated['overall_result'] = assessed_result
    result = assessed_result if action == 'submit' else 'Not evaluated'
    if action == 'submit' and not result:
        raise ValueError('Complete the controlled test readings before submitting.')
    payload = {
        'format': 'ctq-v1',
        'definition_id': kind,
        'document': definition['document'],
        'acceptance': definition['acceptance'],
        'values': values,
        'calculated': calculated,
    }
    return payload, result

def refreshed_ctq_payload(kind, payload):
    """Apply the current peel calculations for display without rewriting stored records."""
    if kind not in ('ribbon_peel', 'busbar_peel') or not isinstance(payload, dict):
        return payload
    if payload.get('format') != 'ctq-v1':
        return payload
    try:
        recalculated, _ = prepare_ctq_payload(kind, payload, 'draft')
    except (ValueError, TypeError, KeyError):
        return payload
    refreshed = dict(payload)
    refreshed['calculated'] = recalculated.get('calculated', {})
    return refreshed

def now():
    return datetime.now(IST).isoformat(timespec='seconds')

def production_defaults(moment=None):
    moment = moment or datetime.now(IST)
    hour = moment.hour
    return ((moment - timedelta(days=1) if hour < 6 else moment).date().isoformat(),
            'A' if 6 <= hour < 14 else 'B' if 14 <= hour < 22 else 'C')

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATA / 'commercial-demo.db', timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA busy_timeout=5000')
        g.db.execute('PRAGMA synchronous=NORMAL')
        g.db.execute('PRAGMA temp_store=MEMORY')
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    con = g.pop('db', None)
    if con is not None:
        con.close()

def import_previous_demo():
    """Read previous demo records once, leaving their source database untouched."""
    legacy_path = DATA / 'qualitysystem.db'
    if not legacy_path.exists() or db().execute('SELECT 1 FROM users LIMIT 1').fetchone():
        return
    source = sqlite3.connect(f'{legacy_path.as_uri()}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        columns = {row['name'] for row in source.execute('PRAGMA table_info(reports)')}
        if not {'reference', 'customer', 'payload'}.issubset(columns):
            return
        states = {'Pending Approval': 'Pending approval', 'Returned for Correction': 'Returned for correction',
                  'Approved with Remarks': 'Approved with remarks'}
        with db():
            for user in source.execute('SELECT * FROM users'):
                db().execute('INSERT INTO users(id,employee,name,password,role,active,is_superuser) VALUES (?,?,?,?,?,?,?)',
                             (user['id'],user['employee'],user['name'],user['password'],user['role'],user['active'],int(user['employee']=='0001')))
            for report in source.execute('SELECT * FROM reports'):
                old = json.loads(report['payload'])
                values = old.get('values', {})
                definition = old.get('definition', {})
                labels = ['Parameter','Reading']
                readings = []
                field_labels = {f['key']: f.get('label', f['key']) for sec in definition.get('sections', []) for f in sec.get('fields', [])}
                for key,value in values.items():
                    readings.append({'Parameter': field_labels.get(key,key.replace('_',' ').title()), 'Reading': str(value), 'Result': report['result']})
                for key,value in old.get('calculations', {}).items():
                    readings.append({'Parameter': key.replace('_',' ').title(), 'Reading': str(value), 'Result': report['result']})
                payload = {'form_version':'Previous demo record', 'labels':labels, 'rows':readings,
                           'metadata':{'customer_name':report['customer'],'production_order':report['reference']},
                           'legacy_source':old}
                timestamp = report['created'][:16]
                db().execute('INSERT INTO reports(id,kind,day,shift,line,machine,inspection_time,owner,approver,status,result,payload,remarks,version,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             (report['id'],report['kind'],report['day'],report['shift'],report['line'],report['reference'] or 'Demo floor',timestamp,
                              report['owner'],report['approver'],states.get(report['status'],report['status']),report['result'],json.dumps(payload),
                              report['remarks'],report['version'],report['created'],report['updated']))
            for event in source.execute('SELECT * FROM history'):
                db().execute('INSERT INTO history(id,report,actor,action,comment,snapshot,time) VALUES (?,?,?,?,?,?,?)',
                             (event['id'],event['report'],event['actor'],states.get(event['action'],event['action']),event['comment'],'{}',event['time']))
    finally:
        source.close()

def init_db():
    with app.app_context():
        db().executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, employee TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('operator','incharge','admin')),
          active INTEGER NOT NULL DEFAULT 1, is_superuser INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS reports (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, day TEXT NOT NULL, shift TEXT NOT NULL,
          line TEXT NOT NULL, machine TEXT NOT NULL, inspection_time TEXT NOT NULL,
          owner INTEGER NOT NULL REFERENCES users(id), approver INTEGER REFERENCES users(id),
          status TEXT NOT NULL, result TEXT NOT NULL, payload TEXT NOT NULL, remarks TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY, report INTEGER NOT NULL REFERENCES reports(id),
          actor INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
          comment TEXT NOT NULL, snapshot TEXT NOT NULL, time TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS report_day ON reports(day,shift);
        CREATE INDEX IF NOT EXISTS report_approver ON reports(approver,status);
        CREATE INDEX IF NOT EXISTS report_kind_day ON reports(kind,day,id);
        CREATE INDEX IF NOT EXISTS report_owner_kind_day ON reports(owner,kind,day,id);
        CREATE INDEX IF NOT EXISTS report_approver_kind_day ON reports(approver,kind,day,id);
        CREATE TABLE IF NOT EXISTS attempts (employee TEXT PRIMARY KEY, count INTEGER NOT NULL, time TEXT NOT NULL);
        ''')
        user_columns = {row['name'] for row in db().execute('PRAGMA table_info(users)').fetchall()}
        if 'is_superuser' not in user_columns:
            db().execute('ALTER TABLE users ADD COLUMN is_superuser INTEGER NOT NULL DEFAULT 0')
        if 'theme_color' not in user_columns:
            db().execute("ALTER TABLE users ADD COLUMN theme_color TEXT NOT NULL DEFAULT 'red'")
        if 'theme_mode' not in user_columns:
            db().execute("ALTER TABLE users ADD COLUMN theme_mode TEXT NOT NULL DEFAULT 'dark'")
        if 'appearance' not in user_columns:
            db().execute("ALTER TABLE users ADD COLUMN appearance TEXT NOT NULL DEFAULT 'midnight'")
            db().execute("""UPDATE users SET appearance=CASE theme_color
                WHEN 'blue' THEN 'ocean' WHEN 'green' THEN 'emerald' WHEN 'purple' THEN 'plum'
                ELSE CASE theme_mode WHEN 'light' THEN 'daylight' ELSE 'midnight' END END""")
        # Employee 0001 is the single, fixed user-management custodian.  Keeping
        # this as a flag preserves the existing role CHECK and all report FKs.
        db().execute("UPDATE users SET is_superuser=CASE WHEN employee='0001' THEN 1 ELSE 0 END")
        db().execute("UPDATE users SET active=1 WHERE employee='0001'")
        import_previous_demo()
        if not db().execute('SELECT 1 FROM users LIMIT 1').fetchone():
            demo_password = generate_password_hash('Demo123')
            db().executemany('INSERT INTO users(employee,name,password,role,is_superuser) VALUES (?,?,?,?,?)', [
                ('OP100','Demo Operator',demo_password,'operator',0),
                ('IC100','Demo Incharge',demo_password,'incharge',0),
                ('AD100','Demo Administrator',demo_password,'admin',0),
                ('0001','Demo Super User',demo_password,'admin',1),
            ])
        if not db().execute("SELECT 1 FROM users WHERE employee='0001'").fetchone():
            db().execute('INSERT INTO users(employee,name,password,role,is_superuser) VALUES (?,?,?,?,1)',
                         ('0001','Demo Super User',generate_password_hash('Demo123'),'admin'))
        db().commit()

def is_superuser(person=None):
    person = person if person is not None else g.user
    return bool(person and (person['employee'] == '0001' or person['is_superuser']))

def require(*roles):
    def wrap(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if not g.user:
                return redirect(url_for('login'))
            if roles and is_superuser():
                abort(403)
            if roles and g.user['role'] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return inner
    return wrap

def require_superuser(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not g.user:
            return redirect(url_for('login'))
        if not is_superuser():
            abort(403)
        return fn(*args, **kwargs)
    return inner

@app.before_request
def security():
    g.request_started = time.perf_counter()
    g.user = None
    # Static assets never need a database connection or a session cookie.
    if request.endpoint == 'static':
        return None
    uid = session.get('uid')
    if uid is not None:
        g.user = db().execute(
            'SELECT id,employee,name,password,role,active,is_superuser,theme_color,theme_mode,appearance FROM users WHERE id=? AND active=1',
            (uid,),
        ).fetchone()
    session.setdefault('csrf', secrets.token_urlsafe(32))
    if request.method == 'POST' and not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
        abort(400, 'Session expired or invalid form token. Reload the page and try again.')

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; style-src 'self'; "
        "script-src 'self' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; "
        "connect-src 'self' https://cdn.jsdelivr.net https://tessdata.projectnaptha.com; "
        "worker-src 'self' blob:; child-src 'self' blob:; "
        "img-src 'self' data: blob:; form-action 'self'; frame-ancestors 'none'"
    )
    if request.endpoint == 'static':
        # Versioned CSS/JS can remain cached for a year. Other images and icons
        # receive a one-day cache while still allowing routine replacements.
        response.headers['Cache-Control'] = (
            'public, max-age=31536000, immutable' if request.args.get('v')
            else 'public, max-age=86400'
        )
    else:
        response.headers['Cache-Control'] = 'no-store'
    started = getattr(g, 'request_started', None)
    if started is not None:
        response.headers['Server-Timing'] = f'qms;dur={(time.perf_counter()-started)*1000:.1f}'
    return response

@app.context_processor
def helpers():
    return dict(forms=FORMS, csrf=session.get('csrf'), user=g.user, approved=APPROVED,
                ctq_kinds=CTQ_KINDS, form_descriptions=FORM_DESCRIPTIONS,
                ctq_definitions=CTQ_DEF, ctq_material_options=CTQ_MATERIAL_OPTIONS,
                observation_unit=observation_unit, display_observation_value=display_observation_value,
                is_superuser=is_superuser)

@app.route('/appearance', methods=['GET', 'POST'])
@require()
def appearance():
    if request.method == 'POST':
        selected = request.form.get('appearance', '').strip().lower()
        if selected not in ('midnight', 'daylight', 'ocean', 'emerald', 'plum', 'amber'):
            abort(400, 'Choose a supported appearance.')
        with db():
            db().execute('UPDATE users SET appearance=? WHERE id=?', (selected, g.user['id']))
        flash('Your appearance settings have been saved.')
        return redirect(url_for('home') if request.form.get('from_menu') else url_for('appearance'))
    return render_template('appearance.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        employee = request.form.get('employee', '').strip()[:80]
        attempt = db().execute('SELECT * FROM attempts WHERE employee=?', (employee,)).fetchone()
        if attempt and attempt['count'] >= 5 and datetime.fromisoformat(attempt['time']) > datetime.now(IST)-timedelta(minutes=15):
            flash('Too many attempts. Wait 15 minutes before trying again.')
            return render_template('login.html'), 429
        person = db().execute('SELECT * FROM users WHERE employee=? AND active=1', (employee,)).fetchone()
        if person and check_password_hash(person['password'], request.form.get('password', '')):
            db().execute('DELETE FROM attempts WHERE employee=?', (employee,)); db().commit()
            session.clear(); session.update(uid=person['id'], csrf=secrets.token_urlsafe(32))
            session.permanent = True
            return redirect(url_for('home'))
        count = attempt['count'] + 1 if attempt and datetime.fromisoformat(attempt['time']) > datetime.now(IST)-timedelta(minutes=15) else 1
        db().execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)', (employee, count, now())); db().commit()
        flash('Employee ID or password is incorrect.')
    return render_template('login.html')

@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.post('/api/render-pdf')
@require('operator')
def render_pdf_page():
    """Render page one of a scanner PDF in memory for the browser OCR workflow."""
    upload = request.files.get('pdf')
    if not upload or not upload.filename:
        abort(400, 'Select a scanner PDF and try again.')
    if not upload.filename.lower().endswith('.pdf') and upload.mimetype != 'application/pdf':
        abort(400, 'Only PDF files can be processed.')
    pdf_bytes = upload.read(25 * 1024 * 1024 + 1)
    if len(pdf_bytes) > 25 * 1024 * 1024:
        abort(413, 'PDF must be smaller than 25 MB.')
    if not pdf_bytes.startswith(b'%PDF-'):
        abort(400, 'The selected file is not a readable PDF.')
    try:
        import fitz
    except ImportError:
        abort(503, 'The QMS PDF renderer is unavailable.')
    document = None
    try:
        document = fitz.open(stream=pdf_bytes, filetype='pdf')
        if document.page_count < 1:
            abort(400, 'The PDF contains no pages.')
        page = document.load_page(0)
        longest_side = max(page.rect.width, page.rect.height)
        scale = min(4.0, max(2.0, 3000.0 / longest_side)) if longest_side else 2.0
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        rendered = pixmap.tobytes('png')
    except Exception:
        abort(400, 'The first PDF page could not be rendered. Rescan it and try again.')
    finally:
        if document is not None:
            document.close()
    return send_file(io.BytesIO(rendered), mimetype='image/png',
                     download_name='qms-pdf-page.png', max_age=0)

def visible_clause():
    if is_superuser(): return '0=1', []
    if g.user['role'] == 'admin': return '1=1', []
    if g.user['role'] == 'incharge': return 'r.approver=?', [g.user['id']]
    return 'r.owner=?', [g.user['id']]

def selected_reports(day=None, shift=None, kind=None, line=None, kinds=None, include_payload=True):
    clause, args = visible_clause()
    placeholders = ','.join('?' for _ in FORMS)
    clause = f"({clause}) AND r.kind IN ({placeholders}) AND r.status!='Deleted'"
    args.extend(FORMS.keys())
    for column, value in [('day',day), ('shift',shift), ('kind',kind), ('line',line)]:
        if value:
            clause += f' AND r.{column}=?'; args.append(value)
    if kinds and not kind:
        kinds = tuple(k for k in kinds if k in FORMS)
        if kinds:
            placeholders = ','.join('?' for _ in kinds)
            clause += f' AND r.kind IN ({placeholders})'
            args.extend(kinds)
    report_columns = 'r.*' if include_payload else '''
        r.id,r.kind,r.day,r.shift,r.line,r.machine,r.inspection_time,
        r.owner,r.approver,r.status,r.result,r.remarks,r.version,r.created,r.updated
    '''
    return db().execute(
        f'SELECT {report_columns}, u.name operator_name, a.name approver_name '
        'FROM reports r JOIN users u ON r.owner=u.id LEFT JOIN users a ON r.approver=a.id '
        'WHERE '+clause+' ORDER BY r.day DESC,r.shift,r.id DESC', args
    ).fetchall()

@app.get('/')
@require()
def home():
    if is_superuser():
        return redirect(url_for('users'))
    requested_module = request.args.get('module', '').lower()
    module = requested_module if requested_module in MODULE_KINDS else 'ipqc'
    filters = {k:request.args.get(k,'') for k in ['day','shift','kind','line']}
    if filters['kind'] and filters['kind'] not in FORMS:
        filters['kind'] = ''
    if filters['kind']:
        kind_module = 'ipqc' if filters['kind'] == 'ipqc' else 'ctq'
        if requested_module not in MODULE_KINDS:
            module = kind_module
        elif kind_module != module:
            filters['kind'] = ''
    report_filters = {k:v for k,v in filters.items() if k != 'kind'}
    reports = selected_reports(
        **report_filters,
        kind=filters['kind'] or None,
        kinds=None if filters['kind'] else MODULE_KINDS[module],
        include_payload=False,
    )
    counts = {s:sum(r['status']==s for r in reports)
              for s in ['Draft','Pending approval','Returned for correction','Rejected',*APPROVED]}
    module_forms = {kind:FORMS[kind] for kind in MODULE_KINDS[module]}
    return render_template(
        'home.html', reports=reports, counts=counts, filters=filters,
        today=production_defaults()[0], selected_module=module, module_forms=module_forms,
    )

def get_report(rid):
    clause, args = visible_clause()
    r = db().execute("SELECT r.*,u.name operator_name,a.name approver_name FROM reports r JOIN users u ON r.owner=u.id LEFT JOIN users a ON r.approver=a.id WHERE r.id=? AND r.status!='Deleted' AND "+clause,[rid,*args]).fetchone()
    if not r or r['kind'] not in FORMS: abort(404)
    return r

def can_current_user_review(report):
    """Allow the assigned incharge or any active administrator to review."""
    if report['status'] != 'Pending approval':
        return False
    if g.user['role'] == 'admin' and not is_superuser():
        return True
    return g.user['role'] == 'incharge' and report['approver'] == g.user['id']

def observation_value_present(value):
    """Treat zero and other explicit values as filled, but not blank text or null."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True

def ipqc_stage_progress(payload):
    """Calculate saved IPQC completion from observation fields, including legacy drafts."""
    stages = []
    for section in payload.get('sections', []):
        filled = 0
        total = 0
        for item in section.get('items', []):
            observations = item.get('observations', [])
            if isinstance(observations, dict):
                observations = list(observations.values())
            if not isinstance(observations, (list, tuple)):
                observations = []
            item_values = []
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                values = observation.get('values', {})
                if isinstance(values, dict):
                    item_values.extend(values.values())
            if item_values:
                total += len(item_values)
                filled += sum(observation_value_present(value) for value in item_values)
            else:
                # Very old records may have only the item-level completion result.
                total += 1
                filled += item.get('result') in ('Completed', 'PASS', 'FAIL')
        status = 'Completed' if total and filled == total else ('In progress' if filled else 'Not started')
        stages.append({
            'name': section.get('name', 'Inspection stage'),
            'status': status,
            'percent': round(filled * 100 / total) if total else 0,
        })
    return stages

def log(rid, action, comment=''):
    snapshot = dict(db().execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone())
    db().execute('INSERT INTO history(report,actor,action,comment,snapshot,time) VALUES (?,?,?,?,?,?)',
                 (rid,g.user['id'],action,comment,json.dumps(snapshot),now()))

@app.route('/new/<kind>', methods=['GET','POST'])
@app.route('/edit/<int:rid>', methods=['GET','POST'])
@require('operator')
def edit(kind=None, rid=None):
    old = get_report(rid) if rid else None
    if old and (old['owner']!=g.user['id'] or old['status'] not in ['Draft','Returned for correction']): abort(403)
    kind = old['kind'] if old else kind
    if kind not in FORMS: abort(404)
    if not old and kind not in ACTIVE_KINDS: abort(404)
    approvers = db().execute("SELECT id,name,employee FROM users WHERE role='incharge' AND active=1 ORDER BY name").fetchall()
    returned = db().execute("SELECT h.comment,h.time,u.name FROM history h JOIN users u ON h.actor=u.id WHERE h.report=? AND h.action='Returned for correction' ORDER BY h.id DESC LIMIT 1",(rid,)).fetchone() if old else None
    labels = FORMS[kind][1]
    defaults = production_defaults()
    record = dict(old) if old else dict(day=defaults[0],shift=defaults[1],line='Line 1',machine='',inspection_time=datetime.now(IST).strftime('%Y-%m-%dT%H:%M'),approver='',remarks='',version=0,status='Draft')
    old_payload = json.loads(old['payload']) if old else {}
    if old and kind in CTQ_KINDS:
        old_payload = refreshed_ctq_payload(kind, old_payload)
    metadata = old_payload.get('metadata', {}) if kind == 'ipqc' else {}
    ctq_values = ctq_default_values(kind) if kind in CTQ_KINDS else {}
    ctq_calculated = {}
    if kind == 'ipqc':
        saved_rows = {item['id']: {
            'observations': {str(i): obs.get('values', {}) for i, obs in enumerate(item.get('observations', []))},
            'result': item.get('result', 'Not evaluated'), 'remarks': item.get('remarks', '')
        } for section in old_payload.get('sections', []) for item in section.get('items', [])}
        rows = []
    elif kind in CTQ_KINDS:
        saved_rows = {}
        if old_payload.get('format') == 'ctq-v1':
            ctq_values.update(old_payload.get('values', {}))
            ctq_calculated = old_payload.get('calculated', {})
        rows = {'format': 'ctq-v1', 'values': ctq_values}
    else:
        saved_rows = {}
        rows = old_payload.get('rows', [{**{k:'' for k in labels},'Result':'Not evaluated'}])
    if request.method == 'POST':
        record.update({key:request.form.get(key,'').strip() for key in ['day','shift','line','machine','inspection_time','approver','remarks','version']})
        action=request.form.get('action')
        if action not in ['draft','submit']: abort(400)
        try:
            rows=json.loads(request.form.get('rows','[]'))
            if kind in CTQ_KINDS:
                if not isinstance(rows, dict): raise ValueError('Invalid CTQ test data.')
            elif not isinstance(rows,list):
                raise ValueError('Invalid readings.')
            datetime.strptime(record['day'],'%Y-%m-%d')
            datetime.strptime(record['inspection_time'],'%Y-%m-%dT%H:%M')
            if record['shift'] not in ['A','B','C']: raise ValueError('Choose a shift.')
            if not record['line'] or len(record['line'])>100 or len(record['machine'])>150 or len(record['remarks'])>3000: raise ValueError('Check line, machine, and remarks lengths.')
            if action=='submit' and not record['machine']: raise ValueError('Enter a machine or test location.')
            approver=int(record['approver']) if record['approver'] else None
            if approver and approver not in [p['id'] for p in approvers]: raise ValueError('Select an active shift incharge.')
            if action=='submit' and not approver: raise ValueError('Select the shift incharge before submitting.')
            if kind == 'ipqc':
                metadata = {}
                for field in IPQC_DEF['header_fields']:
                    if field.get('type') == 'checkbox':
                        metadata[field['key']] = request.form.get('meta_' + field['key']) == '1'
                    else:
                        value = request.form.get('meta_' + field['key'], '').strip()
                        if len(value) > 200: raise ValueError(field['label'] + ' is too long.')
                        if action == 'submit' and field.get('required') and not value:
                            raise ValueError('Complete ' + field['label'] + '.')
                        metadata[field['key']] = value
                submitted = {str(row.get('id')): row for row in rows if isinstance(row, dict)}
                clean_sections = []
                for section in IPQC_DEF['sections']:
                    clean_items = []
                    for definition in section['items']:
                        entered = submitted.get(definition['id'], {})
                        entered_observations = entered.get('observations', {})
                        clean_observations = []
                        for index, observation in enumerate(definition['observations']):
                            source = entered_observations.get(str(index), entered_observations.get(index, {}))
                            source_values = source.get('values', {}) if isinstance(source, dict) else {}
                            values = {label: str(source_values.get(label, '')).strip() for label in observation['fields']}
                            if any(len(value) > 500 for value in values.values()):
                                raise ValueError(definition['parameter'] + ': a value is too long.')
                            if action == 'submit' and any(not value for value in values.values()):
                                raise ValueError('Complete all observations for: ' + definition['parameter'])
                            clean_observations.append({'label': observation['label'], 'values': values})
                        item_result = 'Completed' if action == 'submit' else 'Not evaluated'
                        item_remarks = ''
                        clean_items.append({**definition, 'observations': clean_observations,
                                            'result': item_result, 'remarks': item_remarks})
                    clean_sections.append({'number': section['number'], 'name': section['name'], 'items': clean_items})
                result = 'Completed' if action == 'submit' else 'Not evaluated'
                payload=json.dumps({'format':'ipqc-v1','definition_id':IPQC_DEF['id'],
                                    'document':{k:IPQC_DEF[k] for k in ['document_no','issue_date','revision_no','revision_date','copy']},
                                    'metadata':metadata,'sections':clean_sections})
            elif kind in CTQ_KINDS:
                source_values = rows.get('values', rows)
                if isinstance(source_values, dict):
                    ctq_values = {str(key): str(value) for key, value in source_values.items()}
                prepared, result = prepare_ctq_payload(kind, rows, action)
                ctq_values = prepared['values']
                ctq_calculated = prepared['calculated']
                rows = prepared
                payload = json.dumps(prepared)
            else:
                if not 1 <= len(rows) <= 100: raise ValueError('Enter between 1 and 100 reading rows.')
                clean=[]
                for row in rows:
                    if not isinstance(row,dict): raise ValueError('Invalid reading row.')
                    item={k:str(row.get(k,'')).strip() for k in [*labels,'Result']}
                    if any(len(v)>500 for v in item.values()): raise ValueError('A reading is too long (maximum 500 characters).')
                    if item['Result'] not in RESULTS: raise ValueError('Select a valid result.')
                    if action=='submit' and any(not item[k] for k in labels): raise ValueError('Complete every reading field before submitting.')
                    if action=='submit' and item['Result']=='Not evaluated': raise ValueError('Select PASS or FAIL for every reading.')
                    clean.append(item)
                rows=clean
                result='FAIL' if any(x['Result']=='FAIL' for x in rows) else 'PASS' if all(x['Result']=='PASS' for x in rows) else 'Not evaluated'
                payload=json.dumps(dict(form_version='STARTER-1', labels=labels, rows=rows))
            status='Pending approval' if action=='submit' else 'Draft'
            fields=(record['day'],record['shift'],record['line'],record['machine'],record['inspection_time'],approver,status,result,payload,record['remarks'],now())
            with db():
                if old:
                    cur=db().execute("UPDATE reports SET day=?,shift=?,line=?,machine=?,inspection_time=?,approver=?,status=?,result=?,payload=?,remarks=?,updated=?,version=version+1 WHERE id=? AND version=? AND status IN ('Draft','Returned for correction')",(*fields,rid,int(record['version'])))
                    if cur.rowcount!=1: abort(409,'This report changed in another tab. Reload before saving.')
                else:
                    cur=db().execute('INSERT INTO reports(day,shift,line,machine,inspection_time,approver,status,result,payload,remarks,updated,kind,owner,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(*fields,kind,g.user['id'],now()))
                    rid=cur.lastrowid
                log(rid,'Submitted' if action=='submit' else 'Draft saved')
            flash('Submitted to the selected incharge. An administrator can also review it when required.' if action=='submit' else 'Draft saved.')
            return redirect(url_for('detail',rid=rid))
        except (ValueError,TypeError,KeyError) as error:
            if kind == 'ipqc' and isinstance(rows, list):
                saved_rows = {str(item.get('id')): {
                    'observations': {str(index): observation.get('values', {}) for index, observation in
                                     (item.get('observations', {}) or {}).items() if isinstance(observation, dict)},
                    'result': item.get('result', 'Not evaluated'), 'remarks': item.get('remarks', '')
                } for item in rows if isinstance(item, dict) and item.get('id')}
            flash(str(error) or 'Check the entered fields.')
    return render_template('edit.html',kind=kind,record=record,rows=rows,labels=labels,approvers=approvers,
                           ipqc=IPQC_DEF if kind=='ipqc' else {'sections':[]}, metadata=metadata, saved_rows=saved_rows,
                           material_options=MATERIAL_FIELD_OPTIONS, returned=returned,
                           ctq=CTQ_DEF.get(kind), ctq_values=ctq_values, ctq_calculated=ctq_calculated)

@app.get('/report/<int:rid>')
@require()
def detail(rid):
    report=get_report(rid)
    history=db().execute('SELECT h.*,u.name actor_name,u.role actor_role FROM history h JOIN users u ON h.actor=u.id WHERE report=? ORDER BY h.id DESC',(rid,)).fetchall()
    reviewed_by = next((item for item in history if item['action'] in REVIEW_OUTCOMES), None)
    if report['status'] not in REVIEW_OUTCOMES:
        reviewed_by = None
    payload=refreshed_ctq_payload(report['kind'], json.loads(report['payload']))
    stage_progress = ipqc_stage_progress(payload) if report['kind']=='ipqc' and payload.get('format')=='ipqc-v1' else []
    return render_template('detail.html',r=report,payload=payload,history=history,stage_progress=stage_progress,
                           ctq=CTQ_DEF.get(report['kind']),
                           can_review=can_current_user_review(report), reviewed_by=reviewed_by)

@app.post('/report/<int:rid>/delete')
@require('operator')
def delete_draft(rid):
    report = get_report(rid)
    if report['owner'] != g.user['id'] or report['status'] != 'Draft':
        abort(403, 'Only the operator who created an unsubmitted draft can delete it.')
    version = request.form.get('version', '')
    if not version.isdecimal():
        abort(400, 'Invalid report version. Reload the report and try again.')
    with db():
        changed = db().execute(
            "UPDATE reports SET status='Deleted', updated=?, version=version+1 "
            "WHERE id=? AND owner=? AND status='Draft' AND version=?",
            (now(), rid, g.user['id'], int(version)),
        )
        if changed.rowcount != 1:
            abort(409, 'This draft changed in another tab. Reload before deleting.')
        log(rid, 'Draft deleted')
    flash('Draft removed from your records. Its audit history is retained.')
    return redirect(url_for('home') + '#records')

@app.post('/report/<int:rid>/review')
@require('incharge','admin')
def review(rid):
    r=get_report(rid)
    if not can_current_user_review(r): abort(403)
    action=request.form.get('action')
    if action not in REVIEW_OUTCOMES: abort(400)
    comment=request.form.get('comment','').strip()
    if len(comment)>3000: abort(400,'Comment is too long.')
    if action!='Approved' and not comment:
        flash('A comment is required for this action.'); return redirect(url_for('detail',rid=rid))
    if action=='Approved' and r['result']=='FAIL':
        flash('For a failed result, approve with remarks, return for correction, or reject the report.'); return redirect(url_for('detail',rid=rid))
    with db():
        cur=db().execute("UPDATE reports SET status=?,updated=?,version=version+1 WHERE id=? AND version=? AND status='Pending approval'",(action,now(),rid,request.form.get('version')))
        if cur.rowcount!=1: abort(409,'Another review already changed this report.')
        log(rid,action,comment)
    flash(action+'.')
    return redirect(url_for('detail',rid=rid))

@app.route('/users',methods=['GET','POST'])
@require_superuser
def users():
    if request.method=='POST':
        employee=request.form.get('employee','').strip(); name=request.form.get('name','').strip()
        role=request.form.get('role'); password=request.form.get('password','')
        if not employee or len(employee)>80 or not name or len(name)>100 or role not in ['operator','incharge','admin'] or not 5 <= len(password) <= 12:
            flash('Enter employee ID, name, role, and a password from 5 to 12 characters.')
        else:
            try:
                with db(): db().execute('INSERT INTO users(employee,name,password,role) VALUES (?,?,?,?)',(employee,name,generate_password_hash(password),role))
                flash('User account created. Give the credentials to that employee securely.')
                return redirect(url_for('users'))
            except sqlite3.IntegrityError: flash('That employee ID already exists.')
    return render_template('users.html',people=db().execute(
        'SELECT id,employee,name,role,active,is_superuser FROM users ORDER BY is_superuser DESC,active DESC,role,name'
    ).fetchall())

@app.post('/users/<int:uid>/activate')
@require_superuser
def activate_user(uid):
    target = db().execute('SELECT id,name,active FROM users WHERE id=?', (uid,)).fetchone()
    if not target or target['active'] == -1:
        abort(404)
    if target['active'] == 1:
        flash('That user is already active.')
    else:
        with db(): db().execute('UPDATE users SET active=1 WHERE id=?', (uid,))
        flash(f'{target["name"]} was activated.')
    return redirect(url_for('users'))

@app.post('/users/<int:uid>/deactivate')
@require_superuser
def deactivate_user(uid):
    target = db().execute('SELECT id,name,active,is_superuser FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        abort(404)
    if uid == g.user['id'] or target['is_superuser']:
        flash('The Super User account cannot be deactivated.')
    elif target['active'] != 1:
        flash('That user is not active.')
    else:
        with db(): db().execute('UPDATE users SET active=0 WHERE id=?', (uid,))
        flash(f'{target["name"]} was deactivated. Historical reports were preserved.')
    return redirect(url_for('users'))

@app.post('/users/<int:uid>/delete')
@require_superuser
def delete_user(uid):
    target = db().execute('SELECT id,employee,name,role,active,is_superuser FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        abort(404)
    if uid == g.user['id'] or target['is_superuser']:
        flash('The Super User account cannot be deleted.')
        return redirect(url_for('users'))
    if target['active'] == -1:
        flash('That user is already deleted.')
        return redirect(url_for('users'))
    # A tombstone preserves immutable report ownership and audit-history FKs,
    # while permanently removing the account from login and active lists.
    with db():
        db().execute('UPDATE users SET active=-1 WHERE id=?', (uid,))
    flash(f'{target["name"]} was deleted. Historical reports and audit records were preserved.')
    return redirect(url_for('users'))

@app.route('/password',methods=['GET','POST'])
@require()
def password():
    if request.method=='POST':
        new=request.form.get('new','')
        if not check_password_hash(g.user['password'],request.form.get('current','')) or not 5 <= len(new) <= 12 or new!=request.form.get('confirm'):
            flash('Check your current password; new passwords must match and contain 5 to 12 characters.')
        else:
            with db(): db().execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(new),g.user['id']))
            session.clear(); flash('Password changed. Please log in again.')
            return redirect(url_for('login'))
    return render_template('password.html')

def make_pdf(reports, title, context=None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
    from reportlab.platypus import (Image as PDFImage, KeepTogether, LongTable, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)
    if 'QMS-Regular' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('QMS-Regular', ROOT / 'assets' / 'fonts' / 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('QMS-Bold', ROOT / 'assets' / 'fonts' / 'DejaVuSans-Bold.ttf'))
        pdfmetrics.registerFontFamily('QMS-Regular', normal='QMS-Regular', bold='QMS-Bold')

    navy = colors.HexColor('#0B1F3A')
    navy_2 = colors.HexColor('#163A63')
    blue = colors.HexColor('#2D5B9B')
    orange = colors.HexColor('#F4A62A')
    pale_blue = colors.HexColor('#EAF1F8')
    pale_orange = colors.HexColor('#FFF3DE')
    line = colors.HexColor('#8998AA')
    text_color = colors.HexColor('#172235')
    white = colors.white

    body_style = ParagraphStyle('PDFBody', fontName='QMS-Regular', fontSize=5.7,
                                leading=7.1, textColor=text_color, spaceAfter=0)
    body_center_style = ParagraphStyle('PDFBodyCenter', parent=body_style, alignment=TA_CENTER)
    bold_style = ParagraphStyle('PDFBold', parent=body_style, fontName='QMS-Bold')
    bold_center_style = ParagraphStyle('PDFBoldCenter', parent=bold_style, alignment=TA_CENTER)
    table_header_style = ParagraphStyle('PDFTableHeader', parent=bold_center_style,
                                        textColor=white)
    small_style = ParagraphStyle('PDFSmall', parent=body_style, fontSize=4.8, leading=5.9)
    small_center_style = ParagraphStyle('PDFSmallCenter', parent=small_style, alignment=TA_CENTER)
    title_style = ParagraphStyle('PDFTitle', parent=bold_center_style, fontSize=10.5,
                                 leading=12.5, textColor=navy)
    section_style = ParagraphStyle('PDFSection', parent=bold_style, fontSize=8.5,
                                   leading=10.5, textColor=navy)
    cover_title_style = ParagraphStyle('PDFCoverTitle', parent=bold_style, fontSize=15,
                                       leading=18, textColor=navy)

    def clean(value):
        return escape(str(value if value not in [None, ''] else '-')).replace('\n', '<br/>')

    def p(value, style=body_style):
        return Paragraph(clean(value), style)

    def rich(parts, style=body_style):
        """Render trusted labels with escaped database values."""
        return Paragraph(''.join(parts), style)

    def label_value(label, value):
        return f'<b>{escape(str(label))}:</b> {clean(value)}'

    def compact_table(data, widths, header_rows=0, align='LEFT', font_size=4.7):
        table = Table(data, colWidths=widths, repeatRows=header_rows, hAlign=align)
        commands = [
            ('GRID', (0, 0), (-1, -1), .28, line),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 1.4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.4),
            ('FONTNAME', (0, 0), (-1, -1), 'QMS-Regular'),
            ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ]
        if header_rows:
            commands.extend([
                ('BACKGROUND', (0, 0), (-1, header_rows - 1), pale_blue),
                ('FONTNAME', (0, 0), (-1, header_rows - 1), 'QMS-Bold'),
                ('ALIGN', (0, 0), (-1, header_rows - 1), 'CENTER'),
            ])
        table.setStyle(TableStyle(commands))
        return table

    def observation_cell(item):
        observations = item.get('observations', [])
        if not observations:
            return p('-')

        # The Observation column is 227 pt wide, but its parent cell has
        # 2.5 pt of padding on each side. Nested tables must stay narrower
        # than the available 222 pt so their right borders cannot intrude
        # into the Remarks column. Center them with a small inner gutter.
        observation_width = 216

        # HV / IR / Ground Continuity uses five modules in a true four-column
        # matrix.  Keep both shift checks in one compact eight-column block so
        # the PDF matches the entry and read-only screens without changing the
        # stored field names used by existing records.
        if item.get('id') == 'R183' and len(observations) == 2:
            headings = ['Module No.', 'IR', 'HV', 'GND']
            data = [
                [p(observations[0].get('label', 'First check'), small_center_style)] + [''] * 3 +
                [p(observations[1].get('label', 'Second check'), small_center_style)] + [''] * 3,
                [p(heading, small_center_style) for heading in headings * 2],
            ]
            for module_number in range(1, 6):
                row = []
                for observation in observations:
                    values = observation.get('values', {})
                    for heading in headings:
                        field = f'{module_number}. {heading}'
                        row.append(p(display_observation_value(item.get('parameter'), field,
                                                               values.get(field, '-')),
                                     small_center_style))
                data.append(row)
            table = compact_table(data, [27] * 8, header_rows=2, align='CENTER', font_size=4.25)
            table.setStyle(TableStyle([
                ('SPAN', (0, 0), (3, 0)),
                ('SPAN', (4, 0), (7, 0)),
                ('LINEBEFORE', (4, 0), (4, -1), .65, navy_2),
            ]))
            return table

        # Keep the four laminators as columns, but group the recipe rows into
        # three clearly labelled chamber tables. Field names stay unchanged so
        # existing drafts and approved reports remain compatible.
        if len(observations) == 4 and all(str(o.get('label', '')).startswith('Laminator ') for o in observations):
            fields = list(observations[0].get('values', {}).keys())
            chamber_tables = []
            for chamber in ('Chamber 1', 'Chamber 2', 'Chamber 3'):
                prefix = f'{chamber} · '
                chamber_fields = [field for field in fields if field.startswith(prefix)]
                if not chamber_fields:
                    continue
                chamber_tables.append(p(chamber, small_center_style))
                data = [[p('Parameter', small_center_style)] +
                        [p(o.get('label', ''), small_center_style) for o in observations]]
                for field in chamber_fields:
                    data.append([p(field.removeprefix(prefix), small_style)] + [
                        p(display_observation_value(item.get('parameter'), field,
                                                    o.get('values', {}).get(field, '-')),
                          small_center_style) for o in observations
                    ])
                chamber_tables.append(compact_table(data, [76, 35, 35, 35, 35], header_rows=1,
                                                    align='CENTER', font_size=4.4))
                chamber_tables.append(Spacer(1, 3))
            return chamber_tables[:-1] if chamber_tables else p('-')

        first_values = observations[0].get('values', {})
        fields = list(first_values.keys())
        stringer_width = all(field.startswith('Stringer ') and ' - ' in field for field in fields)
        if len(observations) == 1 and stringer_width and fields:
            # Half-cut measurements use Stringer / A-top-middle-bottom /
            # B-top-middle-bottom, matching the controlled checksheet blocks.
            if any(' - A top' in field for field in fields):
                headings = ['Stringer', 'A top', 'A middle', 'A bottom', 'B top', 'B middle', 'B bottom']
                data = [[p(h, small_center_style) for h in headings]]
                for number in range(1, 4):
                    values = first_values
                    data.append([p(number, small_center_style)] + [
                        p(display_observation_value(item.get('parameter'), f'Stringer {number} - {key}',
                                                    values.get(f'Stringer {number} - {key}', '-')),
                          small_center_style)
                        for key in ['A top', 'A middle', 'A bottom', 'B top', 'B middle', 'B bottom']
                    ])
                return compact_table(data, [24, 32, 32, 32, 32, 32, 32], header_rows=1,
                                     align='CENTER', font_size=4.35)

            if any('Track A' in field for field in fields):
                data = [[p('Stringer', small_center_style), p('Track A', small_center_style),
                         p('Track B', small_center_style)]]
                for number in range(1, 4):
                    data.append([
                        p(number, small_center_style),
                        p(display_observation_value(item.get('parameter'), f'Stringer {number} - Track A',
                                                    first_values.get(f'Stringer {number} - Track A', '-')),
                          small_center_style),
                        p(display_observation_value(item.get('parameter'), f'Stringer {number} - Track B',
                                                    first_values.get(f'Stringer {number} - Track B', '-')),
                          small_center_style),
                    ])
                return compact_table(data, [44, 86, 86], header_rows=1, align='CENTER', font_size=4.5)

        # Generic checks remain side-by-side. The reviewed controlled PDF must
        # not print the words "Observation", "First check" or "Second check".
        columns = min(len(observations), 4)
        if len(observations) > 1:
            widths = [observation_width / columns] * columns
            values = []
            for observation in observations:
                parts = [
                    clean(display_observation_value(item.get('parameter'), field, value))
                    if str(field).strip().casefold() == 'observation'
                    else label_value(field, display_observation_value(item.get('parameter'), field, value))
                    for field, value in observation.get('values', {}).items()
                ]
                values.append(rich(['<br/>'.join(parts)], small_style))
            return compact_table([values], widths, align='CENTER', font_size=4.6)

        values = observations[0].get('values', {})
        if len(values) == 1:
            field, value = next(iter(values.items()))
            if str(field).strip().casefold() == 'observation':
                return p(display_observation_value(item.get('parameter'), field, value), body_style)
            return rich([label_value(field, display_observation_value(item.get('parameter'), field, value))],
                        body_style)
        data = [[p(field, small_style), p(display_observation_value(item.get('parameter'), field, value), small_style)]
                for field, value in values.items()]
        return compact_table(data, [86, 130], align='CENTER', font_size=4.6)

    def controlled_header(payload, report):
        doc = payload.get('document', {})
        logo_path = ROOT / 'static' / 'company-logo.svg'
        logo = p('YOUR COMPANY', bold_center_style)
        header = Table([
            [logo, p('Your Company', title_style), p('Document No.', bold_style), p(doc.get('document_no', '-'), bold_style)],
            ['', p('Quality Department', bold_center_style), p('Issue date', bold_style), p(doc.get('issue_date', '-'))],
            ['', p('In-Process Quality Audit Report', title_style), p('Revision No.', bold_style), p(doc.get('revision_no', '-'))],
            ['', p('Controlled IPQC checksheet', bold_center_style), p('Revision date', bold_style), p(doc.get('revision_date', '-'))],
            ['', p('Controlled report', bold_center_style), p('Copy', bold_style), p(doc.get('copy', '-'))],
        ], colWidths=[105, 354, 91, 246])
        header.setStyle(TableStyle([
            ('SPAN', (0, 0), (0, 4)),
            ('GRID', (0, 0), (-1, -1), .55, navy_2),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 4), 'CENTER'),
            ('BACKGROUND', (2, 0), (2, 4), pale_blue),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))

        metadata = payload.get('metadata', {})
        info = Table([[
            p('Date', bold_style), p(report['day'], body_style),
            p('Production Order', bold_style), p(metadata.get('production_order', '-'), body_style),
            p('Module Type', bold_style), p(metadata.get('module_type', '-'), body_style),
            p('Line', bold_style), p(report['line'], body_style),
            p('Shift', bold_style), p(report['shift'], bold_center_style),
        ]], colWidths=[36, 63, 79, 92, 67, 246, 28, 70, 31, 84])
        info.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .45, line),
            ('BACKGROUND', (0, 0), (0, 0), pale_blue),
            ('BACKGROUND', (2, 0), (2, 0), pale_blue),
            ('BACKGROUND', (4, 0), (4, 0), pale_blue),
            ('BACKGROUND', (6, 0), (6, 0), pale_blue),
            ('BACKGROUND', (8, 0), (8, 0), pale_blue),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        customer = Table([[
            p('Customer name', bold_style), p(metadata.get('customer_name') or '-', body_style),
        ]], colWidths=[99, 697])
        customer.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .45, line),
            ('BACKGROUND', (0, 0), (0, 0), pale_blue),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        status_strip = Table([[
            rich([label_value('Inspection time', report['inspection_time'] + ' IST')], small_style),
            rich([label_value('Status', report['status'])], small_style),
        ]], colWidths=[398, 398])
        status_strip.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .35, line),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F7F9FC')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        return [header, info, customer, status_strip, Spacer(1, 5)]

    def audit_table(payload):
        data = [[p('Sr. No.', table_header_style), p('Stage', table_header_style),
                 p('Parameter', table_header_style), p('Acceptance Criteria', table_header_style),
                 p('Frequency', table_header_style), p('Recorded values', table_header_style),
                 p('Remarks', table_header_style)]]
        row_sections = []
        for section_index, section in enumerate(payload.get('sections', [])):
            items = section.get('items', [])
            for item_index, item in enumerate(items):
                serial = section.get('number', item.get('serial', '-')) if item_index == 0 else ''
                stage = section.get('name', item.get('stage', '-')) if item_index == 0 else ''
                data.append([
                    p(serial or ' ', bold_center_style), p(stage or ' ', bold_style), p(item.get('parameter', '-')),
                    p(item.get('acceptance', '-')), p(item.get('frequency', '-'), body_center_style),
                    observation_cell(item), p(item.get('remarks', '-')),
                ])
                row_sections.append(section_index)
        table = LongTable(data, colWidths=[32, 88, 151, 145, 66, 227, 87], repeatRows=1,
                          splitByRow=1, hAlign='CENTER')
        commands = [
            ('BACKGROUND', (0, 0), (-1, 0), navy),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('GRID', (0, 0), (-1, -1), .38, line),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2.5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2.5),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]
        for row_index, section_index in enumerate(row_sections, 1):
            if section_index % 2:
                commands.append(('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#F6F8FB')))
            if row_index == 1 or row_sections[row_index - 2] != section_index:
                commands.extend([
                    ('LINEABOVE', (0, row_index), (-1, row_index), 1.35, navy),
                    ('BACKGROUND', (0, row_index), (1, row_index), pale_orange),
                ])
            # A dark full-width rule closes each inspection checkpoint,
            # including long Stringer, Encapsulant (EPE), and Laminator stages.
            if row_index == len(row_sections) or row_sections[row_index] != section_index:
                commands.append(('LINEBELOW', (0, row_index), (-1, row_index), 1.35, navy))
        table.setStyle(TableStyle(commands))
        return table

    def signatures(report):
        history = list(db().execute(
            'SELECT h.*,u.name FROM history h JOIN users u ON h.actor=u.id '
            'WHERE h.report=? ORDER BY h.id', (report['id'],)))
        submitted = next((h for h in reversed(history) if h['action'] == 'Submitted'), None)
        reviewed = next((h for h in reversed(history) if h['action'] in REVIEW_OUTCOMES), None)
        if report['status'] not in REVIEW_OUTCOMES:
            reviewed = None
        reviewed_comment = reviewed['comment'] if reviewed and reviewed['comment'] else '-'
        operator_block = rich([
            '<b>(Checked by)</b><br/>',
            label_value('Name', report['operator_name']), '<br/>',
            label_value('Sign', 'Authenticated electronic submission'), '<br/>',
            label_value('Date / time', submitted['time'] if submitted else report['updated']),
        ], body_style)
        reviewer_block = rich([
            '<b>(Reviewed by)</b><br/>',
            label_value('Name', reviewed['name'] if reviewed else report['approver_name'] or '-'), '<br/>',
            label_value('Sign', report['status'] if report['status'] in REVIEW_OUTCOMES else 'Awaiting review'), '<br/>',
            label_value('Date / time', reviewed['time'] if reviewed else '-'), '<br/>',
            label_value('Comment', reviewed_comment),
        ], body_style)
        remarks = rich([label_value('Operator remarks', report['remarks'] or '-')], body_style)
        table = Table([[remarks, ''], [operator_block, reviewer_block]], colWidths=[398, 398])
        table.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('GRID', (0, 0), (-1, -1), .55, navy_2),
            ('BACKGROUND', (0, 0), (1, 0), pale_blue),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return table

    def ctq_header(payload, report, definition):
        doc = payload.get('document', definition.get('document', {}))
        logo_path = ROOT / 'static' / 'company-logo.svg'
        logo = p('YOUR COMPANY', bold_center_style)
        header = Table([
            [logo, p('Your Company', title_style), p('Document No.', bold_style), p(doc.get('document_no', '-'), bold_style)],
            ['', p('Quality Department', bold_center_style), p('Issue date', bold_style), p(doc.get('issue_date', '-'))],
            ['', p(doc.get('title', definition['name']), title_style), p('Revision No.', bold_style), p(doc.get('revision_no', '-'))],
            ['', p('Controlled report', bold_center_style), p('Revision date', bold_style), p(doc.get('revision_date', '-'))],
        ], colWidths=[105, 354, 91, 246])
        header.setStyle(TableStyle([
            ('SPAN', (0, 0), (0, 3)), ('GRID', (0, 0), (-1, -1), .55, navy_2),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (0, 0), (0, 3), 'CENTER'),
            ('BACKGROUND', (2, 0), (2, 3), pale_blue),
            ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        info = Table([[
            p('Date', bold_style), p(report['day']), p('Shift', bold_style), p(report['shift'], bold_center_style),
            p('Line', bold_style), p(report['line']), p('Machine / Location', bold_style), p(report['machine']),
        ], [
            p('Inspection Time', bold_style), p(report['inspection_time'] + ' IST'),
            p('Status', bold_style), p(report['status']), p('Result', bold_style), p(report['result']),
            p('Assigned Incharge', bold_style), p(report['approver_name'] or '-'),
        ]], colWidths=[62, 135, 49, 70, 42, 100, 92, 246])
        info.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .4, line), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (0, -1), pale_blue), ('BACKGROUND', (2, 0), (2, -1), pale_blue),
            ('BACKGROUND', (4, 0), (4, -1), pale_blue), ('BACKGROUND', (6, 0), (6, -1), pale_blue),
            ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        acceptance = Table([[p('Acceptance Criteria', bold_style), p(definition.get('acceptance', '-'))]], colWidths=[120, 676])
        acceptance.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .45, navy_2), ('BACKGROUND', (0, 0), (0, 0), pale_orange),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        return [header, info, acceptance, Spacer(1, 6)]

    def ctq_table(data, widths, header_rows=1, font_size=5.2):
        table = LongTable(data, colWidths=widths, repeatRows=header_rows, splitByRow=1, hAlign='CENTER')
        commands = [
            ('GRID', (0, 0), (-1, -1), .4, line), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('FONTNAME', (0, 0), (-1, -1), 'QMS-Regular'), ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ]
        if header_rows:
            commands.extend([('BACKGROUND', (0, 0), (-1, header_rows - 1), navy),
                             ('TEXTCOLOR', (0, 0), (-1, header_rows - 1), white),
                             ('FONTNAME', (0, 0), (-1, header_rows - 1), 'QMS-Bold'),
                             ('ALIGN', (0, 0), (-1, header_rows - 1), 'CENTER')])
        table.setStyle(TableStyle(commands))
        return table

    def ribbon_track_table(section, track, values, calculated):
        side_headings = ['Sl No.'] + [f'Peak {peak} (N)' for peak in range(1, section['peaks'] + 1)] + ['Average (N)', 'N/mm']
        data = [[p(f"Stringer {track['label']}", table_header_style), p('Front', table_header_style)] + [''] * 9 +
                [p('Back', table_header_style)] + [''] * 9,
                [''] + [p(label, table_header_style) for label in side_headings] * 2]
        low_cells = []
        nr_cells = []
        for position in range(1, section['count'] + 1):
            row = ['']
            for side_index, side in enumerate(section['sides']):
                row.append(p(position, small_center_style))
                for peak in range(1, section['peaks'] + 1):
                    column = (2 if side_index == 0 else 12) + peak - 1
                    if ribbon_not_required(track, position, peak):
                        row.append(p('NR', small_center_style))
                        nr_cells.append((column, position + 1))
                        continue
                    key = ribbon_peak_key(track['key'], side['key'], position, peak)
                    raw = values.get(key, '')
                    row.append(p(raw or '-', small_center_style))
                    if raw:
                        try:
                            if float(raw) < section['minimum']:
                                low_cells.append((column, position + 1))
                        except (TypeError, ValueError):
                            pass
                prefix = ribbon_calculation_key(track['key'], side['key'], position, '')[:-1]
                row.extend([
                    p(calculated.get(prefix + '_average', '-'), small_center_style),
                    p(calculated.get(prefix + '_n_per_mm', '-'), small_center_style),
                ])
            data.append(row)
        side_widths = [24] + [35] * section['peaks'] + [56, 57]
        table = LongTable(data, colWidths=[32] + side_widths * 2, repeatRows=2,
                          splitByRow=1, hAlign='CENTER')
        commands = [
            ('SPAN', (0, 0), (0, -1)),
            ('SPAN', (1, 0), (10, 0)), ('SPAN', (11, 0), (20, 0)),
            ('BACKGROUND', (0, 0), (-1, 1), navy), ('TEXTCOLOR', (0, 0), (-1, 1), white),
            ('FONTNAME', (0, 0), (-1, 1), 'QMS-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 4.0),
            ('GRID', (0, 0), (-1, -1), .35, line), ('BOX', (0, 0), (-1, -1), 1.15, navy),
            ('LINEBEFORE', (11, 0), (11, -1), 1.15, navy),
            ('BACKGROUND', (9, 2), (10, -1), pale_blue), ('BACKGROUND', (19, 2), (20, -1), pale_blue),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 1.2), ('RIGHTPADDING', (0, 0), (-1, -1), 1.2),
            ('TOPPADDING', (0, 0), (-1, -1), 2.0), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.0),
        ]
        for column, row in nr_cells:
            commands.extend([('BACKGROUND', (column, row), (column, row), colors.HexColor('#E9EDF2')),
                             ('TEXTCOLOR', (column, row), (column, row), colors.HexColor('#667085'))])
        for column, row in low_cells:
            commands.extend([('BACKGROUND', (column, row), (column, row), colors.HexColor('#FDE3E5')),
                             ('TEXTCOLOR', (column, row), (column, row), colors.HexColor('#A51F2A')),
                             ('FONTNAME', (column, row), (column, row), 'QMS-Bold')])
        table.setStyle(TableStyle(commands))
        return table

    def ribbon_chart(section, track, side, calculated, width=390, height=62):
        drawing = Drawing(width, height)
        left, right, bottom, top = 25, 7, 13, 15
        chart_width, chart_height = width - left - right, height - bottom - top
        averages = []
        for position in range(1, section['count'] + 1):
            key = ribbon_calculation_key(track['key'], side['key'], position, 'average')
            try:
                averages.append(float(calculated[key]))
            except (KeyError, TypeError, ValueError):
                averages.append(None)
        entered = [value for value in averages if value is not None]
        maximum = max([1.0, section['minimum'] * 1.2, *(entered or [0])]) * 1.08
        drawing.add(Rect(left, bottom, chart_width, chart_height, fillColor=colors.white,
                         strokeColor=line, strokeWidth=.45))
        for fraction in (0, .5, 1):
            y = bottom + chart_height * fraction
            drawing.add(Line(left, y, left + chart_width, y, strokeColor=colors.HexColor('#D9E1EA'), strokeWidth=.35))
        threshold_y = bottom + chart_height * section['minimum'] / maximum
        threshold = Line(left, threshold_y, left + chart_width, threshold_y,
                         strokeColor=orange, strokeWidth=.8)
        threshold.strokeDashArray = [3, 2]
        drawing.add(threshold)
        points = []
        for index, value in enumerate(averages):
            if value is None:
                continue
            x = left + chart_width * index / max(1, section['count'] - 1)
            y = bottom + chart_height * value / maximum
            points.append((x, y))
        if len(points) > 1:
            drawing.add(PolyLine(points, strokeColor=blue, strokeWidth=1.05, fillColor=None))
        for x, y in points:
            drawing.add(Circle(x, y, 1.25, fillColor=blue, strokeColor=blue))
        drawing.add(String(0, height - 8, f"Stringer {track['label']} · {side['label']}",
                           fontName='QMS-Bold', fontSize=5.6, fillColor=navy))
        drawing.add(String(0, bottom + chart_height - 2, display_number(maximum),
                           fontName='QMS-Regular', fontSize=4.2, fillColor=text_color))
        drawing.add(String(0, bottom - 1, '0', fontName='QMS-Regular', fontSize=4.2, fillColor=text_color))
        drawing.add(String(left + chart_width - 22, threshold_y + 2, f"≥ {section['minimum']} N",
                           fontName='QMS-Bold', fontSize=4.2, fillColor=orange))
        for position in (1, 4, 8, 12, 16):
            x = left + chart_width * (position - 1) / max(1, section['count'] - 1)
            drawing.add(String(x - 2, 3, str(position), fontName='QMS-Regular', fontSize=4.1,
                               fillColor=text_color))
        return drawing

    def ctq_report_story(payload, report, definition):
        values = payload.get('values', {})
        calculated = payload.get('calculated', {})
        parts = ctq_header(payload, report, definition)
        for section in definition.get('sections', []):
            section_parts = [p(section['title'], section_style), Spacer(1, 3)]
            section_type = section['type']
            if section_type == 'fields':
                pairs = [(field['label'] + (f" ({field['unit']})" if field.get('unit') else ''), values.get(field['key'], '-'))
                         for field in section['fields']]
                data = []
                for offset in range(0, len(pairs), 2):
                    row = pairs[offset:offset + 2]
                    if len(row) == 1:
                        row.append(('', ''))
                    data.append([p(row[0][0], bold_style), p(row[0][1]), p(row[1][0], bold_style), p(row[1][1])])
                table = Table(data, colWidths=[155, 243, 155, 243])
                table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), .35, line), ('BACKGROUND', (0, 0), (0, -1), pale_blue),
                    ('BACKGROUND', (2, 0), (2, -1), pale_blue), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))
                section_parts.append(table)
            elif section_type == 'matrix':
                data = [[p('Parameter', table_header_style)] + [p(column['label'], table_header_style) for column in section['columns']]]
                for row in section['rows']:
                    row_label = row['label'] + (f" ({row['unit']})" if row.get('unit') else '')
                    cells = [p(row_label, bold_style)]
                    for column in section['columns']:
                        applies = not row.get('columns') or column['key'] in row['columns']
                        cells.append(p(values.get(f"{column['key']}_{row['key']}", '-') if applies else 'Not applicable', body_center_style))
                    data.append(cells)
                column_width = (796 - 300) / len(section['columns'])
                section_parts.append(ctq_table(data, [300] + [column_width] * len(section['columns'])))
            elif section_type == 'gel_samples':
                data = [[p(label, table_header_style) for label in ['Sample', 'W1 EVA (g)', 'W2 Filter (g)', 'W3 Residual (g)', 'Dried W3-W2 (g)', 'Gel (%)', 'Remarks']]]
                for sample in range(1, section['count'] + 1):
                    data.append([p(f'Sample {sample}', bold_style), p(values.get(f'sample_{sample}_w1', '-')), p(values.get(f'sample_{sample}_w2', '-')),
                                 p(values.get(f'sample_{sample}_w3', '-')), p(calculated.get(f'sample_{sample}_dried', '-')),
                                 p(calculated.get(f'sample_{sample}_gel', '-')), p(values.get(f'sample_{sample}_remarks', '-'))])
                data.append([p('Average Gel Content', bold_style), '', '', '', '', p(calculated.get('average_gel', '-'), bold_center_style), p(calculated.get('overall_result', 'Pending'), bold_center_style)])
                table = ctq_table(data, [72, 92, 92, 92, 105, 82, 261])
                table.setStyle(TableStyle([('SPAN', (0, -1), (4, -1)), ('BACKGROUND', (0, -1), (-1, -1), pale_blue)]))
                section_parts.append(table)
            elif section_type == 'ribbon_peel_matrix':
                parts.extend(section_parts)
                for track in section['tracks']:
                    track_heading = Table([[
                        p(f"Stringer {track['label']}", bold_style),
                        p(f"Controlled ribbon width: {track['ribbon_width_mm']} mm", body_center_style),
                        p(f"Criterion: every peak ≥ {section['minimum']} N", bold_center_style),
                    ]], colWidths=[190, 286, 320])
                    track_heading.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), pale_orange), ('BOX', (0, 0), (-1, -1), .55, navy_2),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 3),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ]))
                    parts.append(KeepTogether([
                        track_heading, ribbon_track_table(section, track, values, calculated), Spacer(1, 6)
                    ]))
                parts.extend([PageBreak(), p('Front / Back average peak trends', section_style), Spacer(1, 4)])
                charts = []
                for track in section['tracks']:
                    charts.append([
                        ribbon_chart(section, track, section['sides'][0], calculated),
                        ribbon_chart(section, track, section['sides'][1], calculated),
                    ])
                chart_table = Table(charts, colWidths=[398, 398], rowHeights=[66] * len(charts))
                chart_table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), .35, line), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))
                parts.extend([chart_table, Spacer(1, 7)])
                continue
            elif section_type == 'adhesion_readings':
                headings = ['Test Interface'] + [f'Reading {index} (N/cm)' for index in range(1, section['count'] + 1)] + ['Average', 'Criterion']
                data = [[p(label, table_header_style) for label in headings]]
                for group in section['groups']:
                    data.append([p(group['label'], bold_style)] + [p(values.get(f"{group['key']}_{index}", '-'), body_center_style) for index in range(1, section['count'] + 1)] +
                                [p(calculated.get(f"{group['key']}_average", '-'), bold_center_style), p(f"≥ {group['minimum']} N/cm", bold_center_style)])
                section_parts.append(ctq_table(data, [220, 82, 82, 82, 82, 96, 152]))
            elif section_type == 'busbar_matrix':
                headings = ['Interconnector Type'] + [f'R{index}' for index in range(1, section['count'] + 1)] + ['Avg (N)', 'N/mm<br/>(Avg ÷ 0.24)']
                data = [[p(label, table_header_style) for label in headings]]
                for row in section['rows']:
                    data.append([p(row['label'], small_style)] + [p(values.get(f"{row['key']}_r{index}", '-'), small_center_style) for index in range(1, section['count'] + 1)] +
                                [p(calculated.get(f"{row['key']}_average", '-'), small_center_style), p(calculated.get(f"{row['key']}_n_per_mm", '-'), small_center_style)])
                section_parts.append(ctq_table(data, [136] + [31] * section['count'] + [76, 88], font_size=4.3))
            elif section_type == 'empty':
                table = Table([[p('Controlled sheet is blank', bold_style), p(section['message'])]], colWidths=[170, 626])
                table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .45, line), ('BACKGROUND', (0, 0), (0, 0), pale_orange),
                                           ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 7),
                                           ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 8),
                                           ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
                section_parts.append(table)
            section_parts.append(Spacer(1, 7))
            parts.append(KeepTogether(section_parts))
        parts.append(signatures(report))
        return parts

    story=[]
    if context:
        story += [p(title, cover_title_style), Spacer(1, 5), p(context['subtitle'], section_style),
                  p(context['scope']), Spacer(1, 10)]
        summary=[[p('Report type', table_header_style),p('Shift', table_header_style),
                  p('Approved', table_header_style),p('Other / pending', table_header_style)]]
        visible=context['visible']
        for kind in context['kinds']:
            for shift in context['shifts']:
                matching=[r for r in visible if r['kind']==kind and r['shift']==shift]
                summary.append([p(FORMS[kind][0]),p(shift),p(sum(r['status'] in APPROVED for r in matching)),p(sum(r['status'] not in APPROVED for r in matching))])
        table=Table(summary,colWidths=[360,90,170,176],repeatRows=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),('TEXTCOLOR',(0,0),(-1,0),white),
                                   ('GRID',(0,0),(-1,-1),.4,line),('VALIGN',(0,0),(-1,-1),'TOP'),
                                   ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                                   ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story += [table,Spacer(1,8),p('Approved records are included. Pending, returned, and draft records appear only in this summary.')]
    for report_index,r in enumerate(reports):
        if context or report_index: story.append(PageBreak())
        payload=refreshed_ctq_payload(r['kind'], json.loads(r['payload']))
        if payload.get('format') == 'ipqc-v1':
            story.extend(controlled_header(payload, r))
            story.extend([audit_table(payload), Spacer(1, 6), signatures(r)])
        elif payload.get('format') == 'ctq-v1' and r['kind'] in CTQ_DEF:
            story.extend(ctq_report_story(payload, r, CTQ_DEF[r['kind']]))
        else:
            story += [p(FORMS[r['kind']][0], cover_title_style),
                      p('Form version: '+payload.get('form_version','STARTER-1'))]
            for index,row in enumerate(payload.get('rows',[]),1):
                story.append(p(f'Reading {index}', section_style))
                data=[[p(label),p(row.get(label,''))] for label in [*payload.get('labels',[]),'Result']]
                table=Table(data,colWidths=[190,561],splitByRow=1)
                table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,line),('BACKGROUND',(0,0),(0,-1),pale_blue),
                                           ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),
                                           ('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),
                                           ('BOTTOMPADDING',(0,0),(-1,-1),5)]));story.extend([table,Spacer(1,6)])
    if not reports:
        story += [Spacer(1,18),p('No approved records matched the selected filters.',section_style)]
    out=io.BytesIO()
    ipqc_only = bool(reports) and all(report['kind'] == 'ipqc' for report in reports)
    ribbon_only = bool(reports) and all(report['kind'] == 'ribbon_peel' for report in reports)
    def footer(canvas,doc):
        page_width, page_height = landscape(A4)
        canvas.saveState()
        canvas.setStrokeColor(line);canvas.line(18,21,page_width-18,21)
        canvas.setFont('QMS-Regular',6.2);canvas.setFillColor(colors.HexColor('#526174'))
        footer_text = (f"{IPQC_DEF['document_no']} | Control Copy" if ipqc_only else
                       'DEMO/QAD/FM/L3/007 | Control Copy' if ribbon_only else
                       'Company QMS | Controlled quality report')
        canvas.drawString(18,10,footer_text+' | Generated '+now())
        canvas.drawRightString(page_width-18,10,f'Page {doc.page}')
        if doc.page > 1:
            canvas.setFont('QMS-Bold',5.8);canvas.setFillColor(navy)
            report_title = ('In-Process Quality Audit Report' if ipqc_only else
                            'Cell To Ribbon Peel Test Report' if ribbon_only else 'Controlled Quality Report')
            canvas.drawString(18,page_height-12,'Your Company | '+report_title)
            canvas.drawRightString(page_width-18,page_height-12,
                                   f"Revision {IPQC_DEF['revision_no']}" if ipqc_only else
                                   'Revision 0' if ribbon_only else 'Company QMS')
            canvas.setStrokeColor(pale_blue);canvas.line(18,page_height-16,page_width-18,page_height-16)
        canvas.restoreState()
    SimpleDocTemplate(out,pagesize=landscape(A4),rightMargin=18,leftMargin=18,topMargin=20,bottomMargin=29,
                      title=title,author='Company QMS').build(story,onFirstPage=footer,onLaterPages=footer)
    out.seek(0)
    return out

@app.get('/report/<int:rid>.pdf')
@require()
def report_pdf(rid):
    report=get_report(rid)
    report_name = FORMS[report['kind']][0]
    output=make_pdf([report],f'QUALITY REPORT - {report_name}')
    safe_name = re.sub(r'[^A-Za-z0-9]+', '-', report_name).strip('-')
    return send_file(output,mimetype='application/pdf',as_attachment=True,
                     download_name=f'{safe_name}-{report["day"]}-Shift-{report["shift"]}.pdf')

@app.get('/daily.pdf')
@require('admin','incharge')
def daily_pdf():
    if is_superuser():
        abort(403)
    day=request.args.get('day','')
    try: datetime.strptime(day,'%Y-%m-%d')
    except ValueError: abort(400,'Select a production date.')
    shift=request.args.get('shift',''); kind=request.args.get('kind',''); line=request.args.get('line','')
    module=request.args.get('module','').lower()
    if shift and shift not in ['A','B','C']: abort(400)
    if kind and kind not in FORMS: abort(400)
    if module and module not in MODULE_KINDS: abort(400)
    if kind and module and kind not in MODULE_KINDS[module]: abort(400)
    scoped_kinds = MODULE_KINDS[module] if module and not kind else None
    reports=selected_reports(day,shift,kind,line,kinds=scoped_kinds)
    approved_reports=[r for r in reports if r['status'] in APPROVED]
    context={'subtitle':f'Production date: {day} | Shift: {shift or "A + B + C"} | Line: {line or "All visible lines"}',
             'scope':'Access scope: '+('All company reports' if g.user['role']=='admin' else 'Reports assigned to '+g.user['name']),
             'visible':reports,'kinds':[kind] if kind else list(scoped_kinds or FORMS),'shifts':[shift] if shift else ['A','B','C']}
    output=make_pdf(approved_reports,'QUALITY DAILY REPORT',context)
    return send_file(output,mimetype='application/pdf',as_attachment=True,download_name=f'Quality-{day}-{shift or "ABC"}.pdf')

init_db()
if __name__=='__main__':
    from waitress import serve
    bind=os.environ.get('QUALITYSYSTEM_BIND','0.0.0.0'); port=int(os.environ.get('PORT',os.environ.get('QUALITYSYSTEM_PORT','8080')))
    print(f'Company QMS listening on {bind}:{port} (Ctrl+C to stop)')
    serve(app,host=bind,port=port)
