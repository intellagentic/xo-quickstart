"""
XO Platform - POST /upload Lambda
Generates presigned URLs for direct S3 uploads and records in DB.
"""

import json
import os
import boto3
from auth_helper import require_auth, get_db_connection, CORS_HEADERS

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'xo-client-data')
URL_EXPIRATION = 3600  # 1 hour


def lambda_handler(event, context):
    """
    Generate presigned URLs for file uploads.

    Expected input:
    {
        "client_id": "client_1234567890_abcd",
        "files": [
            {"name": "data.csv", "type": "text/csv"},
            {"name": "report.pdf", "type": "application/pdf"}
        ]
    }

    Returns:
    {
        "upload_urls": ["https://...", "https://..."]
    }
    """

    # Handle OPTIONS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

    # Auth check
    user, err = require_auth(event)
    if err:
        return err

    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        client_id = body.get('client_id', '').strip()
        files = body.get('files', [])

        if not client_id:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'client_id is required'})
            }

        if not files or not isinstance(files, list):
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'files array is required'})
            }

        # Verify client exists in DB and belongs to this user
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM clients WHERE s3_folder = %s AND user_id = %s",
            (client_id, user['user_id'])
        )
        row = cur.fetchone()

        if not row:
            cur.close()
            conn.close()
            return {
                'statusCode': 404,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Client not found'})
            }

        db_client_id = row[0]

        # Generate presigned URLs and record uploads
        upload_urls = []
        for file_info in files:
            file_name = file_info.get('name', '')
            file_type = file_info.get('type', 'application/octet-stream')

            if not file_name:
                continue

            s3_key = f"{client_id}/uploads/{file_name}"

            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': BUCKET_NAME,
                    'Key': s3_key,
                    'ContentType': file_type
                },
                ExpiresIn=URL_EXPIRATION
            )

            upload_urls.append(presigned_url)

            # Record upload in DB
            cur.execute("""
                INSERT INTO uploads (client_id, filename, file_type, s3_key)
                VALUES (%s, %s, %s, %s)
            """, (str(db_client_id), file_name, file_type, s3_key))

        conn.commit()
        cur.close()
        conn.close()

        print(f"Generated {len(upload_urls)} presigned URLs for client: {client_id}")

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'upload_urls': upload_urls})
        }

    except Exception as e:
        print(f"Error generating presigned URLs: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }
