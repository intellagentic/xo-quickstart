"""
XO Platform - Buttons Lambda
GET /buttons       -- return all buttons for authenticated user
PUT /buttons/sync  -- full replace of user's buttons
"""

import json
from auth_helper import require_auth, get_db_connection, CORS_HEADERS


def lambda_handler(event, context):
    """Route to GET or PUT handler based on HTTP method."""

    # Handle OPTIONS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

    # Auth check
    user, err = require_auth(event)
    if err:
        return err

    method = event.get('httpMethod', '')

    if method == 'GET':
        return handle_get(user)
    elif method == 'PUT':
        return handle_sync(event, user)
    else:
        return {
            'statusCode': 405,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Method not allowed'})
        }


def handle_get(user):
    """Return all buttons for the authenticated user, ordered by sort_order."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, name, icon, color, url, sort_order
            FROM buttons
            WHERE user_id = %s
            ORDER BY sort_order ASC
        """, (user['user_id'],))

        buttons = []
        for row in cur.fetchall():
            buttons.append({
                'id': str(row[0]),
                'label': row[1],
                'icon': row[2],
                'color': row[3],
                'url': row[4] or '',
                'sort_order': row[5]
            })

        cur.close()
        conn.close()

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'buttons': buttons})
        }

    except Exception as e:
        print(f"Error fetching buttons: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }


def handle_sync(event, user):
    """Full replace: delete all user's buttons, insert new set."""
    try:
        body = json.loads(event.get('body', '{}'))
        buttons = body.get('buttons', [])

        conn = get_db_connection()
        cur = conn.cursor()

        # Delete existing buttons
        cur.execute("DELETE FROM buttons WHERE user_id = %s", (user['user_id'],))

        # Insert new buttons
        for i, btn in enumerate(buttons):
            cur.execute("""
                INSERT INTO buttons (user_id, name, icon, color, url, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                user['user_id'],
                btn.get('label', btn.get('name', 'Button')),
                btn.get('icon', 'Zap'),
                btn.get('color', '#3b82f6'),
                btn.get('url', ''),
                btn.get('sort_order', i)
            ))

        conn.commit()
        cur.close()
        conn.close()

        print(f"Synced {len(buttons)} buttons for user {user['email']}")

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'status': 'synced', 'count': len(buttons)})
        }

    except Exception as e:
        print(f"Error syncing buttons: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'Internal server error'})
        }
