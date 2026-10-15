"""Keep the separate marketing document outside the application's login flow."""
import importlib.util
import os
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as data:
    os.environ['QUALITYSYSTEM_DATA']=data
    spec=importlib.util.spec_from_file_location('landing_app',ROOT/'app.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.app.config['TESTING']=True;c=module.app.test_client()
    r=c.get('/');assert r.status_code==302 and r.headers['Location'].endswith('/login')
    assert c.get('/overview').status_code==404
    page=c.get('/login');assert page.status_code==200 and b'login-shell' in page.data and b'Less paperwork.' not in page.data
    assert c.get('/static/login-background.webp').status_code==200
    doc=(ROOT/'marketing/SolarQMS-Landing.html').read_text()
    assert 'Less paperwork.' in doc and 'https://qualitysystem.onrender.com/login' in doc
    assert '{{' not in doc and '{%' not in doc and '/static/' not in doc
    c.get('/login')
    with c.session_transaction() as session:csrf=session['csrf']
    assert c.post('/login',data={'csrf':csrf,'employee':'OP100','password':'Demo123'}).status_code==302
    assert b'data-dashboard-module' in c.get('/').data
    print('PASS: direct login, no marketing app route, login photograph, separate self-contained HTML and signed-in dashboard')
