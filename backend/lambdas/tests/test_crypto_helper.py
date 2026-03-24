"""
Regression tests for shared/crypto_helper.py
Tests two-tier AES-256-GCM encryption: master key + per-client keys.
"""

import os
import sys
import json
import base64
import pytest

# Ensure shared is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

# Generate a test master key
TEST_MASTER_KEY = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def set_master_key(monkeypatch):
    monkeypatch.setenv('AES_MASTER_KEY', TEST_MASTER_KEY)
    # Force re-import with fresh env
    import importlib
    import crypto_helper
    importlib.reload(crypto_helper)
    crypto_helper.AES_MASTER_KEY = TEST_MASTER_KEY
    yield crypto_helper


# ── Master key encrypt/decrypt ──

class TestMasterKeyEncryption:
    def test_encrypt_decrypt_roundtrip(self, set_master_key):
        ch = set_master_key
        plaintext = "hello@example.com"
        encrypted = ch.encrypt(plaintext)
        assert encrypted != plaintext
        assert ch.decrypt(encrypted) == plaintext

    def test_encrypt_empty_string(self, set_master_key):
        ch = set_master_key
        assert ch.encrypt('') == ''
        assert ch.encrypt(None) is None

    def test_decrypt_empty_string(self, set_master_key):
        ch = set_master_key
        assert ch.decrypt('') == ''
        assert ch.decrypt(None) is None

    def test_decrypt_plaintext_fallback(self, set_master_key):
        ch = set_master_key
        # Decrypting unencrypted text should return it as-is
        assert ch.decrypt('not-encrypted') == 'not-encrypted'

    def test_encrypt_produces_different_ciphertext(self, set_master_key):
        ch = set_master_key
        # Each encrypt should produce different ciphertext (random nonce)
        e1 = ch.encrypt("same")
        e2 = ch.encrypt("same")
        assert e1 != e2
        assert ch.decrypt(e1) == "same"
        assert ch.decrypt(e2) == "same"

    def test_encrypt_json_roundtrip(self, set_master_key):
        ch = set_master_key
        obj = [{'email': 'a@b.com', 'phone': '555-1234'}]
        encrypted = ch.encrypt_json(obj)
        assert encrypted != json.dumps(obj)
        decrypted = ch.decrypt_json(encrypted)
        assert decrypted == obj

    def test_encrypt_json_none(self, set_master_key):
        ch = set_master_key
        assert ch.encrypt_json(None) is None
        assert ch.encrypt_json([]) == []

    def test_decrypt_json_legacy_plaintext(self, set_master_key):
        ch = set_master_key
        raw = json.dumps([{'name': 'test'}])
        result = ch.decrypt_json(raw)
        assert result == [{'name': 'test'}]

    def test_decrypt_json_none(self, set_master_key):
        ch = set_master_key
        assert ch.decrypt_json(None) is None
        assert ch.decrypt_json('') is None


# ── Per-client key management ──

class TestClientKeyManagement:
    def test_generate_and_unwrap_client_key(self, set_master_key):
        ch = set_master_key
        encrypted_key = ch.generate_client_key()
        assert encrypted_key
        assert isinstance(encrypted_key, str)
        raw_key = ch.unwrap_client_key(encrypted_key)
        assert raw_key is not None
        assert len(raw_key) == 32  # 256-bit key

    def test_unwrap_none_returns_none(self, set_master_key):
        ch = set_master_key
        assert ch.unwrap_client_key(None) is None
        assert ch.unwrap_client_key('') is None

    def test_different_clients_get_different_keys(self, set_master_key):
        ch = set_master_key
        k1 = ch.generate_client_key()
        k2 = ch.generate_client_key()
        assert k1 != k2
        assert ch.unwrap_client_key(k1) != ch.unwrap_client_key(k2)


# ── Client key encrypt/decrypt ──

class TestClientKeyEncryption:
    def test_client_encrypt_decrypt_roundtrip(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        plaintext = "sensitive@client.com"
        encrypted = ch.client_encrypt(ck, plaintext)
        assert encrypted != plaintext
        assert ch.client_decrypt(ck, encrypted) == plaintext

    def test_client_encrypt_none_key(self, set_master_key):
        ch = set_master_key
        # No key → pass through
        assert ch.client_encrypt(None, "hello") == "hello"
        assert ch.client_decrypt(None, "hello") == "hello"

    def test_client_encrypt_empty_value(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        assert ch.client_encrypt(ck, '') == ''
        assert ch.client_encrypt(ck, None) is None

    def test_client_decrypt_falls_back_to_master_key(self, set_master_key):
        ch = set_master_key
        # Encrypt with master key
        master_encrypted = ch.encrypt("legacy-data")
        # Try to decrypt with a client key — should fall back to master key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        result = ch.client_decrypt(ck, master_encrypted)
        assert result == "legacy-data"

    def test_client_decrypt_falls_back_to_plaintext(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        # Unencrypted text returns as-is
        assert ch.client_decrypt(ck, "plain-text") == "plain-text"

    def test_client_encrypt_json_roundtrip(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        obj = {'firstName': 'John', 'email': 'j@test.com'}
        encrypted = ch.client_encrypt_json(ck, obj)
        assert ch.client_decrypt_json(ck, encrypted) == obj

    def test_client_decrypt_json_legacy(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        raw_json = json.dumps([{'name': 'test'}])
        result = ch.client_decrypt_json(ck, raw_json)
        assert result == [{'name': 'test'}]

    def test_cross_client_isolation(self, set_master_key):
        ch = set_master_key
        ck1 = ch.unwrap_client_key(ch.generate_client_key())
        ck2 = ch.unwrap_client_key(ch.generate_client_key())
        encrypted = ch.client_encrypt(ck1, "secret")
        # Decrypt with wrong client key should not return plaintext
        result = ch.client_decrypt(ck2, encrypted)
        # It may fall back to master key or return ciphertext — but NOT "secret"
        # Actually client_decrypt tries master key fallback, which also won't work
        # So it returns the ciphertext as-is
        assert result != "secret" or result == encrypted


# ── S3 body encryption ──

class TestS3BodyEncryption:
    def test_encrypt_decrypt_s3_body_text(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        original = "# Client Config\nCompany: Test Corp"
        encrypted = ch.encrypt_s3_body(ck, original)
        assert isinstance(encrypted, bytes)
        assert encrypted.startswith(b'ENC:')
        decrypted = ch.decrypt_s3_body(ck, encrypted)
        assert decrypted == original

    def test_decrypt_s3_body_unencrypted(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        raw = b"just plain text"
        result = ch.decrypt_s3_body(ck, raw)
        assert result == "just plain text"

    def test_encrypt_s3_body_no_key(self, set_master_key):
        ch = set_master_key
        body = "plain content"
        result = ch.encrypt_s3_body(None, body)
        assert result == body.encode('utf-8')

    def test_decrypt_s3_body_no_key(self, set_master_key):
        ch = set_master_key
        body = b"ENC:something"
        # No key — returns without the marker
        result = ch.decrypt_s3_body(None, body)
        assert result == "something"

    def test_encrypt_decrypt_s3_bytes(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        original = b'\x89PNG\r\n\x1a\n' + os.urandom(100)
        encrypted = ch.encrypt_s3_bytes(ck, original)
        assert encrypted.startswith(b'ENCB:')
        decrypted = ch.decrypt_s3_bytes(ck, encrypted)
        assert decrypted == original

    def test_decrypt_s3_bytes_unencrypted(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        raw = b'\x89PNG raw data'
        assert ch.decrypt_s3_bytes(ck, raw) == raw

    def test_encrypt_s3_bytes_no_key(self, set_master_key):
        ch = set_master_key
        data = b'binary data'
        assert ch.encrypt_s3_bytes(None, data) == data

    def test_empty_body_handling(self, set_master_key):
        ch = set_master_key
        ck = ch.unwrap_client_key(ch.generate_client_key())
        assert ch.encrypt_s3_body(ck, '') == b''
        assert ch.encrypt_s3_body(ck, None) == b''
        assert ch.decrypt_s3_body(ck, b'') == ''
        assert ch.decrypt_s3_body(ck, None) == ''


# ── Search hash ──

class TestSearchHash:
    def test_search_hash_deterministic(self, set_master_key):
        ch = set_master_key
        h1 = ch.search_hash("Test@Example.com")
        h2 = ch.search_hash("test@example.com")
        assert h1 == h2

    def test_search_hash_strips_whitespace(self, set_master_key):
        ch = set_master_key
        h1 = ch.search_hash("  test@example.com  ")
        h2 = ch.search_hash("test@example.com")
        assert h1 == h2

    def test_search_hash_empty(self, set_master_key):
        ch = set_master_key
        assert ch.search_hash('') == ''
        assert ch.search_hash(None) == ''

    def test_search_hash_length(self, set_master_key):
        ch = set_master_key
        h = ch.search_hash("test@example.com")
        assert len(h) == 64  # SHA-256 hex


# ── Pass-through mode (no key) ──

class TestPassthroughMode:
    def test_no_master_key_passthrough(self, set_master_key, monkeypatch):
        ch = set_master_key
        monkeypatch.setattr(ch, 'AES_MASTER_KEY', '')
        assert ch.encrypt("hello") == "hello"
        assert ch.decrypt("hello") == "hello"
        assert ch.encrypt_json([1, 2]) == json.dumps([1, 2])
