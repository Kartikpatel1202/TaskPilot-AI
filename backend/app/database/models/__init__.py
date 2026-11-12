"""Phase 6 persistent models. Import every model so Base.metadata is complete (Alembic, create_all)."""

from .approval import ApprovalRecord
from .audit import AuditEventRecord
from .browser_session import AppSessionRecord, BrowserSessionRecord
from .conversation import ConversationTurnRecord
from .execution import ActionJournalRecord, ActionLifecycle
from .file import FileRecord
from .integration import IntegrationStatusRecord, LlmUsageRecord
from .plan import PlanRecord
from .preferences import UserPreferencesRecord
from .task import TaskRecord
from .user import RefreshTokenRecord, UserRecord, UserRole, UserStatus
from .workflow import WorkflowRecord

__all__ = [
    "ActionJournalRecord", "ActionLifecycle", "AppSessionRecord", "ApprovalRecord", "AuditEventRecord", "BrowserSessionRecord",
    "ConversationTurnRecord", "FileRecord", "IntegrationStatusRecord", "LlmUsageRecord", "PlanRecord", "RefreshTokenRecord",
    "TaskRecord", "UserPreferencesRecord", "UserRecord", "UserRole", "UserStatus", "WorkflowRecord",
]
