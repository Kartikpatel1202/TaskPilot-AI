"""Dependency container wiring settings, transport, event generation and services."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from app.agent.intent_classifier import IntentClassifier
from app.agent.llm_runner import StructuredLLMRunner
from app.agent.memory import MemoryManager
from app.agent.orchestrator import AgentOrchestrator
from app.agent.plan_store import PlanStore
from app.agent.planner import Planner
from app.agent.providers import LLMProvider, create_provider
from app.agent.tools import ToolRegistry, build_default_registry
from app.agent.websites import demo_shop_website, register_website, unregister_website, DEMO_SHOP_KEY
from app.browser.controller import BrowserController
from app.browser.dom_inspector import DOMInspector
from app.browser.manager import BrowserManager
from app.browser.navigation_guard import NavigationGuard
from app.browser.screenshot_manager import ScreenshotManager
from app.browser.selector_resolver import SelectorResolver
from app.browser.session_store import SessionStore
from app.browser.stream_manager import BrowserStreamManager
from app.commerce.adapters.amazon_india import AmazonIndiaAdapter
from app.commerce.adapters.blinkit import BlinkitAdapter
from app.commerce.commerce_manager import CommerceManager
from app.commerce.commerce_planner import CommercePlanner
from app.commerce.registry import FIXTURE_KEYS, CommerceRegistry, fixture_binding, fixture_website
from app.config import Settings
from app.auth.authentication import AuthService
from app.auth.authorization import ResourceAuthorizer
from app.auth.sessions import SessionOwnership
from app.database.dependencies import Persistence
from app.database.session import Database
from app.integrations.files.scanner import ClamAVScanner, NullScanner
from app.observability.audit import AuditService
from app.observability.metrics import Metrics
from app.resilience.circuit_breaker import CircuitBreaker
from app.resilience.idempotency import ExecutionJournal
from app.resilience.rate_limiter import RateLimiter
from app.integrations.capability_registry import CapabilityRegistry
from app.integrations.files.downloader import FileDownloader
from app.integrations.files.storage import FileStore
from app.integrations.integration_manager import IntegrationManager
from app.integrations.integration_planner import IntegrationPlanner
from app.integrations.registry import FIXTURE_KEYS as INTEGRATION_FIXTURE_KEYS
from app.integrations.registry import IntegrationRegistry
from app.integrations.registry import fixture_binding as integration_fixture_binding
from app.integrations.registry import fixture_website as integration_fixture_website
from app.schemas.integration import DomainType
from app.services.integration_service import IntegrationService
from app.workflow.workflow_validator import validate_workflow
from app.services.commerce_service import CommerceService
from app.schemas.product import CommercePlatform
from app.core.execution_events import ExecutionEvents
from app.execution.approval_coordinator import ApprovalCoordinator
from app.execution.execution_manager import ExecutionManager
from app.services.browser_service import BrowserService
from app.services.execution_service import ExecutionService
from app.core.event_manager import EventManager
from app.dev.demo_events import DemoSimulator
from app.services.approval_service import ApprovalService
from app.services.planning_service import PlanningService
from app.services.task_service import TaskService
from app.websocket.manager import WebSocketManager


_log = logging.getLogger("taskpilot.maintenance")


@dataclass
class Container:
    settings: Settings
    ws_manager: WebSocketManager
    events: EventManager
    tasks: TaskService
    approvals: ApprovalService
    demo: DemoSimulator
    provider: LLMProvider
    registry: ToolRegistry
    memory: MemoryManager
    orchestrator: AgentOrchestrator
    planning: PlanningService
    browser: BrowserManager
    stream: BrowserStreamManager
    execution: ExecutionManager
    execution_service: ExecutionService
    browser_service: BrowserService
    commerce: CommerceManager | None
    commerce_registry: CommerceRegistry
    commerce_service: CommerceService
    integrations: IntegrationManager | None
    integration_service: IntegrationService
    capabilities: CapabilityRegistry
    # ---------------------------------------------------------------- Phase 6
    db: Database
    persistence: Persistence
    redis: Any
    rate_limiter: RateLimiter
    ownership: SessionOwnership
    auth: AuthService
    audit: AuditService
    metrics: Metrics
    breakers: dict[str, CircuitBreaker]
    store: PlanStore
    files: FileStore | None
    worker_id: str
    authorizer: Any = None
    preferences: Any = None
    recovery_report: Any = None
    background: list[Any] = field(default_factory=list)

    async def startup(self) -> None:
        """Database schema check, bootstrap owner, startup recovery (before traffic is served)."""
        s = self.settings
        if s.database_auto_create:
            await self.db.create_all()
        else:
            await _require_migrated(self.db)
        if s.bootstrap_owner_email and s.bootstrap_owner_password is not None:
            await self.auth.ensure_bootstrap_owner(s.bootstrap_owner_email, s.bootstrap_owner_password.get_secret_value())

    async def run_recovery(self) -> None:
        """After the planner/execution queues have started (recovery may re-submit planning jobs)."""
        if self.settings.recovery_on_startup:
            from app.resilience.recovery import recover

            self.recovery_report = await recover(self)

    async def run_maintenance(self) -> dict[str, int]:
        """Periodic cleanup (sweeper): expired downloads (disk + metadata) and expired conversation memory.
        Audit records are never deleted here. Each part is independent; one failing does not stop the others."""
        done: dict[str, int] = {}
        if self.files is not None:
            try:
                done["files_purged"] = self.files.purge_expired()
            except Exception:  # noqa: BLE001
                _log.exception("maintenance_files_failed")
        for name, job in (("file_records_expired", self.persistence.files.expire_overdue),
                          ("memory_turns_purged", self.persistence.conversations.purge_expired)):
            try:
                done[name] = await job()
            except Exception:  # noqa: BLE001
                _log.exception("maintenance_failed", extra={"job": name})
        return done

    async def shutdown(self) -> None:
        await self.persistence.drain()
        await self.db.dispose()
        if self.redis is not None:
            try:
                await self.redis.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _require_migrated(db: Database) -> None:
    from sqlalchemy import text

    try:
        async with db.engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("The database is not migrated. Run `alembic upgrade head` (DATABASE_AUTO_CREATE=false).") from exc
    if not version:
        raise RuntimeError("The database has no Alembic revision. Run `alembic upgrade head`.")


def _redis_client(settings: Settings) -> Any:
    if not settings.redis_url:
        return None
    from redis.asyncio import from_url

    return from_url(settings.redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5, health_check_interval=30)


def build_container(settings: Settings, *, provider: LLMProvider | None = None) -> Container:
    # ---------------------------------------------------------------- Phase 6 persistence & platform services
    db = Database(settings.database_url, pool_size=settings.database_pool_size, max_overflow=settings.database_max_overflow,
                  pool_timeout=settings.database_pool_timeout_seconds, echo=settings.database_echo)
    persistence = Persistence(db, memory_max_turns=settings.memory_max_turns, memory_ttl_minutes=settings.memory_ttl_minutes)
    redis = _redis_client(settings)
    rate_limiter = RateLimiter(redis, enabled=settings.rate_limit_enabled)
    ownership = SessionOwnership(persistence.sessions)
    metrics = Metrics()
    breakers = {
        "llm": CircuitBreaker("llm", failure_threshold=settings.circuit_breaker_failure_threshold,
                              recovery_seconds=settings.circuit_breaker_recovery_seconds),
        "redis": CircuitBreaker("redis", failure_threshold=settings.circuit_breaker_failure_threshold,
                                recovery_seconds=settings.circuit_breaker_recovery_seconds),
        "database": CircuitBreaker("database", failure_threshold=settings.circuit_breaker_failure_threshold,
                                   recovery_seconds=settings.circuit_breaker_recovery_seconds),
    }
    secret = settings.app_secret_key.get_secret_value() if settings.app_secret_key else secrets.token_urlsafe(48)  # dev: per-process
    auth = AuthService(persistence, secret=secret, access_ttl_minutes=settings.jwt_access_token_ttl_minutes,
                       refresh_ttl_days=settings.refresh_token_ttl_days, registration_enabled=settings.registration_enabled,
                       password_min_length=settings.password_min_length, rate_limiter=rate_limiter,
                       login_attempts_per_minute=settings.auth_login_attempts_per_minute)
    audit = AuditService(persistence, ownership)
    from app.queue.worker import new_worker_id

    worker_id = new_worker_id()

    ws_manager = WebSocketManager(
        history_limit=settings.telemetry_history_limit,
        max_connections=settings.websocket_max_connections,
        queue_size=settings.websocket_send_queue_size,
        max_sessions=settings.max_tracked_sessions,
    )
    events = EventManager(ws_manager, max_sessions=settings.max_tracked_sessions)
    events.taps.extend([audit.tap, metrics.tap])
    tasks = TaskService(events, max_tasks=settings.max_tasks_in_memory, planning_enabled=settings.agent_planning_enabled)
    tasks.persistence = persistence
    approvals = ApprovalService(events, max_items=settings.max_tasks_in_memory)
    approvals.persistence = persistence
    approvals.owner_lookup = tasks.owner_of
    demo = DemoSimulator(settings=settings, events=events, tasks=tasks, approvals=approvals)
    approvals.add_resolution_handler(demo.on_approval_resolved)

    # ---------------------------------------------------------------- Phase 2 agent
    provider = provider or create_provider(settings, mock_latency_ms=settings.agent_mock_latency_ms)
    runner = StructuredLLMRunner(
        provider,
        timeout=settings.agent_request_timeout_seconds,
        max_tokens=settings.agent_max_output_tokens,
        max_retries=settings.agent_max_retries,
        retry_base_delay=settings.agent_retry_base_delay_seconds,
    )
    runner.breaker = breakers["llm"]

    async def _llm_usage(**kw: Any) -> None:
        usage = kw.get("usage")
        provider_name = kw["provider"]
        metrics.llm_requests.labels(provider=provider_name, request_type=kw["request_type"][:30]).inc()
        if kw["outcome"] != "OK":
            metrics.llm_errors.labels(provider=provider_name, code=kw["outcome"][:40]).inc()
        if usage is not None:
            metrics.llm_tokens.labels(provider=provider_name, direction="input").inc(usage.input_tokens or 0)
            metrics.llm_tokens.labels(provider=provider_name, direction="output").inc(usage.output_tokens or 0)
        if provider_name != "mock" and usage is not None and runner.budget is not None:
            await runner.budget.add((usage.input_tokens or 0) + (usage.output_tokens or 0))
        if provider_name != "mock":  # usage accounting for real providers (no prompts stored)
            from app.database.models import LlmUsageRecord
            from app.schemas.common import utc_now

            cost = 0.0
            if usage is not None:
                cost = ((usage.input_tokens or 0) * settings.llm_input_cost_per_million
                        + (usage.output_tokens or 0) * settings.llm_output_cost_per_million) / 1_000_000

            async def _save() -> None:
                async with db.session() as s:
                    s.add(LlmUsageRecord(provider=provider_name, model=kw["model"], request_type=kw["request_type"][:40],
                                         prompt_version=kw["prompt_version"], input_tokens=(usage.input_tokens or 0) if usage else 0,
                                         output_tokens=(usage.output_tokens or 0) if usage else 0, latency_ms=kw["latency_ms"],
                                         estimated_cost=cost, outcome=kw["outcome"][:24], created_at=utc_now()))

            await persistence.best_effort(_save(), "llm.usage")

    runner.usage_hook = _llm_usage
    if provider.name != "mock":
        from app.resilience.llm_budget import TokenBudget

        runner.budget = TokenBudget(settings.llm_daily_token_budget, redis)
    registry = build_default_registry()
    memory = MemoryManager(
        max_turns=settings.memory_max_turns,
        max_characters=settings.memory_max_characters,
        ttl_minutes=settings.memory_ttl_minutes,
        max_sessions=settings.memory_max_sessions,
    )
    store = PlanStore(max_records=settings.max_tasks_in_memory)
    trusted_origins = frozenset(settings.browser_test_origin_list)
    planner = Planner(
        runner, registry, max_steps=settings.agent_max_plan_steps, max_retries=settings.agent_max_retries,
        trusted_origins=trusted_origins,
    )
    # Development/test only: the local demo shop is a catalog site on an exact trusted origin.
    if settings.browser_dev_fixtures_enabled and settings.browser_test_origin_list:
        register_website(demo_shop_website(settings.browser_test_origin_list[0]))
    else:
        unregister_website(DEMO_SHOP_KEY)
    # ---------------------------------------------------------------- Phase 4 commerce (registry + planner)
    commerce_registry = CommerceRegistry(
        {CommercePlatform.BLINKIT: BlinkitAdapter(), CommercePlatform.AMAZON_IN: AmazonIndiaAdapter()},
        settings.commerce_platform_list,
    )
    for platform in (CommercePlatform.BLINKIT, CommercePlatform.AMAZON_IN):
        if settings.commerce_enable_fixtures and settings.browser_test_origin_list:
            origin = settings.browser_test_origin_list[0]
            commerce_registry.register_fixture(fixture_binding(platform, origin))
            register_website(fixture_website(platform, origin))
        else:
            unregister_website(FIXTURE_KEYS[platform])
    commerce_planner = CommercePlanner(settings.commerce_max_products_per_task) if settings.commerce_enabled else None
    # ---------------------------------------------------------------- Phase 5 integrations (registry + planner)
    capabilities = CapabilityRegistry(settings)
    integration_domains = CapabilityRegistry.enabled_domains(settings) - {DomainType.BLINKIT, DomainType.AMAZON_IN}
    integration_registry = IntegrationRegistry(integration_domains)
    for domain in (DomainType.YOUTUBE, DomainType.GMAIL, DomainType.GOOGLE_CALENDAR, DomainType.FILES):
        if settings.integrations_enabled and settings.integration_enable_fixtures and settings.browser_test_origin_list \
                and domain in integration_domains:
            origin = settings.browser_test_origin_list[0]
            integration_registry.register_fixture(integration_fixture_binding(domain, origin))
            register_website(integration_fixture_website(domain, origin))
        else:
            unregister_website(INTEGRATION_FIXTURE_KEYS[domain])
    integration_planner = IntegrationPlanner(settings, integration_registry) if settings.integrations_enabled else None
    orchestrator = AgentOrchestrator(
        commerce_planner=commerce_planner,
        commerce_registry=commerce_registry,
        integration_planner=integration_planner,
        workflow_validator=lambda steps: validate_workflow(steps, capabilities, settings),
        provider=provider,
        events=events,
        tasks=tasks,
        memory=memory,
        classifier=IntentClassifier(runner),
        planner=planner,
        store=store,
        max_command_length=settings.max_command_length,
    )
    orchestrator.persistence = persistence
    from app.preferences import PreferencesService

    preferences = PreferencesService(db)
    orchestrator.preferences = preferences
    planning = PlanningService(
        settings=settings, tasks=tasks, orchestrator=orchestrator, store=store, memory=memory, provider=provider
    )
    # ---------------------------------------------------------------- Phase 3 browser
    telemetry = ExecutionEvents(events)
    guard = NavigationGuard(
        allowed_domains=settings.browser_allowed_domain_list, trusted_origins=settings.browser_test_origin_list
    )
    session_store = None
    if settings.browser_persist_sessions and settings.browser_state_encryption_key is not None:
        from datetime import timedelta

        session_store = SessionStore(
            settings.browser_state_directory,
            settings.browser_state_encryption_key.get_secret_value(),
            ttl=timedelta(minutes=settings.browser_session_idle_timeout_minutes),
        )
    browser = BrowserManager(settings, guard=guard, telemetry=telemetry, store=session_store)
    inspector = DOMInspector()
    screenshots = ScreenshotManager(
        quality=settings.browser_screenshot_quality, max_bytes=settings.browser_max_frame_bytes,
        fps=settings.browser_screenshot_fps, width=settings.browser_viewport_width, height=settings.browser_viewport_height,
    )
    controller = BrowserController(
        manager=browser, inspector=inspector,
        resolver=SelectorResolver(
            inspector, min_confidence=settings.browser_selector_min_confidence,
            max_attempts=settings.browser_selector_max_attempts,
            memory_ttl_seconds=settings.selector_cache_ttl_minutes * 60,
        ),
        screenshots=screenshots, action_timeout_ms=settings.browser_action_timeout_ms,
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
    )
    stream = BrowserStreamManager(
        manager=browser, screenshots=screenshots, telemetry=telemetry, max_frame_bytes=settings.browser_max_frame_bytes
    )
    coordinator = ApprovalCoordinator(approvals)
    execution = ExecutionManager(
        settings=settings, tasks=tasks, store=store, validator=planner.validator, browser=browser,
        controller=controller, stream=stream, telemetry=telemetry, approvals=coordinator,
    )
    commerce = None
    if settings.commerce_enabled:
        commerce = CommerceManager(
            settings=settings, registry=commerce_registry, browser=browser, controller=controller, telemetry=telemetry,
            approvals=coordinator, approval_service=approvals,
        )
        execution.commerce = commerce
    files: FileStore | None = None
    integrations: IntegrationManager | None = None
    if settings.integrations_enabled:
        downloader = None
        if settings.file_download_enabled:
            files = FileStore(settings.file_download_storage, ttl_hours=settings.file_download_ttl_hours,
                              max_storage_bytes=settings.file_download_max_storage_mb * 1024 * 1024)
            file_guard = NavigationGuard(
                allowed_domains=settings.file_download_domain_list,
                trusted_origins=settings.browser_test_origin_list if settings.integration_enable_fixtures else [],
            )
            downloader = FileDownloader(store=files, guard=file_guard, allowed_extensions=settings.file_download_extension_list,
                                        max_bytes=settings.file_download_max_size_mb * 1024 * 1024,
                                        max_concurrent=settings.file_download_max_concurrent,
                                        proxy=settings.egress_proxy_url or None)
        integrations = IntegrationManager(
            settings=settings, registry=integration_registry, capabilities=capabilities, controller=controller, telemetry=telemetry,
            approvals=coordinator, approval_service=approvals, store=store, tasks=tasks, downloader=downloader, files=files,
        )
        execution.integrations = integrations
        integrations.persistence = persistence
        integrations.rate_limiter = rate_limiter
        integrations.scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port) if settings.malware_scanner == "clamav" else NullScanner()
    execution.journal = ExecutionJournal(persistence, worker_id)
    if settings.self_correction_enabled:
        from app.agent.self_correction.recovery_policy import RecoveryPolicy
        from app.agent.self_correction.replanner import Replanner
        from app.browser.mutation_monitor import MutationMonitor
        from app.browser.recovery_engine import RecoveryEngine

        execution.recovery = RecoveryEngine(
            policy=RecoveryPolicy(enabled=True, max_attempts=settings.self_correction_max_attempts,
                                  max_replans=settings.self_correction_max_replans, max_seconds=settings.self_correction_max_time_seconds),
            monitor=MutationMonitor(settings.dom_mutation_buffer_size), replanner=Replanner(runner), metrics=metrics)
    if redis is not None:
        from app.queue.locks import SessionLocks

        execution.session_locks = SessionLocks(redis)
    if settings.queue_backend == "redis" and redis is not None:
        from app.queue.execution_bridge import RedisExecutionQueue

        execution.queue = RedisExecutionQueue(
            redis, execution.run_job, concurrency=settings.execution_concurrency, max_depth=settings.queue_max_depth,
            max_attempts=settings.queue_max_attempts, heartbeat_seconds=settings.worker_heartbeat_seconds, metrics=metrics,
            should_run=execution.prepare_job, on_abandoned=execution.abandon_job,
        )
    planning.execution_available = lambda: execution.available
    metrics.bind_gauge(metrics.approval_pending, lambda: approvals.pending_count())
    metrics.bind_gauge(metrics.ws_active, lambda: ws_manager.connection_count)
    metrics.bind_gauge(metrics.browser_sessions_active, lambda: browser.session_count())
    execution.preferences = preferences
    execution.executor.rate_limiter = rate_limiter
    execution.executor.actions_per_minute = settings.browser_actions_per_minute
    if commerce is not None:
        commerce.rate_limiter = rate_limiter
    container = Container(
        db=db, persistence=persistence, redis=redis, rate_limiter=rate_limiter, ownership=ownership, auth=auth, audit=audit,
        metrics=metrics, breakers=breakers, store=store, files=files, worker_id=worker_id, preferences=preferences,
        integrations=integrations,
        integration_service=IntegrationService(integrations, capabilities, files),
        capabilities=capabilities,
        commerce=commerce,
        commerce_registry=commerce_registry,
        commerce_service=CommerceService(commerce, lambda sid: browser.peek_session(sid) is not None),
        browser=browser,
        stream=stream,
        execution=execution,
        execution_service=ExecutionService(execution),
        browser_service=BrowserService(settings=settings, manager=browser, stream=stream, execution=execution),
        settings=settings,
        ws_manager=ws_manager,
        events=events,
        tasks=tasks,
        approvals=approvals,
        demo=demo,
        provider=provider,
        registry=registry,
        memory=memory,
        orchestrator=orchestrator,
        planning=planning,
    )
    container.authorizer = ResourceAuthorizer(container)
    return container
