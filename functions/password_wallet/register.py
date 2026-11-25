import os
from cryptography.fernet import Fernet
from supabase import Client, create_client

_FERNET_KEY = os.getenv("VAULT_ENCRYPTION_KEY")
_SUPABASE_URL = os.getenv("SUPABASE_URL")
_SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not _FERNET_KEY:
    raise RuntimeError("Missing VAULT_ENCRYPTION_KEY in environment.")
if not _SUPABASE_URL or not _SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment.")

_fernet = Fernet(_FERNET_KEY.encode("utf-8"))
_supabase: Client = create_client(_SUPABASE_URL, _SUPABASE_KEY)


def encrypt_value(plain_text: str) -> str:
    return _fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def save_password_entry(
    user_id: int,
    service_name: str,
    password: str,
    username_or_email: str | None = None,
    notes: str | None = None,
) -> dict:
    payload = {
        "user_id": user_id,
        "service_name": service_name.strip(),
        "username_or_email": username_or_email.strip() if username_or_email else None,
        "encrypted_password": encrypt_value(password),
        "notes": notes.strip() if notes else None,
    }
    res = _supabase.table("vault_passwords").insert(payload).execute()
    return res.data[0]


def save_totp_entry(
    user_id: int,
    service_name: str,
    totp_secret: str,
    account_label: str | None = None,
    notes: str | None = None,
) -> dict:
    cleaned_secret = totp_secret.replace(" ", "").strip().upper()
    payload = {
        "user_id": user_id,
        "service_name": service_name.strip(),
        "account_label": account_label.strip() if account_label else None,
        "encrypted_totp_secret": encrypt_value(cleaned_secret),
        "notes": notes.strip() if notes else None,
    }
    res = _supabase.table("vault_totp").insert(payload).execute()
    return res.data[0]


def save_recovery_entry(
    user_id: int,
    service_name: str,
    recovery_keys: str,
    notes: str | None = None,
) -> dict:
    payload = {
        "user_id": user_id,
        "service_name": service_name.strip(),
        "encrypted_recovery_keys": encrypt_value(recovery_keys.strip()),
        "notes": notes.strip() if notes else None,
    }
    res = _supabase.table("vault_recovery").insert(payload).execute()
    return res.data[0]