"""
Idempotency store for the Order Sync service.

Provides deduplication of inbound order messages to prevent duplicate
order creation when messages are redelivered (expected in at-least-once
message queues).

The abstract base class ``IdempotencyStore`` defines the interface so
the backing implementation can be swapped (e.g. Redis, database) without
changing service code.
"""

from abc import ABC, abstractmethod
from typing import Optional

from .models import OrderSyncResult


class IdempotencyStore(ABC):
    """Protocol for idempotency stores.

    Implementations must support three operations:
    - check:  look up a previously cached result by message_id
    - save:   persist a result keyed by message_id
    - remove: delete a cached result (e.g. to allow reprocessing)
    """

    @abstractmethod
    def check(self, message_id: str) -> Optional[OrderSyncResult]:
        """Return the cached result for *message_id*, or ``None``."""
        ...

    @abstractmethod
    def save(self, message_id: str, result: OrderSyncResult) -> None:
        """Cache *result* under *message_id*."""
        ...

    @abstractmethod
    def remove(self, message_id: str) -> None:
        """Remove any cached result for *message_id*."""
        ...


class InMemoryIdempotencyStore(IdempotencyStore):
    """Simple dict-backed idempotency store.

    Suitable for single-process / testing scenarios.  For production use,
    swap this out for a Redis- or database-backed implementation that
    shares state across workers.
    """

    def __init__(self) -> None:
        self._store: dict[str, OrderSyncResult] = {}

    def check(self, message_id: str) -> Optional[OrderSyncResult]:
        return self._store.get(message_id)

    def save(self, message_id: str, result: OrderSyncResult) -> None:
        self._store[message_id] = result

    def remove(self, message_id: str) -> None:
        self._store.pop(message_id, None)
