"""Account appearance persistence and isolation checks on temporary data."""
import importlib.util
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as data:
    os.environ['QUALITYSYSTEM_DATA'] = data
    spec = importlib.util.spec_from_file_location('theme_app', Path(__file__).resolve().parents[1] / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config.update(TESTING=True)
    module.init_db()  # Existing databases can safely run the migration again.
    client = module.app.test_client()
    def csrf():
        with client.session_transaction() as session:
            return session['csrf']
    def login(employee):
        client.get('/login')
        assert client.post('/login', data={'csrf': csrf(), 'employee': employee, 'password': 'Demo123'}).status_code == 302
    assert client.get('/appearance').status_code == 302
    login('OP100')
    assert b'data-appearance="midnight"' in client.get('/').data
    assert client.post('/appearance', data={'appearance': 'plum'}).status_code == 400
    assert client.post('/appearance', data={'csrf': csrf(), 'appearance': 'invalid'}).status_code == 400
    assert client.post('/appearance', data={'csrf': csrf(), 'appearance': 'plum', 'id': '2'}).status_code == 302
    with module.app.app_context():
        row = module.db().execute("SELECT appearance FROM users WHERE employee='OP100'").fetchone()
        assert tuple(row) == ('plum',)
        assert module.db().execute("SELECT appearance FROM users WHERE employee='IC100'").fetchone()[0] == 'midnight'
    second_device = module.app.test_client()
    second_device.get('/login')
    with second_device.session_transaction() as session:
        token = session['csrf']
    second_device.post('/login', data={'csrf': token, 'employee': 'OP100', 'password': 'Demo123'})
    assert b'data-appearance="plum"' in second_device.get('/').data
    assert b'data-theme="light"' in second_device.get('/').data
    assert client.post('/appearance', data={'csrf': csrf(), 'appearance': 'midnight'}).status_code == 302
    assert b'data-appearance="midnight"' in client.get('/').data
    client.post('/logout', data={'csrf': csrf()})
    login('0001')
    assert client.get('/appearance').status_code == 200
    print('PASS: appearance persistence across devices, account isolation, validation, CSRF, anonymous protection, superuser access and repeatable migration')
