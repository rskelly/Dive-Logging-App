import gc
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

PEOPLE = [{'id': 7, 'first_name': 'Jackie', 'last_name': 'Doe'},
          {'id': 9, 'first_name': 'Stacey', 'last_name': 'Ray'}]


def _model(brand, model, kind):
    return {'id': 1, 'brand_name': brand, 'model_name': model, 'equipment_type': {'id': 1, 'name': kind}}


INSTRUMENTS = [
    {'id': 101, 'name': 'Main camera', 'serial_number': '4830543', 'retired': None, 'model': _model('GoPro', 'Hero4', 'Camera')},
    {'id': 102, 'name': None, 'serial_number': '123456', 'retired': '2024-01-01', 'model': _model('ROWETech', 'DVL', 'DVL')},
    {'id': 103, 'name': 'Compass', 'serial_number': '12345', 'retired': None, 'model': _model('Generic', 'Compass', 'Compass')},
]

PLATFORMS = [
    {'id': 201, 'name': 'John P. Tully', 'serial_number': None, 'retired': None, 'model': _model('CCGS', 'Tully', 'Ship')},
    {'id': 202, 'name': 'Phantom', 'serial_number': '428', 'retired': None, 'model': _model('Deep Ocean', 'Phantom', 'ROV')},
    {'id': 203, 'name': 'Delta', 'serial_number': None, 'retired': None, 'model': _model('Delta Oceanographics', 'Delta', 'Submersible')},
]


class MockAPI:
    """The MSEA API's people and instruments endpoints, paginated like the real
    one: instruments come in pages of 2, and 'next' points somewhere unreachable,
    as it can behind a proxy."""

    def __init__(self, host='127.0.0.1'):
        self.people, self.instruments, self.platforms = list(PEOPLE), list(INSTRUMENTS), list(PLATFORMS)
        self.fail = None  # path that answers 500
        self.requests = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                api.requests.append((url.path, query))
                if url.path == api.fail:
                    return self._send(500, {'detail': 'boom'})
                if url.path == '/api/v2/shared/people/':
                    return self._send(200, {'count': len(api.people), 'next': None, 'previous': None, 'results': api.people})
                if url.path == '/api/v2/rov/platforms/':
                    return self._send(200, {'count': len(api.platforms), 'next': None, 'previous': None,
                                            'results': api.platforms})
                if url.path == '/api/v2/rov/instruments/':
                    page = int(query.get('page', ['1'])[0])
                    results = api.instruments[(page - 1) * 2:page * 2]
                    more = page * 2 < len(api.instruments)
                    return self._send(200, {'count': len(api.instruments), 'previous': None, 'results': results,
                                            'next': 'http://unreachable.invalid/next' if more else None})
                self._send(404, {'detail': 'Not found.'})

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer((host, 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/api/v2'
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    api = MockAPI()
    yield api
    api.close()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('DIVELOG_HOME', str(tmp_path / 'home'))
    return tmp_path / 'home'


@pytest.fixture(autouse=True)
def collect_on_main_thread():
    """Widgets created by a test are freed by the garbage collector, which can
    run in any thread, including the mock API's. Qt objects must be destroyed
    on the GUI thread, so collect here instead, after each test."""
    gc.disable()
    yield
    gc.collect()
    gc.enable()


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
