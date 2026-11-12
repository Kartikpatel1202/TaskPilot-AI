"""Application configuration loaded from environment variables / `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"
SERVICE_NAME = "taskpilot-backend"
# Resolve `.env` relative to the backend folder so the working directory doesn't matter.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Typed runtime settings. Every tunable lives here — nothing is hardcoded elsewhere."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TaskPilot AI"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Comma-separated list of allowed origins. Kept as a raw string so that
    # pydantic-settings does not try to JSON-decode it.
    cors_origins: str = "http://localhost:3000"

    enable_demo_endpoints: bool = True
    max_command_length: int = Field(default=4000, ge=1, le=4000)
    websocket_max_connections: int = Field(default=10, ge=1)
    # Raised from 100 in Phase 3: browser execution emits several events per step.
    telemetry_history_limit: int = Field(default=500, ge=1, le=10_000)

    # Supporting settings (sensible defaults, overridable)
    assistant_name: str = "Kamlesh Bhai"
    websocket_send_queue_size: int = Field(default=256, ge=8)
    websocket_heartbeat_seconds: int = Field(default=25, ge=5)
    websocket_max_message_bytes: int = Field(default=4096, ge=256)
    max_tracked_sessions: int = Field(default=200, ge=1)
    max_tasks_in_memory: int = Field(default=1000, ge=1)
    demo_event_delay_ms: int = Field(default=450, ge=0, le=10_000)
    demo_approval_ttl_seconds: int = Field(default=120, ge=1)
    approval_sweep_interval_seconds: float = Field(default=5.0, gt=0)

    # ---------------------------------------------------------------- Phase 2: agent
    # auto = Anthropic or OpenAI when its API key is set, otherwise the offline rule-based planner — which the
    # dashboard then labels clearly with setup instructions (never presented as AI).
    agent_provider: Literal["auto", "mock", "openai", "anthropic"] = "mock"
    # Optional override; empty means "use the provider-specific model below".
    agent_model: str = ""
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Server-side refusal fallback routing on the Claude API (beta). Disable if not wanted.
    anthropic_server_fallbacks: bool = True

    agent_request_timeout_seconds: float = Field(default=40, gt=0, le=600)
    # Reasoning models think before answering, so a low cap truncates JSON output.
    agent_max_output_tokens: int = Field(default=16000, ge=256, le=64000)
    agent_max_retries: int = Field(default=2, ge=0, le=5)
    agent_retry_base_delay_seconds: float = Field(default=0.75, ge=0, le=30)
    agent_max_plan_steps: int = Field(default=25, ge=1, le=50)
    agent_planning_enabled: bool = True
    # Phase 3: plans may be executed in a real browser after an explicit "Run Plan".
    agent_browser_execution_enabled: bool = True
    agent_allow_mock_in_production: bool = False
    # Artificial per-call latency for the mock provider so planning stages are visible in the UI.
    agent_mock_latency_ms: int = Field(default=350, ge=0, le=10_000)

    planner_concurrency: int = Field(default=3, ge=1, le=32)
    planner_queue_size: int = Field(default=50, ge=1, le=10_000)

    memory_max_turns: int = Field(default=20, ge=2, le=200)
    memory_max_characters: int = Field(default=12_000, ge=500, le=200_000)
    memory_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)
    memory_max_sessions: int = Field(default=1000, ge=1, le=100_000)

    # ---------------------------------------------------------------- Phase 3: browser
    browser_engine: Literal["chromium"] = "chromium"
    browser_headless: bool = True
    browser_start_timeout_seconds: float = Field(default=30, ge=5, le=180)
    browser_action_timeout_ms: int = Field(default=10_000, ge=1_000, le=60_000)
    browser_navigation_timeout_ms: int = Field(default=30_000, ge=5_000, le=120_000)
    browser_max_sessions: int = Field(default=5, ge=1, le=20)
    browser_max_pages_per_session: int = Field(default=3, ge=1, le=10)
    browser_session_idle_timeout_minutes: int = Field(default=30, ge=1, le=24 * 60)
    browser_viewport_width: int = Field(default=1440, ge=800, le=2560)
    browser_viewport_height: int = Field(default=900, ge=600, le=1600)
    # Bounded: the live preview never exceeds 5 frames per second.
    browser_screenshot_fps: float = Field(default=1.0, ge=0.2, le=5.0)
    browser_screenshot_quality: int = Field(default=55, ge=20, le=90)
    browser_max_frame_bytes: int = Field(default=300_000, ge=20_000, le=2_000_000)
    browser_selector_max_attempts: int = Field(default=2, ge=1, le=4)
    # How long to wait when a site shows a security check (Cloudflare / CAPTCHA). TaskPilot never solves these;
    # with a visible browser you can complete it yourself in the window. Headless runs wait briefly only.
    browser_human_check_wait_seconds: int = Field(default=90, ge=0, le=600)
    # How the browser's network policy is enforced:
    #   route — every page/script/XHR is re-fetched by the server to check redirects (sites with bot protection,
    #           such as Blinkit, reject those requests and break);
    #   proxy — Chromium makes its own requests through a guard proxy (EGRESS_PROXY_URL, or a built-in local one)
    #           that checks every connection and redirect hop against the address it actually connects to.
    browser_network_guard: Literal["route", "proxy"] = "route"
    browser_selector_min_confidence: float = Field(default=0.82, ge=0.5, le=1.0)
    browser_action_max_retries: int = Field(default=1, ge=0, le=3)
    browser_allowed_domains: str = "blinkit.com,amazon.in,youtube.com,google.com"
    # Development/test only: exact origins (e.g. http://127.0.0.1:8000) for local fixture sites.
    browser_test_allowed_origins: str = ""
    # Development/test only: serve the local demo shop fixture at /dev/fixtures/shop/.
    browser_dev_fixtures_enabled: bool = False
    browser_persist_sessions: bool = False
    browser_state_encryption_key: SecretStr | None = None
    browser_state_directory: str = "./runtime/browser_state"

    execution_queue_size: int = Field(default=20, ge=1, le=500)
    execution_concurrency: int = Field(default=3, ge=1, le=10)
    # Phase 3 supports exactly one active execution per session.
    execution_max_tasks_per_session: int = Field(default=1, ge=1, le=1)
    execution_approval_ttl_seconds: int = Field(default=300, ge=10, le=3600)

    # ---------------------------------------------------------------- Phase 4: commerce
    commerce_enabled: bool = True
    commerce_supported_platforms: str = "BLINKIT,AMAZON_IN"
    commerce_max_products_per_task: int = Field(default=20, ge=1, le=50)
    commerce_max_search_results: int = Field(default=30, ge=1, le=100)
    commerce_exact_match_threshold: float = Field(default=0.92, gt=0, le=1)
    commerce_acceptable_match_threshold: float = Field(default=0.80, gt=0, le=1)
    commerce_ambiguity_margin: float = Field(default=0.05, ge=0, le=0.5)
    commerce_max_price_change_percent: float = Field(default=5, ge=0, le=100)
    commerce_search_timeout_seconds: float = Field(default=20, ge=2, le=120)
    commerce_cart_verification_timeout_seconds: float = Field(default=15, ge=2, le=120)
    commerce_max_search_attempts: int = Field(default=3, ge=1, le=5)
    commerce_max_packs_per_item: int = Field(default=6, ge=1, le=24)
    commerce_selection_timeout_seconds: int = Field(default=300, ge=10, le=3600)
    # Purchase controls (validated below: final approval always on, automated prepaid payment always off).
    commerce_require_final_purchase_approval: bool = True
    commerce_allow_cod_order_after_approval: bool = True
    commerce_automated_prepaid_payment: bool = False
    commerce_require_cart_verification: bool = True
    # Development/test only.
    commerce_enable_fixtures: bool = False
    commerce_enable_public_smoke_tests: bool = False

    # ---------------------------------------------------------------- Phase 5: multi-domain integrations
    integrations_enabled: bool = True
    youtube_enabled: bool = True
    gmail_enabled: bool = True
    google_calendar_enabled: bool = True
    file_download_enabled: bool = True
    integration_allowed_domains: str = "www.youtube.com,youtube.com,youtu.be,mail.google.com,calendar.google.com"
    youtube_max_search_results: int = Field(default=10, ge=1, le=20)
    youtube_search_timeout_seconds: float = Field(default=20, ge=2, le=120)
    youtube_playback_timeout_seconds: float = Field(default=20, ge=2, le=120)
    gmail_max_recipients: int = Field(default=20, ge=1, le=50)
    gmail_max_draft_length: int = Field(default=12_000, ge=100, le=50_000)
    gmail_automated_send_enabled: bool = False
    gmail_attachment_enabled: bool = False
    calendar_default_timezone: str = "Asia/Kolkata"
    calendar_default_duration_minutes: int = Field(default=0, ge=0, le=480)  # 0 = always ask
    calendar_max_attendees: int = Field(default=50, ge=0, le=200)
    calendar_require_creation_approval: bool = True
    calendar_allow_automatic_event_deletion: bool = False
    file_download_max_size_mb: int = Field(default=25, ge=1, le=500)
    file_download_max_concurrent: int = Field(default=2, ge=1, le=8)
    file_download_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    file_download_storage: str = "./runtime/downloads"
    file_download_allowed_extensions: str = "pdf,txt,csv,png,jpg,jpeg,webp,docx,xlsx,pptx"
    # Hosts files may be fetched from (exact or subdomain). Empty = only dev/test fixture origins.
    file_download_allowed_domains: str = ""
    file_download_allow_archives: bool = False
    file_download_allow_executables: bool = False
    file_download_max_storage_mb: int = Field(default=500, ge=10, le=10_000)
    workflow_max_steps: int = Field(default=30, ge=1, le=60)
    workflow_max_domains: int = Field(default=5, ge=1, le=6)
    workflow_max_concurrency: int = Field(default=2, ge=1, le=8)
    workflow_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    # Development/test only: local YouTube/Gmail/Calendar/download fixture sites.
    integration_enable_fixtures: bool = False

    # ---------------------------------------------------------------- Phase 6: persistence
    # SQLite is for local development/tests only; production requires PostgreSQL (postgresql+asyncpg://).
    database_url: str = "sqlite+aiosqlite:///./runtime/taskpilot.db"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10, gt=0, le=120)
    database_echo: bool = False
    # Create tables on startup (dev/test). Production runs `alembic upgrade head` instead.
    database_auto_create: bool = True
    redis_url: str = ""  # empty = in-process queue/locks/rate limits (single-process development only)
    queue_backend: Literal["inprocess", "redis"] = "inprocess"
    queue_max_depth: int = Field(default=200, ge=1, le=100_000)
    queue_max_attempts: int = Field(default=3, ge=1, le=10)
    queue_visibility_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    worker_heartbeat_seconds: int = Field(default=10, ge=1, le=300)
    recovery_on_startup: bool = True

    # ---------------------------------------------------------------- Phase 6: authentication
    auth_mode: Literal["local", "oidc"] = "local"
    auth_required: bool = False
    allow_dev_auth_bypass: bool = True
    app_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_token_ttl_minutes: int = Field(default=15, ge=1, le=240)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=90)
    password_hash_scheme: Literal["argon2id"] = "argon2id"
    password_min_length: int = Field(default=12, ge=8, le=128)
    session_cookie_secure: bool = False
    session_cookie_http_only: bool = True
    session_cookie_samesite: Literal["lax", "strict"] = "lax"
    csrf_protection_enabled: bool = True
    registration_enabled: bool = True
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    # Bootstrap the first OWNER account (only when no user exists yet).
    bootstrap_owner_email: str = ""
    bootstrap_owner_password: SecretStr | None = None

    # ---------------------------------------------------------------- Phase 6: rate limits
    rate_limit_enabled: bool = True
    api_rate_limit_per_minute: int = Field(default=120, ge=1)
    auth_login_attempts_per_minute: int = Field(default=5, ge=1)
    llm_requests_per_minute: int = Field(default=30, ge=1)
    planning_requests_per_minute: int = Field(default=20, ge=1)
    browser_actions_per_minute: int = Field(default=120, ge=1)
    commerce_searches_per_minute: int = Field(default=20, ge=1)
    file_downloads_per_hour: int = Field(default=20, ge=1)
    max_websocket_connections_per_user: int = Field(default=5, ge=1)
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1, le=100)
    circuit_breaker_recovery_seconds: float = Field(default=30, gt=0, le=3600)

    # ---------------------------------------------------------------- Phase 6: self-correction
    self_correction_enabled: bool = True
    self_correction_max_attempts: int = Field(default=2, ge=0, le=5)
    self_correction_max_replans: int = Field(default=2, ge=0, le=5)
    self_correction_max_time_seconds: float = Field(default=60, gt=0, le=600)
    selector_cache_ttl_minutes: int = Field(default=30, ge=1, le=1440)
    dom_mutation_buffer_size: int = Field(default=100, ge=10, le=1000)

    # ---------------------------------------------------------------- Phase 6: network egress
    # Outbound proxy (e.g. http://egress:3128) that enforces the DNS/IP policy at the network level.
    egress_proxy_url: str = ""
    require_egress_proxy: bool = False

    # ---------------------------------------------------------------- Phase 6: files, observability
    file_storage_quota_mb_per_user: int = Field(default=200, ge=1, le=100_000)
    file_max_count_per_user: int = Field(default=200, ge=1, le=100_000)
    malware_scanner: Literal["none", "clamav"] = "none"
    clamav_host: str = "clamav"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None
    audit_retention_days: int = Field(default=365, ge=1, le=3650)
    llm_daily_token_budget: int = Field(default=2_000_000, ge=1)
    llm_input_cost_per_million: float = Field(default=0.0, ge=0)
    llm_output_cost_per_million: float = Field(default=0.0, ge=0)

    @field_validator("openai_api_key", "anthropic_api_key", "browser_state_encryption_key", "app_secret_key",
                     "bootstrap_owner_password", "metrics_token", mode="before")
    @classmethod
    def _blank_secret_is_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _validate_agent(self) -> "Settings":
        local = self.app_env in ("development", "test")
        if self.browser_test_allowed_origins.strip() and not local:
            raise ValueError("BROWSER_TEST_ALLOWED_ORIGINS is only allowed when APP_ENV is development or test.")
        if self.browser_dev_fixtures_enabled and not local:
            raise ValueError("BROWSER_DEV_FIXTURES_ENABLED is only allowed when APP_ENV is development or test.")
        for origin in self.browser_test_origin_list:
            if not origin.startswith(("http://", "https://")) or origin.count("/") != 2:
                raise ValueError(f"BROWSER_TEST_ALLOWED_ORIGINS entries must be bare origins, got {origin!r}.")
        if self.browser_persist_sessions:
            if self.browser_state_encryption_key is None:
                raise ValueError("BROWSER_PERSIST_SESSIONS=true requires BROWSER_STATE_ENCRYPTION_KEY.")
            try:
                from cryptography.fernet import Fernet

                Fernet(self.browser_state_encryption_key.get_secret_value().encode())
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    "BROWSER_STATE_ENCRYPTION_KEY must be a Fernet key "
                    "(python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")."
                ) from exc
        if self.commerce_enable_fixtures and not local:
            raise ValueError("COMMERCE_ENABLE_FIXTURES is only allowed when APP_ENV is development or test.")
        if not self.commerce_require_final_purchase_approval:
            raise ValueError("COMMERCE_REQUIRE_FINAL_PURCHASE_APPROVAL cannot be disabled.")
        if self.commerce_automated_prepaid_payment:
            raise ValueError("COMMERCE_AUTOMATED_PREPAID_PAYMENT is not supported; prepaid payments are always completed by you.")
        if not self.commerce_require_cart_verification:
            raise ValueError("COMMERCE_REQUIRE_CART_VERIFICATION cannot be disabled.")
        if self.commerce_acceptable_match_threshold > self.commerce_exact_match_threshold:
            raise ValueError("COMMERCE_ACCEPTABLE_MATCH_THRESHOLD must not exceed COMMERCE_EXACT_MATCH_THRESHOLD.")
        unknown = set(self.commerce_platform_list) - {"BLINKIT", "AMAZON_IN"}
        if unknown:
            raise ValueError(f"Unsupported COMMERCE_SUPPORTED_PLATFORMS: {sorted(unknown)}.")
        if self.integration_enable_fixtures and not local:
            raise ValueError("INTEGRATION_ENABLE_FIXTURES is only allowed when APP_ENV is development or test.")
        if self.gmail_automated_send_enabled:
            raise ValueError("GMAIL_AUTOMATED_SEND_ENABLED is not supported: TaskPilot only saves drafts; you send them yourself.")
        if self.gmail_attachment_enabled:
            raise ValueError("GMAIL_ATTACHMENT_ENABLED is not supported in this phase.")
        if not self.calendar_require_creation_approval:
            raise ValueError("CALENDAR_REQUIRE_CREATION_APPROVAL cannot be disabled.")
        if self.calendar_allow_automatic_event_deletion:
            raise ValueError("CALENDAR_ALLOW_AUTOMATIC_EVENT_DELETION is not supported.")
        if self.file_download_allow_executables:
            raise ValueError("FILE_DOWNLOAD_ALLOW_EXECUTABLES is not supported; executables are always blocked.")
        if self.file_download_allow_archives:
            raise ValueError("FILE_DOWNLOAD_ALLOW_ARCHIVES is not supported yet (archives need separate inspection).")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(self.calendar_default_timezone)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"CALENDAR_DEFAULT_TIMEZONE must be a valid IANA timezone, got {self.calendar_default_timezone!r}.") from exc
        blocked = {"exe", "msi", "bat", "cmd", "ps1", "sh", "dll", "scr", "com", "jar", "vbs", "js", "zip", "rar", "7z", "tar", "gz"}
        bad = set(self.file_download_extension_list) & blocked
        if bad:
            raise ValueError(f"FILE_DOWNLOAD_ALLOWED_EXTENSIONS may not include {sorted(bad)}.")
        if self.workflow_max_concurrency > self.execution_concurrency:
            raise ValueError("WORKFLOW_MAX_CONCURRENCY must not exceed EXECUTION_CONCURRENCY.")
        if self.file_download_max_size_mb > self.file_download_max_storage_mb:
            raise ValueError("FILE_DOWNLOAD_MAX_SIZE_MB must not exceed FILE_DOWNLOAD_MAX_STORAGE_MB.")
        if not self.browser_allowed_domain_list:
            raise ValueError("BROWSER_ALLOWED_DOMAINS must list at least one domain.")
        if self.agent_provider == "openai" and self.openai_api_key is None:
            raise ValueError("AGENT_PROVIDER=openai requires OPENAI_API_KEY to be set.")
        if self.agent_provider == "anthropic" and self.anthropic_api_key is None:
            raise ValueError("AGENT_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set.")
        if self.agent_provider not in ("mock", "auto") and self.agent_model.startswith("taskpilot-mock"):
            raise ValueError("AGENT_MODEL names the mock model but AGENT_PROVIDER is not 'mock'. Clear AGENT_MODEL.")
        self._validate_production()
        if self.effective_agent_provider == "mock" and self.app_env == "production" and not self.agent_allow_mock_in_production:
            raise ValueError(
                "AGENT_PROVIDER=mock is not allowed in production. Configure a real provider "
                "or set AGENT_ALLOW_MOCK_IN_PRODUCTION=true explicitly."
            )
        return self

    def _validate_production(self) -> None:
        """Phase 6: production refuses every unsafe development convenience."""
        if self.auth_required and self.app_secret_key is None:
            raise ValueError("AUTH_REQUIRED=true needs APP_SECRET_KEY (at least 32 random characters).")
        if self.app_secret_key is not None and len(self.app_secret_key.get_secret_value()) < 32:
            raise ValueError("APP_SECRET_KEY must be at least 32 characters.")
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_client_id):
            raise ValueError("AUTH_MODE=oidc requires OIDC_ISSUER and OIDC_CLIENT_ID.")
        if self.queue_backend == "redis" and not self.redis_url:
            raise ValueError("QUEUE_BACKEND=redis requires REDIS_URL.")
        if self.require_egress_proxy and not self.egress_proxy_url:
            raise ValueError("REQUIRE_EGRESS_PROXY=true requires EGRESS_PROXY_URL.")
        if self.app_env != "production":
            return
        problems = []
        if not self.auth_required or self.allow_dev_auth_bypass:
            problems.append("AUTH_REQUIRED=true and ALLOW_DEV_AUTH_BYPASS=false are mandatory")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            problems.append("DATABASE_URL must be PostgreSQL (postgresql+asyncpg://…); SQLite is development-only")
        if self.database_auto_create:
            problems.append("DATABASE_AUTO_CREATE must be false (run `alembic upgrade head`)")
        if not self.redis_url or self.queue_backend != "redis":
            problems.append("REDIS_URL and QUEUE_BACKEND=redis are required")
        if not self.session_cookie_secure or not self.csrf_protection_enabled:
            problems.append("SESSION_COOKIE_SECURE=true and CSRF_PROTECTION_ENABLED=true are required (TLS)")
        if self.enable_demo_endpoints:
            problems.append("ENABLE_DEMO_ENDPOINTS must be false")
        if not self.require_egress_proxy:
            problems.append("REQUIRE_EGRESS_PROXY=true (controlled outbound network) is required")
        if self.browser_persist_sessions:
            problems.append("BROWSER_PERSIST_SESSIONS must be false")
        if not self.rate_limit_enabled:
            problems.append("RATE_LIMIT_ENABLED must be true")
        if not self.browser_headless:
            problems.append("BROWSER_HEADLESS must be true (a visible browser is for local development only)")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems) + ".")

    @property
    def auth_enforced(self) -> bool:
        return self.auth_required or self.app_env in ("staging", "production")

    @property
    def browser_allowed_domain_list(self) -> list[str]:
        domains = []
        extra = self.integration_allowed_domains.split(",") if self.integrations_enabled else []
        for raw in [*self.browser_allowed_domains.split(","), *extra]:
            domain = raw.strip().lower().rstrip(".").removeprefix("www.")
            if domain and "/" not in domain and ":" not in domain and "*" not in domain:
                domains.append(domain)
        return list(dict.fromkeys(domains))

    @property
    def commerce_platform_list(self) -> list[str]:
        return [p.strip().upper() for p in self.commerce_supported_platforms.split(",") if p.strip()]

    @property
    def file_download_extension_list(self) -> list[str]:
        return [e.strip().lower().lstrip(".") for e in self.file_download_allowed_extensions.split(",") if e.strip()]

    @property
    def file_download_domain_list(self) -> list[str]:
        return [d.strip().lower().removeprefix("www.") for d in self.file_download_allowed_domains.split(",") if d.strip()]

    @property
    def integration_domain_list(self) -> list[str]:
        return [d.strip().lower().rstrip(".") for d in self.integration_allowed_domains.split(",") if d.strip()]

    @property
    def browser_test_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/").lower() for o in self.browser_test_allowed_origins.split(",") if o.strip()]

    @property
    def effective_agent_provider(self) -> str:
        """The provider actually used. `auto` prefers Anthropic, then OpenAI, then the offline planner."""
        if self.agent_provider != "auto":
            return self.agent_provider
        if self.anthropic_api_key is not None:
            return "anthropic"
        if self.openai_api_key is not None:
            return "openai"
        return "mock"

    @property
    def planner_setup_hint(self) -> str | None:
        """Shown in the dashboard when no AI planner is active (no secrets, just what to configure)."""
        if self.effective_agent_provider != "mock":
            return None
        return ("AI planning is off: no LLM API key is configured, so Kamlesh Bhai uses the offline rule-based planner "
                "(limited understanding, canned chat). To enable AI, set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in "
                "backend/.env with AGENT_PROVIDER=auto and restart the backend.")

    @property
    def resolved_agent_model(self) -> str:
        if self.effective_agent_provider == "mock":
            return "taskpilot-mock-v1"
        if self.agent_model:
            return self.agent_model
        return self.openai_model if self.effective_agent_provider == "openai" else self.anthropic_model

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        # Credentialed requests must never be combined with a wildcard origin.
        return [o for o in origins if o != "*"]

    @property
    def demo_endpoints_active(self) -> bool:
        """Demo endpoints are only ever available in development/test."""
        return self.enable_demo_endpoints and self.app_env in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
