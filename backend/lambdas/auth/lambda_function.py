"""
XO Platform - Auth Lambda
Routes: POST /auth/login, POST /auth/register, POST /auth/reset-password, POST /auth/google

Login auto-creates accounts: if the email doesn't exist, a new user is created.
Google OAuth login restricted to allowed admin emails.
"""

import json
import os
import bcrypt
import jwt
import urllib.request
from datetime import datetime, timedelta, timezone
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL', '')
JWT_SECRET = os.environ.get('JWT_SECRET', '')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

ALLOWED_EMAILS = [
    'alan.moore@intellagentic.io',
    'ken.scott@intellagentic.io',
    'rs@multiversant.com',
    'vn@multiversant.com'
]

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Allow-Methods': 'POST, OPTIONS'
}


def lambda_handler(event, context):
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

    path = event.get('path', '')

    if path.endswith('/auth/google'):
        return handle_google_login(event)
    elif path.endswith('/auth/preferences'):
        return handle_preferences(event)
    elif path.endswith('/auth/reset-password'):
        return handle_reset_password(event)
    elif path.endswith('/auth/register'):
        return handle_register(event)
    else:
        return handle_login(event)


def _make_token(user_id, email, name, is_admin=False):
    payload = {
        'user_id': str(user_id),
        'email': email,
        'name': name,
        'is_admin': is_admin,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def _success_response(user_id, email, name, preferred_model='claude-sonnet-4-5-20250929', status=200, is_admin=False):
    token = _make_token(user_id, email, name, is_admin=is_admin)
    return {
        'statusCode': status,
        'headers': CORS_HEADERS,
        'body': json.dumps({
            'token': token,
            'user': {'id': str(user_id), 'email': email, 'name': name, 'preferred_model': preferred_model, 'is_admin': is_admin}
        })
    }


def handle_google_login(event):
    """POST /auth/google - Verify Google ID token and login/create admin user."""
    try:
        body = json.loads(event.get('body', '{}'))
        credential = body.get('credential', '')

        if not credential:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Google credential is required'})
            }

        # Verify token via Google's tokeninfo endpoint
        try:
            url = f'https://oauth2.googleapis.com/tokeninfo?id_token={credential}'
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                token_info = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"Google token verification failed: {e}")
            return {
                'statusCode': 401,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Invalid Google token'})
            }

        # Validate audience matches our client ID
        if token_info.get('aud') != GOOGLE_CLIENT_ID:
            return {
                'statusCode': 401,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Token audience mismatch'})
            }

        # Validate email is verified
        if token_info.get('email_verified') != 'true':
            return {
                'statusCode': 401,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Email not verified'})
            }

        email = token_info.get('email', '').lower()
        name = token_info.get('name', '') or email.split('@')[0].replace('.', ' ').title()

        # Check allowed list
        if email not in ALLOWED_EMAILS:
            return {
                'statusCode': 403,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Access denied. This email is not authorized.'})
            }

        # Upsert user in database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute(
            "SELECT id, email, name, COALESCE(preferred_model, 'claude-sonnet-4-5-20250929') FROM users WHERE email = %s",
            (email,)
        )
        row = cur.fetchone()

        if row:
            user_id, user_email, user_name, preferred_model = row
            cur.close()
            conn.close()
            print(f"Google login successful: {user_email}")
            return _success_response(user_id, user_email, user_name, preferred_model, is_admin=True)
        else:
            # Create new user with sentinel password (blocks password login)
            cur.execute(
                "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
                (email, 'google-oauth-no-password', name)
            )
            user_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            print(f"New Google OAuth account created: {email}")
            return _success_response(user_id, email, name, status=201, is_admin=True)

    except Exception as e:
        print(f"Google login error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }


def handle_login(event):
    """POST /auth/login - If user exists, verify password. If not, create account."""
    try:
        body = json.loads(event.get('body', '{}'))
        email = body.get('email', '').strip().lower()
        password = body.get('password', '')

        if not email or not password:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Email and password are required'})
            }

        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute(
            "SELECT id, email, password_hash, name, COALESCE(preferred_model, 'claude-sonnet-4-5-20250929') FROM users WHERE email = %s",
            (email,)
        )
        row = cur.fetchone()

        if row:
            # Existing user — verify password
            cur.close()
            conn.close()
            user_id, user_email, password_hash, user_name, preferred_model = row

            if not bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
                return {
                    'statusCode': 401,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'error': 'Invalid password'})
                }

            print(f"Login successful: {user_email}")
            return _success_response(user_id, user_email, user_name, preferred_model)

        else:
            # New user — create account
            if len(password) < 8:
                cur.close()
                conn.close()
                return {
                    'statusCode': 400,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'error': 'Password must be at least 8 characters'})
                }

            name = email.split('@')[0].replace('.', ' ').title()
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            cur.execute(
                "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
                (email, password_hash, name)
            )
            user_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

            print(f"New account created: {email}")
            return _success_response(user_id, email, name, status=201)

    except Exception as e:
        print(f"Login error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }


def handle_register(event):
    """POST /auth/register - Explicit registration (kept for API compatibility)."""
    try:
        body = json.loads(event.get('body', '{}'))
        email = body.get('email', '').strip().lower()
        password = body.get('password', '')
        name = body.get('name', '').strip()

        if not email or not password:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Email and password are required'})
            }

        if len(password) < 8:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Password must be at least 8 characters'})
            }

        if not name:
            name = email.split('@')[0].replace('.', ' ').title()

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return {
                'statusCode': 409,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'An account with that email already exists'})
            }

        cur.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
            (email, password_hash, name)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        print(f"Registration successful: {email}")
        return _success_response(user_id, email, name, status=201)

    except Exception as e:
        print(f"Register error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }


def handle_reset_password(event):
    """POST /auth/reset-password - Directly resets password (prototype, no email verification)."""
    try:
        body = json.loads(event.get('body', '{}'))
        email = body.get('email', '').strip().lower()
        new_password = body.get('new_password', '')

        if not email or not new_password:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Email and new password are required'})
            }

        if len(new_password) < 8:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Password must be at least 8 characters'})
            }

        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return {
                'statusCode': 404,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'No account found with that email'})
            }

        password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("UPDATE users SET password_hash = %s WHERE email = %s", (password_hash, email))
        conn.commit()
        cur.close()
        conn.close()

        print(f"Password reset for: {email}")
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'message': 'Password reset successfully'})
        }

    except Exception as e:
        print(f"Reset password error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }


def handle_preferences(event):
    """PUT /auth/preferences - Update user preferences (requires auth)."""
    # Verify JWT
    headers = event.get('headers', {}) or {}
    auth_header = headers.get('Authorization') or headers.get('authorization', '')
    if not auth_header.startswith('Bearer '):
        return {'statusCode': 401, 'headers': CORS_HEADERS, 'body': json.dumps({'error': 'Unauthorized'})}

    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        user_id = payload['user_id']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return {'statusCode': 401, 'headers': CORS_HEADERS, 'body': json.dumps({'error': 'Unauthorized'})}

    try:
        body = json.loads(event.get('body', '{}'))
        preferred_model = body.get('preferred_model', '')

        allowed_models = ['claude-opus-4-6', 'claude-sonnet-4-5-20250929', 'claude-haiku-4-5-20251001']
        if preferred_model not in allowed_models:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': f'Invalid model. Allowed: {", ".join(allowed_models)}'})
            }

        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("UPDATE users SET preferred_model = %s WHERE id = %s", (preferred_model, user_id))
        conn.commit()
        cur.close()
        conn.close()

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'preferred_model': preferred_model})
        }

    except Exception as e:
        print(f"Preferences error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }
