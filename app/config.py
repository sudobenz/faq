import os
from dataclasses import dataclass


def csv_set(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Centre d'aide")
    app_url: str = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")
    secret_key: str = os.getenv("SECRET_KEY", "development-only-change-me")
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://faquser:faqpass@localhost:5432/faqdb")
    oidc_discovery_url: str = os.getenv("OIDC_DISCOVERY_URL", "")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")
    oidc_scopes: str = os.getenv("OIDC_SCOPES", "openid profile email")
    oidc_button_label: str = os.getenv("OIDC_BUTTON_LABEL", "Connexion entreprise")
    glpi_api_token: str = os.getenv("GLPI_API_TOKEN", "").strip()
    glpi_api_max_results: int = max(1, min(12, int(os.getenv("GLPI_API_MAX_RESULTS", "8"))))
    analytics_enabled: bool = os.getenv("ANALYTICS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "oui"}
    analytics_require_consent: bool = os.getenv("ANALYTICS_REQUIRE_CONSENT", "true").strip().lower() in {"1", "true", "yes", "oui"}
    analytics_service_claim: str = os.getenv("ANALYTICS_SERVICE_CLAIM", "department").strip() or "department"
    analytics_salt: str = os.getenv("ANALYTICS_SALT", "").strip()
    analytics_retention_days: int = max(30, int(os.getenv("ANALYTICS_RETENTION_DAYS", "365")))
    auth_mode: str = os.getenv("AUTH_MODE", "oidc").strip().lower()
    local_admin_username: str = os.getenv("LOCAL_ADMIN_USERNAME", "faqadmin").strip().lower()
    local_admin_password: str = os.getenv("LOCAL_ADMIN_PASSWORD", "")
    admin_emails: set[str] = None
    admin_groups: set[str] = None

    def __post_init__(self):
        if self.auth_mode not in {"oidc", "local", "both"}:
            raise ValueError("AUTH_MODE doit valoir oidc, local ou both.")
        object.__setattr__(self, "admin_emails", csv_set(os.getenv("ADMIN_EMAILS", "")))
        object.__setattr__(self, "admin_groups", csv_set(os.getenv("ADMIN_GROUPS", "faq-admins")))

    @property
    def oidc_auth_enabled(self) -> bool:
        return self.auth_mode in {"oidc", "both"}

    @property
    def local_auth_enabled(self) -> bool:
        return self.auth_mode in {"local", "both"}


settings = Settings()
