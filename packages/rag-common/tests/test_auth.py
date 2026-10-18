from rag_common.auth import AuthError, AuthOk, authenticate

USER = "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d"
OTHER = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"


def test_requires_uuid_header() -> None:
    result = authenticate({})
    assert isinstance(result, AuthError)
    assert result.status == 401
    assert result.body["error"]["code"] == "unauthenticated"
    assert "details" not in result.body["error"]


def test_x_user_id_is_not_identity() -> None:
    result = authenticate({"X-User-Id": USER})
    assert isinstance(result, AuthError)
    assert result.status == 401

    result = authenticate({"X-User-Id": OTHER, "X-Auth-User-Id": USER})
    assert isinstance(result, AuthOk)
    assert result.user_id == USER


def test_authorization_and_cookie_do_not_authenticate() -> None:
    result = authenticate({"Authorization": "Bearer token", "Cookie": "auth_access=abc"})
    assert isinstance(result, AuthError)
    assert result.status == 401


def test_non_uuid_is_401() -> None:
    for value in ("", "not-a-uuid", "91a0b1c23d4e4f50861718293a4b5c6d", "user"):
        result = authenticate({"X-Auth-User-Id": value})
        assert isinstance(result, AuthError)
        assert result.status == 401


def test_canonical_lowercase() -> None:
    result = authenticate({"x-auth-user-id": USER.upper()})
    assert isinstance(result, AuthOk)
    assert result.user_id == USER


def test_blocked_role_is_403_even_with_uuid() -> None:
    result = authenticate({"X-Auth-User-Id": USER, "X-Auth-Role": "BLOCKED"})
    assert isinstance(result, AuthError)
    assert result.status == 403
    assert result.body["error"]["code"] == "forbidden"
    assert result.body["error"]["message"] == "User is blocked"


def test_blocked_without_uuid_stays_401() -> None:
    result = authenticate({"X-Auth-Role": "BLOCKED"})
    assert isinstance(result, AuthError)
    assert result.status == 401


def test_other_roles_pass() -> None:
    result = authenticate({"X-Auth-User-Id": USER, "X-Auth-Role": " blocked "})
    assert isinstance(result, AuthOk)
    result = authenticate(
        {
            "X-Auth-User-Id": USER,
            "X-Auth-Role": "ADMIN",
            "X-Auth-Email": "a@example.com",
            "X-Auth-Name": "Ada",
        }
    )
    assert isinstance(result, AuthOk)
    assert result.user_id == USER


def test_blocked_header_is_trimmed() -> None:
    result = authenticate({"X-Auth-User-Id": USER, "X-Auth-Role": " BLOCKED "})
    assert isinstance(result, AuthError)
    assert result.status == 403
