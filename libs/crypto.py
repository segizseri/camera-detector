import os
import base64
from cryptography.fernet import Fernet

def get_encryption_key() -> bytes:
    key_str = os.getenv("ENCRYPTION_KEY")
    if not key_str:
        # Generate a temporary key for dev if none provided
        key = Fernet.generate_key()
        os.environ["ENCRYPTION_KEY"] = key.decode("utf-8")
        return key
    
    # Try padding logic if necessary, here we assume padded urlsafe base64
    return key_str.encode("utf-8")

_fernet = Fernet(get_encryption_key())

def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return _fernet.encrypt(password.encode("utf-8")).decode("utf-8")

def decrypt_password(encrypted_password: str) -> str:
    if not encrypted_password:
        return ""
    try:
        return _fernet.decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
    except Exception as e:
        print(f"Decryption failed: {e}")
        return ""
