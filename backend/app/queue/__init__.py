"""Phase 6 distributed job queue (Redis), workers, locks, retries and dead letters.

Delivery is AT-LEAST-ONCE. External mutations are protected by the execution journal and
idempotency keys — never by an exactly-once claim.
"""
