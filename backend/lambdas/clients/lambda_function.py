"""
XO Platform - POST /clients Lambda
Creates a new client with S3 folder structure and PostgreSQL record.
"""

import json
import os
import time
import hashlib
import boto3
from datetime import datetime, timezone
from auth_helper import require_auth, get_db_connection, CORS_HEADERS

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'xo-client-data')


def lambda_handler(event, context):
    """
    Create a new client entry with S3 folder structure + DB row.

    Expected input:
    {
        "company_name": "Company Name",
        "website": "https://example.com",
        "contactName": "John Doe",
        "contactTitle": "CEO",
        "contactLinkedIn": "https://linkedin.com/in/...",
        "industry": "Waste Management",
        "description": "Optional description",
        "painPoint": "Route optimization"
    }

    Returns:
    {
        "client_id": "client_1234567890_abcd",
        "id": "uuid",
        "status": "created"
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
        company_name = body.get('company_name', '').strip()
        website = body.get('website', '').strip()
        contact_name = body.get('contactName', '').strip()
        contact_title = body.get('contactTitle', '').strip()
        contact_linkedin = body.get('contactLinkedIn', '').strip()
        industry = body.get('industry', '').strip()
        description = body.get('description', '').strip()
        pain_point = body.get('painPoint', '').strip()

        # Validate required fields
        if not company_name:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'company_name is required'})
            }

        # Generate unique client_id (S3 folder name)
        timestamp = str(int(time.time()))
        name_hash = hashlib.md5(company_name.encode()).hexdigest()[:8]
        client_id = f"client_{timestamp}_{name_hash}"

        # Create folder structure in S3
        folders = [
            f"{client_id}/uploads/",
            f"{client_id}/extracted/",
            f"{client_id}/results/"
        ]

        for folder in folders:
            s3_client.put_object(Bucket=BUCKET_NAME, Key=folder, Body='')

        # Insert into PostgreSQL
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO clients (
                user_id, company_name, website_url, contact_name, contact_title,
                contact_linkedin, industry, description, pain_point, s3_folder
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            user['user_id'], company_name, website, contact_name, contact_title,
            contact_linkedin, industry, description, pain_point, client_id
        ))

        db_id = str(cur.fetchone()[0])
        conn.commit()
        cur.close()
        conn.close()

        print(f"Created client: {client_id} (db: {db_id}) for company: {company_name}")

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'client_id': client_id,
                'id': db_id,
                'status': 'created'
            })
        }

    except Exception as e:
        print(f"Error creating client: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }
