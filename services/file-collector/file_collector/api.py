"""HTTP routes for the public file API."""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from file_collector.errors import ApiError
from file_collector.service import (
    IMAGE_CONTENT_TYPES,
    PDF_CONTENT_TYPE,
    accept_manifest,
    delete_pdf,
    get_pdf,
    list_pdfs,
    read_pdf,
    upload_image,
    upload_pdf,
)

router = APIRouter()

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def parse_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not _UUID.fullmatch(text):
        return None
    return text.lower()


async def require_user(request: Request) -> str:
    user_id = parse_uuid(request.headers.get("x-auth-user-id"))
    if user_id is None:
        raise ApiError(401, "unauthenticated", "Missing or invalid X-Auth-User-Id")
    request.state.user_id = user_id
    role = request.headers.get("x-auth-role")
    if role is not None and role.strip() == "BLOCKED":
        raise ApiError(403, "forbidden", "User is blocked")
    return user_id


def request_id_of(request: Request) -> str:
    current = getattr(request.state, "request_id", None)
    if isinstance(current, str) and current:
        return current
    return "unknown"


def _page(request: Request) -> tuple[int, int]:
    fields: list[str] = []
    limit = _bounded_int(
        request.query_params.get("limit"),
        default=50,
        low=1,
        high=100,
        name="limit",
        fields=fields,
    )
    offset = _bounded_int(
        request.query_params.get("offset"),
        default=0,
        low=0,
        high=None,
        name="offset",
        fields=fields,
    )
    if fields:
        raise ApiError(400, "validation_error", "Invalid request", {"fields": fields})
    return limit, offset


def _bounded_int(
    raw: str | None,
    *,
    default: int,
    low: int,
    high: int | None,
    name: str,
    fields: list[str],
) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        fields.append(name)
        return default
    if value < low or (high is not None and value > high):
        fields.append(name)
    return value


def _file_id(file_id: str) -> str:
    parsed = parse_uuid(file_id)
    if parsed is None:
        raise ApiError(400, "validation_error", "Invalid request", {"fields": ["file_id"]})
    return parsed


def _is_multipart(request: Request) -> bool:
    return "multipart/form-data" in request.headers.get("content-type", "").lower()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/api/files")
async def list_files(request: Request, user_id: str = Depends(require_user)) -> dict:
    limit, offset = _page(request)
    return await list_pdfs(
        files=request.app.state.files,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )


@router.post("/api/files")
async def create_file(request: Request, user_id: str = Depends(require_user)) -> JSONResponse:
    card = await upload_pdf(
        request=request,
        user_id=user_id,
        request_id=request_id_of(request),
        settings=request.app.state.settings,
        files=request.app.state.files,
        objects=request.app.state.objects,
        publisher=request.app.state.publisher,
    )
    return JSONResponse(status_code=202, content=card)


@router.post("/api/files/documents")
async def create_document(request: Request, user_id: str = Depends(require_user)) -> JSONResponse:
    card = await accept_manifest(
        request=request,
        user_id=user_id,
        request_id=request_id_of(request),
        files=request.app.state.files,
        objects=request.app.state.objects,
        publisher=request.app.state.publisher,
        allowed_types=frozenset({PDF_CONTENT_TYPE}),
        pdf_extension=True,
    )
    return JSONResponse(status_code=202, content=card)


@router.post("/api/files/images")
async def create_image(request: Request, user_id: str = Depends(require_user)) -> JSONResponse:
    """Image intake: multipart bytes, or a manifest of an object already in the bucket."""
    if _is_multipart(request):
        card = await upload_image(
            request=request,
            user_id=user_id,
            request_id=request_id_of(request),
            settings=request.app.state.settings,
            files=request.app.state.files,
            objects=request.app.state.objects,
            publisher=request.app.state.publisher,
        )
        return JSONResponse(status_code=202, content=card)
    card = await accept_manifest(
        request=request,
        user_id=user_id,
        request_id=request_id_of(request),
        files=request.app.state.files,
        objects=request.app.state.objects,
        publisher=request.app.state.publisher,
        allowed_types=IMAGE_CONTENT_TYPES,
        pdf_extension=False,
    )
    return JSONResponse(status_code=202, content=card)


@router.get("/api/files/{file_id}")
async def get_file(file_id: str, request: Request, user_id: str = Depends(require_user)) -> dict:
    return await get_pdf(
        files=request.app.state.files,
        user_id=user_id,
        file_id=_file_id(file_id),
    )


@router.delete("/api/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    user_id: str = Depends(require_user),
) -> JSONResponse:
    body = await delete_pdf(
        files=request.app.state.files,
        publisher=request.app.state.publisher,
        settings=request.app.state.settings,
        user_id=user_id,
        file_id=_file_id(file_id),
        request_id=request_id_of(request),
    )
    return JSONResponse(status_code=202, content=body)


@router.get("/api/files/{file_id}/content")
async def get_content(
    file_id: str,
    request: Request,
    user_id: str = Depends(require_user),
) -> Response:
    payload, disposition, size, media_type = await read_pdf(
        files=request.app.state.files,
        objects=request.app.state.objects,
        user_id=user_id,
        file_id=_file_id(file_id),
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(size),
        },
    )
