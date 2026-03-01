"""
XO Platform - POST /auth/login Lambda
Authenticates users with bcrypt and returns JWT token.
"""

import json
import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL', '')
JWT_SECRET = os.environ.get('JWT_SECRET', '')

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Allow-Methods': 'POST, OPTIONS'
}


def lambda_handler(event, context):
    """
    POST /auth/login
    Validates email/password, returns JWT + user object.

    Request:
    {
        "email": "admin@xo.com",
        "password": "XOquickstart2026!"
    }

    Response:
    {
        "token": "eyJ...",
        "user": {
            "id": "uuid",
            "email": "admin@xo.com",
            "name": "XO Admin"
        }
    }
    """

    # Handle OPTIONS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

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

        # Look up user in database
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute(
            "SELECT id, email, password_hash, name FROM users WHERE email = %s",
            (email,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return {
                'statusCode': 401,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Invalid email or password'})
            }

        user_id, user_email, password_hash, user_name = row

        # Verify password with bcrypt
        if not bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            return {
                'statusCode': 401,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Invalid email or password'})
            }

        # Generate JWT (24h expiry)
        payload = {
            'user_id': str(user_id),
            'email': user_email,
            'name': user_name,
            'exp': datetime.now(timezone.utc) + timedelta(hours=24)
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')

        print(f"Login successful: {user_email}")

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'token': token,
                'user': {
                    'id': str(user_id),
                    'email': user_email,
                    'name': user_name
                }
            })
        }

    except Exception as e:
        print(f"Login error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }
