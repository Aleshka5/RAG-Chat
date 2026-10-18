"""Shared contracts for the RAG chat services.

Behavior comes from ``docs/``. HTTP field shape follows the OpenAPI documents.
This package does not talk to MongoDB, Qdrant, or RabbitMQ by itself.
"""

from rag_common.auth import (
    AUTH_ROLE_HEADER,
    AUTH_USER_HEADER,
    BLOCKED_ROLE,
    IGNORED_USER_HEADER,
    AuthError,
    AuthOk,
    authenticate,
)
from rag_common.config import (
    CHAT_EMBEDDING_TIMEOUT,
    DEFAULTS,
    LOCAL_MODEL_WINDOW,
    SECRET_NAMES,
    ConfigError,
    InvalidConfig,
    MissingConfig,
    config_failure_record,
    load_config,
    load_service_config,
    validate_chat_config,
    validate_processor_config,
)
from rag_common.errors import (
    STATUS_BY_CODE,
    ErrorCode,
    error_envelope,
    http_error,
)
from rag_common.logging import LOG_FIELD_NAMES, JsonFormatter, log_extra
from rag_common.messages import DocDelete, DocProcess, parse_message
from rag_common.mongo import (
    ensure_chats_indexes,
    ensure_file_pages_indexes,
    ensure_files_indexes,
    ensure_messages_indexes,
)
from rag_common.qdrant import (
    DISTANCE,
    DOCUMENT_PAYLOAD_KEY,
    HNSW_M,
    HNSW_PAYLOAD_M,
    POINT_ID_NAMESPACE,
    TENANT_PAYLOAD_KEY,
    point_id,
)
from rag_common.rabbitmq import PREFETCH_COUNT, apply_prefetch, build_publish, declare_topology
from rag_common.request_id import (
    AMQP_REQUEST_ID_HEADER,
    REQUEST_ID_HEADER,
    outgoing_http_headers,
    resolve_request_id,
    response_headers,
)

__all__ = [
    "AMQP_REQUEST_ID_HEADER",
    "AUTH_ROLE_HEADER",
    "AUTH_USER_HEADER",
    "BLOCKED_ROLE",
    "CHAT_EMBEDDING_TIMEOUT",
    "DEFAULTS",
    "DISTANCE",
    "DOCUMENT_PAYLOAD_KEY",
    "HNSW_M",
    "HNSW_PAYLOAD_M",
    "IGNORED_USER_HEADER",
    "LOCAL_MODEL_WINDOW",
    "LOG_FIELD_NAMES",
    "POINT_ID_NAMESPACE",
    "PREFETCH_COUNT",
    "REQUEST_ID_HEADER",
    "SECRET_NAMES",
    "STATUS_BY_CODE",
    "TENANT_PAYLOAD_KEY",
    "AuthError",
    "AuthOk",
    "ConfigError",
    "DocDelete",
    "DocProcess",
    "ErrorCode",
    "InvalidConfig",
    "JsonFormatter",
    "MissingConfig",
    "apply_prefetch",
    "authenticate",
    "build_publish",
    "config_failure_record",
    "declare_topology",
    "ensure_chats_indexes",
    "ensure_file_pages_indexes",
    "ensure_files_indexes",
    "ensure_messages_indexes",
    "error_envelope",
    "http_error",
    "load_config",
    "load_service_config",
    "log_extra",
    "outgoing_http_headers",
    "parse_message",
    "point_id",
    "resolve_request_id",
    "response_headers",
    "validate_chat_config",
    "validate_processor_config",
]
