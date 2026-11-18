import hashlib
import hmac
import secrets
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from .config import settings

# PBKDF2-HMAC-SHA256 permet de conserver un hachage robuste sans dépendance native
# supplémentaire. Le sel est aléatoire et stocké avec le hachage.
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000

oauth = OAuth()
_oidc_ready = bool(
    settings.oidc_auth_enabled
    and settings.oidc_discovery_url
    and settings.oidc_client_id
    and settings.oidc_client_secret
)
if _oidc_ready:
    oauth.register(
        name="oidc",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_discovery_url,
        client_kwargs={"scope": settings.oidc_scopes},
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return f"{_PASSWORD_SCHEME}${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != _PASSWORD_SCHEME:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def get_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    # Invalide immédiatement les sessions dont le mode d'authentification
    # vient d'être désactivé dans la configuration.
    auth_type = user.get("auth_type", "oidc")  # compatibilité des sessions OIDC antérieures
    if auth_type == "oidc" and not settings.oidc_auth_enabled:
        request.session.clear()
        return None
    if auth_type == "local" and not settings.local_auth_enabled:
        request.session.clear()
        return None
    return user


def _claim_values(value):
    if value is None:
        return set()
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, (list, tuple, set)):
        return {str(v).lower() for v in value}
    return set()


def is_admin(user: dict | None) -> bool:
    if not user:
        return False
    if user.get("auth_type") == "local" and user.get("is_local_admin") is True:
        return True
    email = str(user.get("email", "")).lower()
    if email and email in settings.admin_emails:
        return True
    groups = set()
    for claim in ("groups", "roles", "memberOf"):
        groups |= _claim_values(user.get(claim))
    return bool(groups & settings.admin_groups)


def oidc_configured() -> bool:
    return _oidc_ready


def local_auth_enabled() -> bool:
    return settings.local_auth_enabled
