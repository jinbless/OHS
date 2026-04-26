"""
SPARQL client for Apache Jena Fuseki with circuit breaker and TTL cache.

Design:
- Circuit breaker: 3 consecutive failures → 60s cooldown → auto-recovery
- TTL-based memory cache (default 300s)
- Async (httpx.AsyncClient, FastAPI compatible)
- On failure: returns empty results (no exceptions raised)
"""
import time
import hashlib
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class SparqlClient:
    def __init__(self, endpoint: str, timeout: int = 5):
        self.endpoint = endpoint
        self.timeout = timeout
        # Circuit breaker state
        self._failure_count = 0
        self._failure_threshold = 3
        self._cooldown_seconds = 60
        self._last_failure_time: float = 0
        # TTL cache: key → (result, expire_time)
        self._cache: dict[str, tuple[list[dict], float]] = {}

    def is_available(self) -> bool:
        """Check circuit breaker state."""
        if self._failure_count < self._failure_threshold:
            return True
        elapsed = time.time() - self._last_failure_time
        if elapsed >= self._cooldown_seconds:
            # Reset circuit breaker — allow retry
            self._failure_count = 0
            logger.info("SPARQL circuit breaker reset after cooldown")
            return True
        return False

    def _record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            logger.warning(
                "SPARQL circuit breaker OPEN — %d failures, cooldown %ds",
                self._failure_count, self._cooldown_seconds
            )

    def _record_success(self):
        if self._failure_count > 0:
            self._failure_count = 0
            logger.info("SPARQL circuit breaker CLOSED — connection restored")

    def _cache_key(self, sparql: str) -> str:
        return hashlib.md5(sparql.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[list[dict]]:
        if key in self._cache:
            result, expire_time = self._cache[key]
            if time.time() < expire_time:
                return result
            del self._cache[key]
        return None

    def _set_cache(self, key: str, result: list[dict], ttl: int):
        self._cache[key] = (result, time.time() + ttl)
        # Evict expired entries periodically
        if len(self._cache) > 200:
            now = time.time()
            expired = [k for k, (_, t) in self._cache.items() if t <= now]
            for k in expired:
                del self._cache[k]

    async def query(self, sparql: str, cache_ttl: int = 300) -> list[dict]:
        """
        Execute SELECT query → list of binding dicts.
        Returns [] on Fuseki failure (circuit breaker).
        """
        if not settings.FUSEKI_ENABLED or not self.is_available():
            return []

        key = self._cache_key(sparql)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self.endpoint,
                    params={"query": sparql},
                    headers={"Accept": "application/sparql-results+json"}
                )
                resp.raise_for_status()
                data = resp.json()

            bindings = data.get("results", {}).get("bindings", [])
            result = [
                {k: v.get("value") for k, v in row.items()}
                for row in bindings
            ]
            self._record_success()
            if cache_ttl > 0:
                self._set_cache(key, result, cache_ttl)
            return result

        except Exception as e:
            logger.warning("SPARQL query failed: %s", e)
            self._record_failure()
            return []

    async def ask(self, sparql: str) -> Optional[bool]:
        """
        Execute ASK query → True/False.
        Returns None on failure.
        """
        if not settings.FUSEKI_ENABLED or not self.is_available():
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self.endpoint,
                    params={"query": sparql},
                    headers={"Accept": "application/sparql-results+json"}
                )
                resp.raise_for_status()
                return resp.json().get("boolean", False)

        except Exception as e:
            logger.warning("SPARQL ASK failed: %s", e)
            self._record_failure()
            return None

    async def health_check(self) -> dict:
        """Return Fuseki health status."""
        result = await self.ask("ASK { ?s ?p ?o }")
        return {
            "fuseki_enabled": settings.FUSEKI_ENABLED,
            "fuseki_reachable": result is True,
            "circuit_breaker_open": not self.is_available(),
            "failure_count": self._failure_count,
            "endpoint": self.endpoint
        }


sparql_client = SparqlClient(
    endpoint=settings.FUSEKI_ENDPOINT,
    timeout=settings.FUSEKI_TIMEOUT
)
