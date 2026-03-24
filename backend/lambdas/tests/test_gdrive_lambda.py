"""
Regression tests for gdrive/lambda_function.py
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gdrive'))

from test_helpers import make_event, assert_status, parse_body, ADMIN_USER, REGULAR_USER


@pytest.fixture
def mock_deps():
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = None

    mock_s3 = MagicMock()

    patches = {
        'get_db_connection': patch('lambda_function.get_db_connection', return_value=mock_conn),
        'require_auth': patch('lambda_function.require_auth'),
        's3': patch('lambda_function.s3', mock_s3),
    }
    started = {k: p.start() for k, p in patches.items()}
    yield started, mock_conn, mock_cur, mock_s3
    for p in patches.values():
        p.stop()


@pytest.fixture
def gdrive_module():
    with patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://fake',
        'JWT_SECRET': 'test',
        'GOOGLE_CLIENT_ID': 'test-id',
        'GOOGLE_CLIENT_SECRET': 'test-secret',
        'BUCKET_NAME': 'test-bucket',
    }):
        # Mock Google libraries
        mock_flow = MagicMock()
        mock_build = MagicMock()
        mock_creds = MagicMock()

        with patch.dict(sys.modules, {
            'google': MagicMock(),
            'google.oauth2': MagicMock(),
            'google.oauth2.credentials': MagicMock(),
            'google_auth_oauthlib': MagicMock(),
            'google_auth_oauthlib.flow': MagicMock(),
            'googleapiclient': MagicMock(),
            'googleapiclient.discovery': MagicMock(),
            'googleapiclient.http': MagicMock(),
        }):
            import importlib
            if 'lambda_function' in sys.modules:
                del sys.modules['lambda_function']
            gdrive_dir = os.path.join(os.path.dirname(__file__), '..', 'gdrive')
            sys.path.insert(0, gdrive_dir)
            try:
                import lambda_function
                importlib.reload(lambda_function)
                yield lambda_function
            finally:
                sys.path.remove(gdrive_dir)
                if 'lambda_function' in sys.modules:
                    del sys.modules['lambda_function']


class TestOptionsHandler:
    def test_options_returns_200(self, gdrive_module, mock_deps):
        event = make_event(method='OPTIONS', path='/gdrive/auth-url')
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 200)


class TestRouting:
    def test_unknown_route_returns_404(self, gdrive_module, mock_deps):
        started, _, _, _ = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        event = make_event(method='GET', path='/gdrive/unknown')
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 404)


class TestAuthUrl:
    def test_no_auth_returns_error(self, gdrive_module, mock_deps):
        started, _, _, _ = mock_deps
        started['require_auth'].return_value = (None, {
            'statusCode': 401, 'headers': {}, 'body': json.dumps({'error': 'Unauthorized'})
        })
        event = make_event(method='GET', path='/gdrive/auth-url')
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 401)


class TestCallback:
    def test_missing_code_returns_400(self, gdrive_module, mock_deps):
        started, _, _, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        event = make_event(method='POST', path='/gdrive/callback', body={})
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 400)


class TestListFiles:
    def test_no_refresh_token_returns_400(self, gdrive_module, mock_deps):
        started, _, mock_cur, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = (None,)  # no refresh token
        event = make_event(method='GET', path='/gdrive/files')
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 400)
        assert 'not connected' in parse_body(response)['error']


class TestImport:
    def test_missing_fields_returns_400(self, gdrive_module, mock_deps):
        started, _, _, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        event = make_event(method='POST', path='/gdrive/import', body={})
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 400)

    def test_client_not_found_returns_403(self, gdrive_module, mock_deps):
        started, _, mock_cur, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = None  # client not found
        event = make_event(method='POST', path='/gdrive/import',
                           body={'file_ids': ['f1'], 'client_id': 'bad'})
        response = gdrive_module.lambda_handler(event, None)
        assert_status(response, 403)
