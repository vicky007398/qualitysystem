"""Public product overview and authenticated workflow boundaries."""
import importlib.util
import os
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as data:
    os.environ['QUALITYSYSTEM_DATA'] = data
    spec = importlib.util.spec_from_file_location('landing_app', Path(__file__).resolve().parents[1] / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config['TESTING'] = True
    c = module.app.test_client()
    for path in ['/', '/overview']:
        r = c.get(path)
        assert r.status_code == 200 and b'Less paperwork.' in r.data
        assert b'landing.css' in r.data and b'/login' in r.data
    for path in ['/new/ipqc', '/new/gel', '/appearance', '/report/1', '/users']:
        assert c.get(path).status_code == 302, path
    for name in ['dashboard', 'ipqc', 'gel']:
        r = c.get('/static/product/' + name + '.webp')
        assert r.status_code == 200 and r.mimetype == 'image/webp'
    c.get('/login')
    with c.session_transaction() as session:
        csrf = session['csrf']
    assert c.post('/login', data={'csrf': csrf, 'employee': 'OP100', 'password': 'Demo123'}).status_code == 302
    dashboard = c.get('/')
    assert dashboard.status_code == 200 and b'data-dashboard-module' in dashboard.data
    assert b'Less paperwork.' not in dashboard.data
    assert b'Go to dashboard' in c.get('/overview').data
    print('PASS: public landing and screenshots, protected app routes, operator dashboard and overview navigation')
