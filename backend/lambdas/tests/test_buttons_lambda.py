"""
Regression tests for buttons/lambda_function.py
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'buttons'))

from test_helpers import (
    make_event, assert_status, parse_body,
    ADMIN_USER, PARTNER_USER, CLIENT_USER, REGULAR_USER
)


@pytest.fixture
def mock_deps():
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = []

    patches = {
        'get_db_connection': patch('lambda_function.get_db_connection', return_value=mock_conn),
        'require_auth': patch('lambda_function.require_auth'),
    }
    started = {k: p.start() for k, p in patches.items()}
    yield started, mock_conn, mock_cur
    for p in patches.values():
        p.stop()


@pytest.fixture
def buttons_module():
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://fake', 'JWT_SECRET': 'test'}):
        with patch('psycopg2.connect') as mock_connect:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_connect.return_value = mock_conn
            import importlib
            if 'lambda_function' in sys.modules:
                del sys.modules['lambda_function']
            buttons_dir = os.path.join(os.path.dirname(__file__), '..', 'buttons')
            sys.path.insert(0, buttons_dir)
            try:
                import lambda_function
                importlib.reload(lambda_function)
                yield lambda_function
            finally:
                sys.path.remove(buttons_dir)
                if 'lambda_function' in sys.modules:
                    del sys.modules['lambda_function']


class TestOptionsHandler:
    def test_options_returns_200(self, buttons_module, mock_deps):
        event = make_event(method='OPTIONS', path='/buttons')
        started, _, _ = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 200)


class TestGetButtons:
    def test_empty_system_buttons(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        mock_cur.fetchall.return_value = []
        event = make_event(method='GET', path='/buttons', query_params={'scope': 'system'})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 200)
        assert parse_body(response)['buttons'] == []

    def test_get_combined_buttons(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        mock_cur.fetchall.return_value = [
            ('id-1', 'Btn 1', 'Zap', '#3b82f6', 'https://test.com', 0, None),
        ]
        event = make_event(method='GET', path='/buttons', query_params={'client_id': 'c123'})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 200)
        body = parse_body(response)
        assert len(body['buttons']) == 1
        assert body['buttons'][0]['label'] == 'Btn 1'
        assert body['buttons'][0]['scope'] == 'system'


class TestSyncButtons:
    def test_system_sync_requires_admin(self, buttons_module, mock_deps):
        started, _, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        event = make_event(method='PUT', path='/buttons/sync',
                           body={'scope': 'system', 'buttons': []})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 403)

    def test_admin_can_sync_system_buttons(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        event = make_event(method='PUT', path='/buttons/sync', body={
            'scope': 'system',
            'buttons': [
                {'label': 'Test', 'icon': 'Zap', 'color': '#f00', 'url': 'https://x.com'}
            ]
        })
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 200)
        assert parse_body(response)['count'] == 1

    def test_sync_client_buttons(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        event = make_event(method='PUT', path='/buttons/sync', body={
            'client_id': 'c123',
            'buttons': [{'label': 'B1'}, {'label': 'B2'}]
        })
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 200)
        assert parse_body(response)['count'] == 2

    def test_sync_user_buttons(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        event = make_event(method='PUT', path='/buttons/sync',
                           body={'buttons': [{'label': 'My Btn'}]})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 200)


class TestDeleteButton:
    def test_missing_button_id_returns_400(self, buttons_module, mock_deps):
        started, _, _ = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        event = make_event(method='DELETE', path='/buttons', query_params={})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 400)

    def test_button_not_found_returns_404(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        mock_cur.fetchone.return_value = None
        event = make_event(method='DELETE', path='/buttons', query_params={'button_id': '999'})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 404)

    def test_non_admin_cannot_delete_system_button(self, buttons_module, mock_deps):
        started, _, mock_cur = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = (None,)  # client_id is None → system button
        event = make_event(method='DELETE', path='/buttons', query_params={'button_id': '1'})
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 403)


class TestMethodNotAllowed:
    def test_patch_returns_405(self, buttons_module, mock_deps):
        started, _, _ = mock_deps
        started['require_auth'].return_value = (ADMIN_USER, None)
        event = make_event(method='PATCH', path='/buttons')
        response = buttons_module.lambda_handler(event, None)
        assert_status(response, 405)
