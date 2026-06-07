"""OpenTelemetry bootstrap.

Optional and lazy: when `PAG_OTEL_ENABLED` is false, every public function
in this module is a no-op. The SDK + instrumentation packages are imported
only when the flag is on, so the core `pip install` stays light.

What we wire up
---------------
- Tracer provider with a `Resource` that names the service.
- OTLP gRPC exporter pointed at `PAG_OTEL_EXPORTER_OTLP_ENDPOINT` with a
  `BatchSpanProcessor`.
- ParentBased(TraceIdRatioBased) sampler.
- Auto-instrumentation for **FastAPI**, **SQLAlchemy**, and **httpx**.
- A `traced_agent_run` decorator that the `BaseAgent` lifecycle wraps every
  `_run` call with so each agent's work is its own span with KPIs as
  attributes.

Privacy
-------
Span attributes contain only:
- Service / agent names.
- Numeric KPIs and durations.
- Tenant id.
- Compact identifiers (UUIDs, codes).

No PHI is ever attached to a span. Critique payloads (`what_failed`,
narratives, etc.) are explicitly excluded.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from .config import Settings, get_settings
from .logging import get_logger

T = TypeVar("T")

_INITIALIZED = False
_TRACER: Any = None
_NOOP_DECORATOR = lambda fn: fn  # noqa: E731 — used as a fall-through


def configure_otel(app: Any | None = None, settings: Settings | None = None) -> bool:
    """Initialise the OTel SDK + instrumentation.

    Returns `True` if OTel was actually wired up, `False` if disabled or if
    the optional dependencies are not installed.
    """
    global _INITIALIZED, _TRACER

    s = settings or get_settings()
    if not s.otel_enabled or _INITIALIZED:
        return _INITIALIZED

    log = get_logger("otel")
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )
    except ImportError as exc:
        log.warning("otel_sdk_missing", error=str(exc))
        return False

    resource = Resource.create(
        {
            "service.name": s.otel_service_name,
            "service.version": s.otel_service_version,
            "deployment.environment": (
                s.environment.value if hasattr(s.environment, "value") else str(s.environment)
            ),
        }
    )
    sampler = ParentBased(TraceIdRatioBased(s.otel_traces_sample_rate))
    provider = TracerProvider(resource=resource, sampler=sampler)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=s.otel_exporter_otlp_endpoint, insecure=True)
        )
    )
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("pa_guard")

    # Auto-instrument optional integrations — each is independent.
    _instrument_safe("opentelemetry.instrumentation.fastapi", "FastAPIInstrumentor", app=app)
    _instrument_safe("opentelemetry.instrumentation.sqlalchemy", "SQLAlchemyInstrumentor")
    _instrument_safe("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor")

    _INITIALIZED = True
    log.info(
        "otel_configured",
        service=s.otel_service_name,
        endpoint=s.otel_exporter_otlp_endpoint,
        sample_rate=s.otel_traces_sample_rate,
    )
    return True


def _instrument_safe(
    module_path: str, instrumentor_name: str, **kwargs: Any
) -> None:
    """Import + run a single instrumentor, swallowing ImportError."""
    log = get_logger("otel")
    try:
        module = __import__(module_path, fromlist=[instrumentor_name])
        klass = getattr(module, instrumentor_name)
    except (ImportError, AttributeError) as exc:
        log.info("otel_instrumentation_skipped", module=module_path, error=str(exc))
        return
    try:
        instance = klass()
        if "app" in kwargs and kwargs["app"] is not None:
            instance.instrument_app(kwargs["app"])
        else:
            instance.instrument()
        log.info("otel_instrumented", target=module_path)
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("otel_instrumentation_failed", target=module_path, error=str(exc))


# ---------------------------------------------------------------------------
# Public surface for tracing agent work
# ---------------------------------------------------------------------------

def get_tracer() -> Any:
    return _TRACER


def traced_agent_run(
    agent_name: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that wraps a single agent's `_run` body in a span.

    No-op when OTel is disabled; meaningful instrumentation when enabled.
    """
    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        if _TRACER is None:
            return fn

        @wraps(fn)
        async def wrapped(*args: Any, **kwargs: Any) -> T:
            tracer = _TRACER
            if tracer is None:
                return await fn(*args, **kwargs)
            with tracer.start_as_current_span(f"agent.{agent_name}") as span:
                span.set_attribute("pa_guard.agent.name", agent_name)
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    raise
                return result

        return wrapped

    return decorator


__all__ = ["configure_otel", "get_tracer", "traced_agent_run"]
