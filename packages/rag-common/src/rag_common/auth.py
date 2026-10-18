"""Identity from docs/gateway.md and docs/api.md.

File Collector and Chat read the user only from ``X-Auth-User-Id``.
``X-User-Id``, cookies, and ``Authorization`` do not select a user.
``X-Auth-Role: BLOCKED`` is ``403 forbidden`` when the user id is a UUID.
A missing or non-UUID ``X-Auth-User-Id`` is ``401 unauthenticated``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from re import compile
from typing import Any

from rag_common.errors import ErrorCode, http_error

AUTH_USER_HEADER = "X-Auth-User-Id"
AUTH_ROLE_HEADER = "X-Auth-Role"
IGNORED_USER_HEADER = "X-User-Id"
BLOCKED_ROLE = "BLOCKED"

_UUID_TEXT = compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class AuthOk:
    user_id: str


@dataclass(frozen=True)
class AuthError:
    status: int
    body: dict[str, Any]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            text = value.strip()
            return text or None
    return None


def canonical_uuid(value: str) -> str | None:
    """Return lowercase ``8-4-4-4-12`` or ``None`` when ``value`` is not a UUID."""
    if not _UUID_TEXT.fullmatch(value):
        return None
    return value.lower()


def authenticate(headers: Mapping[str, str]) -> AuthOk | AuthError:
    """Resolve the RAG user from gateway headers.

    ``X-User-Id`` is ignored even when it is a UUID. Email and name headers
    are not read. The UUID version is not checked: User-Service chooses it.
    """
    user_raw = _header(headers, AUTH_USER_HEADER)
    user_id = canonical_uuid(user_raw) if user_raw is not None else None
    if user_id is None:
        status, body = http_error(ErrorCode.UNAUTHENTICATED)
        return AuthError(status, body)
    if _header(headers, AUTH_ROLE_HEADER) == BLOCKED_ROLE:
        status, body = http_error(ErrorCode.FORBIDDEN)
        return AuthError(status, body)
    return AuthOk(user_id)
