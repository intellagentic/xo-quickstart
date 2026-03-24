pip install bcrypt PyJWT cryptography \
--platform manylinux2014_x86_64 \
--implementation cp \
--python-version 3.11 \
--only-binary=:all: \
-t bcrypt-layer/python/


cd bcrypt-layer

zip -r ../bcrypt-layer.zip python/

cd ..

aws lambda publish-layer-version \
--layer-name bcrypt-jwt-layer \
--zip-file fileb://bcrypt-layer.zip \
--compatible-runtimes python3.11 python3.12 \
--region eu-west-2

python3 lambdas/shared/migrate_encrypt.py



All files pass syntax validation. Here's a summary of what was implemented:

Changes Made

New Files

- shared/crypto_helper.py — AES-256-GCM encrypt/decrypt helper with encrypt(), decrypt(), encrypt_json(), decrypt_json(), search_hash() functions
- shared/migrate_encrypt.py — One-time migration script to encrypt existing plaintext data

Updated Lambdas

┌─────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│     Lambda      │                                                                                Changes                                                                                 │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ auth            │ Email/name encrypted on INSERT. Lookups use email_hash (SHA-256). Decrypt on read. Added email_hash column migration.                                                  │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ clients         │ Contact PII (contact_name, contact_email, contact_phone, contact_linkedin, contacts_json, addresses_json, webhook URLs) encrypted on INSERT/UPDATE, decrypted on read. │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ partners        │ email, phone, contacts_json, addresses_json encrypted on create/update, decrypted on list.                                                                             │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ gdrive          │ google_drive_refresh_token encrypted on store, decrypted on read.                                                                                                      │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ buttons         │ Button url encrypted on sync, decrypted on read.                                                                                                                       │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ enrich          │ All PII fields decrypted when read for Claude analysis and webhook dispatch.                                                                                           │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ results         │ No changes needed (reads from S3, not encrypted DB fields).                                                                                                            │
├─────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ rapid-prototype │ No changes needed (reads company_name, industry — left unencrypted for searchability).                                                                                 │
└─────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

Backward Compatibility

- decrypt() returns the original value if decryption fails, so legacy plaintext data still works before running the migration
- decrypt_json() falls back to json.loads() for unencrypted JSON

Deployment Steps

1. Generate key: python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
2. Add AES_ENCRYPTION_KEY env var to all Lambdas
3. Add cryptography package to Lambda layer
4. Copy crypto_helper.py into each Lambda's deploy package
5. Deploy all Lambdas
6. Run migration: python backend/lambdas/shared/migrate_encrypt.py


All files pass. Here's a summary of the two-tier per-client encryption architecture:

Architecture

AES_MASTER_KEY (env var)
├── Encrypts: users.email, users.name, users.google_drive_refresh_token
├── Encrypts: partners.email, partners.phone, partners.contacts_json
├── Encrypts: buttons.url
└── Wraps: clients.encryption_key (per-client key stored encrypted)

Per-client key (clients.encryption_key)
├── Encrypts DB: contact_name, contact_email, contact_phone, contact_linkedin
│                 contacts_json, addresses_json, webhook URLs
└── Encrypts S3: {client_id}/client-config.md
{client_id}/skills/*.md
{client_id}/results/analysis.json
{client_id}/extracted/*.transcript.txt
{client_id}/uploads/* (binary, via gdrive import)

Files Changed

┌────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                File                │                                                                         Changes                                                                          │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ shared/crypto_helper.py            │ Rewritten — two-tier: master key functions (encrypt/decrypt) + client key functions (client_encrypt/client_decrypt) + S3 encryption                      │
│                                    │ (encrypt_s3_body/decrypt_s3_body/encrypt_s3_bytes/decrypt_s3_bytes) + key management (generate_client_key/unwrap_client_key)                             │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ shared/migrate_encrypt.py          │ Rewritten — generates per-client keys, encrypts DB + S3 files per client                                                                                 │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ clients/lambda_function.py         │ Generates client key on create, encrypts PII with client key, encrypts S3 config/skills with client key                                                  │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ enrich/lambda_function.py          │ Decrypts client data with client key, decrypts S3 files, encrypts results                                                                                │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ results/lambda_function.py         │ Decrypts analysis.json with client key                                                                                                                   │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ rapid-prototype/lambda_function.py │ Decrypts analysis.json with client key                                                                                                                   │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ gdrive/lambda_function.py          │ Encrypts imported files with client key                                                                                                                  │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ auth/lambda_function.py            │ Uses master key (unchanged from prior)                                                                                                                   │
├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ buttons/lambda_function.py         │ Uses master key (unchanged from prior)                                                                                                                   │
└────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

Key Points

- Client isolation: Each client's data is encrypted with a unique key — compromising one client's key doesn't expose other clients
- S3 markers: ENC: prefix for encrypted text, ENCB: prefix for encrypted binary — allows detecting unencrypted legacy files
- Backward compatible: client_decrypt falls back to master key then plaintext for migration period
- Pass-through mode: If AES_MASTER_KEY isn't set, everything works without encryption (for dev/testing)
- Presigned uploads: Files uploaded via browser presigned URLs are not encrypted at upload time (would need a Lambda@Edge or post-processing step)


Test Suite Summary

┌────────────────────────────────┬──────────────────────┬───────┬────────────────────────────────────────────────────────────────────────────────────────────┐
│           Test File            │        Lambda        │ Tests │                                          Coverage                                          │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_crypto_helper.py          │ shared/crypto_helper │ 33    │ Master key, client key, S3 body/bytes, search hash, passthrough mode                       │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_auth_helper.py            │ shared/auth_helper   │ 6     │ JWT verify, require_auth, expired tokens                                                   │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_auth_lambda.py            │ auth                 │ 20    │ Login, register, reset-password, token validation, magic links, preferences, JWT structure │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_clients_lambda.py         │ clients              │ 19    │ CRUD clients, partners, skills, system config, invite, generate_client_config              │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_upload_lambda.py          │ upload               │ 16    │ Presigned URLs, list/delete/toggle/replace uploads, branding, client verification          │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_buttons_lambda.py         │ buttons              │ 11    │ GET/sync/delete buttons, role enforcement, scope isolation                                 │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_results_lambda.py         │ results              │ 7     │ Processing/error/complete status, S3 fallback, NoSuchKey handling                          │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_enrich_lambda.py          │ enrich               │ 16    │ Route dispatch, text extraction, CSV, audio detection, JSON repair, client config          │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_gdrive_lambda.py          │ gdrive               │ 7     │ Auth URL, callback, file listing, import, routing                                          │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_rapid_prototype_lambda.py │ rapid-prototype      │ 6     │ Spec generation, schema rendering, empty analysis, footer                                  │
├────────────────────────────────┼──────────────────────┼───────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ Total                          │                      │ 151   │                                                                                            │
└────────────────────────────────┴──────────────────────┴───────┴────────────────────────────────────────────────────────────────────────────────────────────┘

Run with: cd backend/lambdas && python3 -m pytest tests/ -v


Functional Regression Test Summary

File: tests/test_functional_lifecycle.py

TestUserLifecycle (14 tests)

┌─────┬───────────────────────────────────────┬──────────────────────────────────────────────────────┐
│  #  │                 Test                  │                         Flow                         │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 01  │ Register new user                     │ POST /auth/register -> 201, JWT returned             │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 02  │ Login existing user                   │ POST /auth/login -> 200, JWT matches                 │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 03  │ Login wrong password                  │ POST /auth/login -> 401                              │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 04  │ Duplicate register                    │ POST /auth/register -> 409                           │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 05  │ Create client                         │ POST /clients -> 200, S3 folders created             │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 06  │ Create client missing name            │ POST /clients -> 400                                 │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 07  │ Upload files                          │ POST /upload -> 200, 2 presigned URLs                │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 08  │ List uploads                          │ GET /uploads -> only active files (deleted excluded) │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 09  │ Delete upload                         │ DELETE /uploads/{id} -> soft-deleted                 │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 10  │ Delete client (cascade)               │ DELETE /clients -> client + uploads removed          │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 11  │ Deleted client returns 404            │ DELETE /clients -> 404                               │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 12  │ User still works after client deleted │ POST /auth/login -> 200                              │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 13  │ Delete user from DB                   │ Direct DB delete verified                            │
├─────┼───────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 14  │ Deleted user login behavior           │ POST /auth/login -> auto-creates (201)               │
└─────┴───────────────────────────────────────┴──────────────────────────────────────────────────────┘

TestIdempotency (3 tests)

┌─────────────────────────────┬─────────────────────────────────────────────────┐
│            Test             │                    Verifies                     │
├─────────────────────────────┼─────────────────────────────────────────────────┤
│ Register then login         │ Same credentials work for both                  │
├─────────────────────────────┼─────────────────────────────────────────────────┤
│ Create-delete-create client │ Re-creation after delete produces new DB record │
├─────────────────────────────┼─────────────────────────────────────────────────┤
│ Upload-delete-upload cycle  │ Re-upload produces new upload ID                │
└─────────────────────────────┴─────────────────────────────────────────────────┘

Idempotency Design

- Each test run generates a unique RUN_ID (UUID) embedded in all emails, company names, and filenames
- FakeDB (in-memory) resets per test method via autouse=True fixture
- No real DB, S3, or AWS calls — fully mocked with SmartCursor routing SQL to FakeDB
- Every test creates its own data and verifies cleanup — no shared state between tests

