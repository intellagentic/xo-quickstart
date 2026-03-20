"""
Regression tests for shared/auth_helper.py
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))


class TestVerifyToken:
    @patch.dict(os.environ, {'JWT_SECRET': 'test-secret', 'DATABASE_URL': 'postgresql://fake'})
    def test_missing_auth_header(self):
        import importlib
        import auth_helper
        importlib.reload(auth_helper)

        result = auth_helper.verify_token({'headers': {}})
        assert result is None

    @patch.dict(os.environ, {'JWT_SECRET': 'test-secret', 'DATABASE_URL': 'postgresql://fake'})
    def test_invalid_bearer_prefix(self):
        import importlib
        import auth_helper
        importlib.reload(auth_helper)

        result = auth_helper.verify_token({'headers': {'Authorization': 'Basic abc'}})
        assert result is None

    @patch.dict(os.environ, {'JWT_SECRET': 'test-secret', 'DATABASE_URL': 'postgresql://fake'})
    def test_valid_token(self):
        import importlib
        import jwt
        import auth_helper
        importlib.reload(auth_helper)

        from datetime import datetime, timezone, timedelta
        payload = {
            'user_id': 'u1', 'email': 'a@b.com', 'name': 'Test',
            'role': 'admin', 'is_admin': True, 'is_partner': False, 'is_client': False,
            'exp': datetime.now(timezone.utc) + timedelta(hours=1)
        }
        token = jwt.encode(payload, 'test-secret', algorithm='HS256')
        result = auth_helper.verify_token({'headers': {'Authorization': f'Bearer {token}'}})
        assert result is not None
        assert result['user_id'] == 'u1'
        assert result['is_admin'] is True

    @patch.dict(os.environ, {'JWT_SECRET': 'test-secret', 'DATABASE_URL': 'postgresql://fake'})
    def test_expired_token(self):
        import importlib
        import jwt
        import auth_helper
        importlib.reload(auth_helper)

        from datetime import datetime, timezone, timedelta
        payload = {
            'user_id': 'u1', 'email': 'a@b.com',
            'exp': datetime.now(timezone.utc) - timedelta(hours=1)
        }
        token = jwt.encode(payload, 'test-secret', algorithm='HS256')
        result = auth_helper.verify_token({'headers': {'Authorization': f'Bearer {token}'}})
        assert result is None


class TestRequireAuth:
    @patch.dict(os.environ, {'JWT_SECRET': 'test-secret', 'DATABASE_URL': 'postgresql://fake'})
    def test_no_token_returns_401(self):
        import importlib
        import auth_helper
        importlib.reload(auth_helper)

        user, err = auth_helper.require_auth({'headers': {}})
        assert user is None
        assert err['statusCode'] == 401

    @patch.dict(os.environ, {'JWT_SECRET': 'test-secret', 'DATABASE_URL': 'postgresql://fake'})
    def test_valid_token_returns_user(self):
        import importlib
        import jwt
        import auth_helper
        importlib.reload(auth_helper)

        from datetime import datetime, timezone, timedelta
        payload = {
            'user_id': 'u1', 'email': 'a@b.com', 'name': 'Test',
            'exp': datetime.now(timezone.utc) + timedelta(hours=1)
        }
        token = jwt.encode(payload, 'test-secret', algorithm='HS256')
        user, err = auth_helper.require_auth({'headers': {'Authorization': f'Bearer {token}'}})
        assert err is None
        assert user['user_id'] == 'u1'
