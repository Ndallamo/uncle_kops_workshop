#!/usr/bin/env python
"""Standalone helper to decrypt a base64 AES-GCM blob produced by EncryptedTextField.
Usage:
    python tools/decrypt_blob.py <base64_blob> <base64_key>

Or run interactively and paste values.
"""
import sys
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def decrypt_blob(blob_b64, key_b64):
    key = base64.b64decode(key_b64)
    data = base64.b64decode(blob_b64)
    nonce = data[:12]
    ct = data[12:]
    aesgcm = AESGCM(key)
    pt = aesgcm.decrypt(nonce, ct, None)
    return pt.decode('utf-8')


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        blob = sys.argv[1]
        key = sys.argv[2]
    else:
        blob = input('Base64 blob: ').strip()
        key = input('Base64 key: ').strip()

    try:
        print(decrypt_blob(blob, key))
    except Exception as e:
        print('Decryption failed:', e)
        sys.exit(2)
