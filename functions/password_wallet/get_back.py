import os
import time
from cryptography.fernet import Fernet
import pyotp
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

GRACE_WINDOW_SECONDS = 8


def decrypt_value(cipher_text: str) -> str:
    return _fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")


def get_password_entries(user_id: int, service_query: str | None = None) -> list[dict]:
    query = _supabase.table("vault_passwords").select("*").eq("user_id", user_id)
    if service_query:
        query = query.ilike("service_name", f"%{service_query.strip()}%")
    rows = query.order("created_at", desc=True).execute().data or []

    results = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "service_name": row["service_name"],
                "username_or_email": row.get("username_or_email"),
                "password": decrypt_value(row["encrypted_password"]),
                "notes": row.get("notes"),
            }
        )
    return results


def get_totp_entries(
    user_id: int,
    service_query: str | None = None,
    grace_seconds: int = GRACE_WINDOW_SECONDS,
) -> dict:
    query = _supabase.table("vault_totp").select("*").eq("user_id", user_id)
    if service_query:
        query = query.ilike("service_name", f"%{service_query.strip()}%")
    rows = query.order("created_at", desc=True).execute().data or []

    now_sec = int(time.time())
    current_expires_at = ((now_sec // 30) + 1) * 30
    remaining = current_expires_at - now_sec
    use_next = remaining <= grace_seconds
    next_expires_at = current_expires_at + 30
    active_expires_at = next_expires_at if use_next else current_expires_at

    items = []
    for row in rows:
        base_item = {
            "id": row["id"],
            "service_name": row["service_name"],
            "account_label": row.get("account_label"),
            "is_lookahead": use_next,
            "notes": row.get("notes"),
        }
        try:
            secret = decrypt_value(row["encrypted_totp_secret"]).replace(" ", "").upper()
            totp = pyotp.TOTP(secret)
            code = totp.at(current_expires_at + 1) if use_next else totp.now()
            items.append(
                {
                    **base_item,
                    "otp_code": code,
                    "code_label": "Next OTP" if use_next else "OTP",
                    "error": None,
                }
            )
        except Exception as exc:
            items.append(
                {
                    **base_item,
                    "otp_code": None,
                    "code_label": "Next OTP" if use_next else "OTP",
                    "error": str(exc),
                }
            )

    return {
        "items": items,
        "is_lookahead": use_next,
        "current_expires_at": current_expires_at,
        "expires_at": active_expires_at,
    }


def get_recovery_entries(user_id: int, service_query: str | None = None) -> list[dict]:
    query = _supabase.table("vault_recovery").select("*").eq("user_id", user_id)
    if service_query:
        query = query.ilike("service_name", f"%{service_query.strip()}%")
    rows = query.order("created_at", desc=True).execute().data or []

    results = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "service_name": row["service_name"],
                "recovery_keys": decrypt_value(row["encrypted_recovery_keys"]),
                "notes": row.get("notes"),
            }
        )
    return results