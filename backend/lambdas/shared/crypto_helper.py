"""
XO Platform - Shared AES Encryption Helper
Two-tier encryption:
  1. Master key (AES_MASTER_KEY env var) — encrypts client keys + system-level data (users, partners)
  2. Per-client key (stored encrypted in clients.encryption_key) — encrypts client PII + S3 files

Setup:
  1. Generate master key: python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
  2. Set AES_MASTER_KEY env var on all Lambdas
  3. Add 'cryptography' to Lambda layer or deploy package
"""

import os
import base64
import json
import hashlib

AES_MASTER_KEY = os.environ.get('AES_MASTER_KEY', '') or os.environ.get('AES_ENCRYPTION_KEY', '')
_NONCE_SIZE = 12  # 96-bit nonce for AES-GCM

# Lazy-load cryptography
_aesgcm_cls = None


def _get_aesgcm():
    global _aesgcm_cls
    if _aesgcm_cls is None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            _aesgcm_cls = AESGCM
        except ImportError:
            _aesgcm_cls = False
    return _aesgcm_cls


def _get_master_key():
    """Decode the base64-encoded 256-bit master AES key."""
    if not AES_MASTER_KEY:
        return None
    return base64.b64decode(AES_MASTER_KEY)


def _encryption_available():
    """Check if encryption is configured and available."""
    return bool(AES_MASTER_KEY) and _get_aesgcm() not in (None, False)


# ──────────────────────────────────────────────
# Per-client key management
# ──────────────────────────────────────────────

def generate_client_key():
    """Generate a new 256-bit AES key for a client.
    Returns the key encrypted with the master key (for DB storage)."""
    raw_key = os.urandom(32)
    if not _encryption_available():
        # Pass-through: return base64 raw key
        return base64.b64encode(raw_key).decode('utf-8')
    # Encrypt the raw key with master key
    return _encrypt_with_raw_key(_get_master_key(), base64.b64encode(raw_key).decode('utf-8'))


def unwrap_client_key(encrypted_key):
    """Decrypt a client's encryption key using the master key.
    Returns the raw 32-byte key for use with encrypt_with_key/decrypt_with_key."""
    if not encrypted_key:
        return None
    if not _encryption_available():
        # Pass-through: assume it's base64 raw key
        try:
            return base64.b64decode(encrypted_key)
        except Exception:
            return None
    # Decrypt with master key to get base64-encoded raw key
    decrypted = _decrypt_with_raw_key(_get_master_key(), encrypted_key)
    if not decrypted:
        return None
    try:
        return base64.b64decode(decrypted)
    except Exception:
        return None


# ──────────────────────────────────────────────
# Low-level encrypt/decrypt with a specific raw key
# ──────────────────────────────────────────────

def _encrypt_with_raw_key(raw_key, plaintext):
    """Encrypt plaintext with a specific 32-byte raw key."""
    if not plaintext or not raw_key:
        return plaintext
    AESGCM = _get_aesgcm()
    if not AESGCM:
        return plaintext
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(raw_key).encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ciphertext).decode('utf-8')


def _decrypt_with_raw_key(raw_key, token):
    """Decrypt token with a specific 32-byte raw key."""
    if not token or not raw_key:
        return token
    AESGCM = _get_aesgcm()
    if not AESGCM:
        return token
    try:
        raw = base64.b64decode(token)
        nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        return AESGCM(raw_key).decrypt(nonce, ciphertext, None).decode('utf-8')
    except Exception:
        return token


# ──────────────────────────────────────────────
# Master-key encrypt/decrypt (system-level: users, partners)
# ──────────────────────────────────────────────

def encrypt(plaintext):
    """Encrypt with master key. For system-level data (users, partners)."""
    if not plaintext:
        return plaintext
    if not _encryption_available():
        return plaintext
    return _encrypt_with_raw_key(_get_master_key(), plaintext)


def decrypt(token):
    """Decrypt with master key. For system-level data (users, partners)."""
    if not token:
        return token
    if not _encryption_available():
        return token
    return _decrypt_with_raw_key(_get_master_key(), token)


def encrypt_json(obj):
    """Encrypt JSON object with master key."""
    if not obj:
        return obj
    serialized = json.dumps(obj)
    if not _encryption_available():
        return serialized
    return encrypt(serialized)


def decrypt_json(token):
    """Decrypt JSON from master key."""
    if not token:
        return None
    decrypted = decrypt(token)
    try:
        return json.loads(decrypted)
    except (json.JSONDecodeError, TypeError):
        try:
            return json.loads(token)
        except Exception:
            return None


# ──────────────────────────────────────────────
# Client-key encrypt/decrypt (per-client DB fields)
# ──────────────────────────────────────────────

def client_encrypt(client_key, plaintext):
    """Encrypt with a client's unwrapped raw key."""
    if not plaintext or not client_key:
        return plaintext
    if not _encryption_available():
        return plaintext
    return _encrypt_with_raw_key(client_key, plaintext)


def client_decrypt(client_key, token):
    """Decrypt with a client's unwrapped raw key.
    Falls back to master key, then plaintext for legacy data."""
    if not token:
        return token
    if not client_key or not _encryption_available():
        return token
    result = _decrypt_with_raw_key(client_key, token)
    # If client key didn't work, try master key (migration period)
    if result == token and _get_master_key():
        master_result = _decrypt_with_raw_key(_get_master_key(), token)
        if master_result != token:
            return master_result
    return result


def client_encrypt_json(client_key, obj):
    """Encrypt JSON object with client key."""
    if not obj:
        return obj
    serialized = json.dumps(obj)
    if not client_key or not _encryption_available():
        return serialized
    return client_encrypt(client_key, serialized)


def client_decrypt_json(client_key, token):
    """Decrypt JSON from client key. Falls back to master key then plain JSON."""
    if not token:
        return None
    decrypted = client_decrypt(client_key, token)
    try:
        return json.loads(decrypted)
    except (json.JSONDecodeError, TypeError):
        try:
            return json.loads(token)
        except Exception:
            return None


# ──────────────────────────────────────────────
# S3 body encrypt/decrypt (per-client)
# ──────────────────────────────────────────────

def encrypt_s3_body(client_key, body):
    """Encrypt S3 file body (bytes or str) with client key.
    Returns bytes. Prepends 'ENC:' marker so we can detect encrypted files."""
    if not body or not client_key or not _encryption_available():
        return body if isinstance(body, bytes) else (body.encode('utf-8') if body else b'')
    text = body if isinstance(body, str) else body.decode('utf-8', errors='replace')
    encrypted = client_encrypt(client_key, text)
    return ('ENC:' + encrypted).encode('utf-8')


def decrypt_s3_body(client_key, body):
    """Decrypt S3 file body (bytes) with client key.
    Returns string. Detects 'ENC:' marker; returns as-is if not encrypted."""
    if not body:
        return ''
    text = body if isinstance(body, str) else body.decode('utf-8', errors='replace')
    if not text.startswith('ENC:'):
        # Not encrypted — return as-is
        return text
    if not client_key or not _encryption_available():
        # Can't decrypt — return raw (without marker)
        return text[4:]
    return client_decrypt(client_key, text[4:])


def encrypt_s3_bytes(client_key, data):
    """Encrypt arbitrary binary S3 data with client key.
    Returns bytes. Prepends b'ENCB:' + base64(encrypted nonce+ciphertext)."""
    if not data or not client_key or not _encryption_available():
        return data
    AESGCM = _get_aesgcm()
    if not AESGCM:
        return data
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(client_key).encrypt(nonce, data, None)
    encoded = base64.b64encode(nonce + ciphertext)
    return b'ENCB:' + encoded


def decrypt_s3_bytes(client_key, data):
    """Decrypt binary S3 data encrypted with encrypt_s3_bytes.
    Returns bytes. Detects 'ENCB:' marker."""
    if not data:
        return data
    if not data.startswith(b'ENCB:'):
        return data
    if not client_key or not _encryption_available():
        return data
    AESGCM = _get_aesgcm()
    if not AESGCM:
        return data
    try:
        raw = base64.b64decode(data[5:])
        nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        return AESGCM(client_key).decrypt(nonce, ciphertext, None)
    except Exception:
        return data


# ──────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────

def search_hash(value):
    """Generate a deterministic SHA-256 hash for encrypted field lookups."""
    if not value:
        return ''
    return hashlib.sha256(value.lower().strip().encode('utf-8')).hexdigest()
