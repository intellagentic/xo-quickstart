"""
Regression tests for results/lambda_function.py
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'results'))

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
        's3_client': patch('lambda_function.s3_client', mock_s3),
    }
    started = {k: p.start() for k, p in patches.items()}
    yield started, mock_conn, mock_cur, mock_s3
    for p in patches.values():
        p.stop()


@pytest.fixture
def results_module():
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://fake', 'JWT_SECRET': 'test', 'BUCKET_NAME': 'test-bucket'}):
        import importlib
        if 'lambda_function' in sys.modules:
            del sys.modules['lambda_function']
        results_dir = os.path.join(os.path.dirname(__file__), '..', 'results')
        sys.path.insert(0, results_dir)
        try:
            import lambda_function
            importlib.reload(lambda_function)
            yield lambda_function
        finally:
            sys.path.remove(results_dir)
            if 'lambda_function' in sys.modules:
                del sys.modules['lambda_function']


class TestOptionsHandler:
    def test_options_returns_200(self, results_module, mock_deps):
        started, _, _, _ = mock_deps
        event = make_event(method='OPTIONS', path='/results/c123')
        response = results_module.lambda_handler(event, None)
        assert_status(response, 200)


class TestGetResults:
    def test_missing_client_id_returns_400(self, results_module, mock_deps):
        started, _, _, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        event = make_event(method='GET', path='/results/', path_params={'id': ''})
        response = results_module.lambda_handler(event, None)
        assert_status(response, 400)

    def test_processing_status(self, results_module, mock_deps):
        started, _, mock_cur, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = ('processing', None, 'extracting', None)
        event = make_event(method='GET', path='/results/c123', path_params={'id': 'c123'})
        response = results_module.lambda_handler(event, None)
        assert_status(response, 200)
        body = parse_body(response)
        assert body['status'] == 'processing'
        assert body['stage'] == 'extracting'

    def test_error_status(self, results_module, mock_deps):
        started, _, mock_cur, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = ('error', None, 'analyzing', None)
        event = make_event(method='GET', path='/results/c123', path_params={'id': 'c123'})
        response = results_module.lambda_handler(event, None)
        assert_status(response, 200)
        body = parse_body(response)
        assert body['status'] == 'error'

    def test_complete_reads_s3(self, results_module, mock_deps):
        started, _, mock_cur, mock_s3 = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = ('complete', 'c123/results/analysis.json', 'complete', None)

        # Mock S3 response (unencrypted legacy data)
        analysis = {'problems': [], 'schema': {}, 'plan': []}
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(analysis).encode()
        mock_s3.get_object.return_value = {'Body': mock_body}

        event = make_event(method='GET', path='/results/c123', path_params={'id': 'c123'})
        response = results_module.lambda_handler(event, None)
        assert_status(response, 200)
        body = parse_body(response)
        assert body['status'] == 'complete'

    def test_no_enrichment_falls_back_to_s3(self, results_module, mock_deps):
        started, _, mock_cur, mock_s3 = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = None  # no enrichment record

        # S3 has the file
        analysis = {'problems': [{'title': 'Test'}]}
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(analysis).encode()
        mock_s3.get_object.return_value = {'Body': mock_body}

        event = make_event(method='GET', path='/results/c123', path_params={'id': 'c123'})
        response = results_module.lambda_handler(event, None)
        assert_status(response, 200)

    def test_no_s3_file_returns_processing(self, results_module, mock_deps):
        started, _, mock_cur, mock_s3 = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = None

        # S3 raises NoSuchKey
        mock_s3.exceptions.NoSuchKey = type('NoSuchKey', (Exception,), {})
        mock_s3.get_object.side_effect = mock_s3.exceptions.NoSuchKey()

        event = make_event(method='GET', path='/results/c123', path_params={'id': 'c123'})
        response = results_module.lambda_handler(event, None)
        assert_status(response, 200)
        assert parse_body(response)['status'] == 'processing'
