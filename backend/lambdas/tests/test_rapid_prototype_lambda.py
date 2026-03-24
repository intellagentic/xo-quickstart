"""
Regression tests for rapid-prototype/lambda_function.py
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'rapid-prototype'))

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
def rp_module():
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://fake', 'JWT_SECRET': 'test', 'BUCKET_NAME': 'test-bucket'}):
        import importlib
        # Remove any previously loaded lambda_function to avoid collision
        if 'lambda_function' in sys.modules:
            del sys.modules['lambda_function']
        # Ensure rapid-prototype dir is first in path
        rp_dir = os.path.join(os.path.dirname(__file__), '..', 'rapid-prototype')
        sys.path.insert(0, rp_dir)
        try:
            import lambda_function
            importlib.reload(lambda_function)
            yield lambda_function
        finally:
            sys.path.remove(rp_dir)
            if 'lambda_function' in sys.modules:
                del sys.modules['lambda_function']


class TestOptionsHandler:
    def test_options_returns_200(self, rp_module, mock_deps):
        event = make_event(method='OPTIONS', path='/rapid-prototype/c123')
        response = rp_module.lambda_handler(event, None)
        assert_status(response, 200)


class TestGetSpec:
    def test_missing_client_id_returns_400(self, rp_module, mock_deps):
        started, _, _, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        event = make_event(method='GET', path='/rapid-prototype/', path_params={'id': ''})
        response = rp_module.lambda_handler(event, None)
        assert_status(response, 400)

    def test_client_not_found_returns_404(self, rp_module, mock_deps):
        started, _, mock_cur, _ = mock_deps
        started['require_auth'].return_value = (REGULAR_USER, None)
        mock_cur.fetchone.return_value = None
        event = make_event(method='GET', path='/rapid-prototype/c123', path_params={'id': 'c123'})
        response = rp_module.lambda_handler(event, None)
        assert_status(response, 404)


class TestBuildSpec:
    def test_basic_spec_structure(self, rp_module):
        analysis = {
            'problems': [
                {'title': 'Data Silos', 'severity': 'critical', 'evidence': 'Found in docs', 'recommendation': 'Integrate'}
            ],
            'schema': {
                'tables': [{'name': 'orders', 'columns': [{'name': 'id', 'type': 'INT', 'description': 'PK'}]}],
                'relationships': ['orders → customers']
            },
            'plan': [
                {'phase': 'Day 1-7', 'actions': ['Build dashboard', 'Create API']},
                {'phase': 'Day 8-14', 'actions': ['Add reports']},
            ],
            'sources': [{'name': 'data.csv'}]
        }
        md = rp_module.build_spec(
            client_id='c_123',
            company_name='Test Corp',
            website_url='https://test.com',
            contact_name='John Doe',
            contact_title='CEO',
            industry='Technology',
            description='A tech company',
            pain_point='Manual processes',
            analysis=analysis
        )
        assert '# Test Corp' in md
        assert 'Manual processes' in md
        assert 'Data Silos' in md
        assert 'orders' in md
        assert 'Build dashboard' in md
        assert 'TECH STACK' in md
        assert 'React 18' in md
        assert 'BUILD SEQUENCE' in md

    def test_spec_with_empty_analysis(self, rp_module):
        md = rp_module.build_spec(
            client_id='c_123',
            company_name='Empty Corp',
            website_url='',
            contact_name='',
            contact_title='',
            industry='',
            description='',
            pain_point='Unknown',
            analysis={'problems': [], 'schema': {}, 'plan': [], 'sources': []}
        )
        assert '# Empty Corp' in md
        assert 'Unknown' in md
        assert 'No schema tables' in md

    def test_spec_includes_footer(self, rp_module):
        md = rp_module.build_spec(
            client_id='c_test_123',
            company_name='Footer Corp',
            website_url='',
            contact_name='',
            contact_title='',
            industry='',
            description='',
            pain_point='Test',
            analysis={'problems': [], 'schema': {}, 'plan': [], 'sources': []}
        )
        assert 'c_test_123' in md
        assert 'Intellagentic' in md
