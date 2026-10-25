import httpx
import pytest

from chat.cache import QueryVectorCache
from chat.embedding import EmbeddingClient
from chat.errors import DependencyUnavailable, UpstreamFailed, UpstreamTimeout
from chat.llm import LLMClient, ProviderUnavailable
from chat.textutil import truncate_query
from chat.vectors import QdrantVectorIndex
from tests.support import USER_A, make_settings
from tests.transport import ScriptedTransport, openai_sse


@pytest.mark.asyncio
async def test_llm_retries_status_and_skips_empty_chunks():
    settings = make_settings()
    transport = ScriptedTransport()
    transport.llm_script.append(httpx.Response(429, json={"error": "slow"}))
    client = LLMClient(settings, transport=transport)
    tokens = [token async for token in client.stream([{"role": "user", "content": "q"}], "req-1")]
    assert tokens == ["Срок", " годности"]
    assert len(transport.llm_requests) == 2
    assert transport.llm_requests[0].headers["authorization"] == "Bearer test-key"
    await client.close()


@pytest.mark.asyncio
async def test_llm_does_not_retry_other_4xx():
    settings = make_settings()
    transport = ScriptedTransport()
    transport.llm_script.append(httpx.Response(400, json={"error": "bad"}))
    client = LLMClient(settings, transport=transport)
    with pytest.raises(UpstreamFailed):
        _ = [token async for token in client.stream([{"role": "user", "content": "q"}], "req")]
    assert len(transport.llm_requests) == 1
    await client.close()


@pytest.mark.asyncio
async def test_llm_timeout_after_retry():
    settings = make_settings()
    transport = ScriptedTransport()
    transport.llm_script.extend([httpx.ReadTimeout("timed out"), httpx.ReadTimeout("timed out")])
    client = LLMClient(settings, transport=transport)
    with pytest.raises(ProviderUnavailable) as caught:
        _ = [token async for token in client.stream([{"role": "user", "content": "q"}], "req")]
    assert caught.value.kind == "timeout"
    assert len(transport.llm_requests) == 2
    await client.close()


@pytest.mark.asyncio
async def test_llm_timeout_after_token_is_upstream_timeout(monkeypatch):
    settings = make_settings()
    transport = ScriptedTransport()
    body = (
        'data: {"choices":[{"index":0,"delta":{"content":"токен"},"finish_reason":null}]}\n'
        'data: {"choices":[{"index":0,"delta":{"content":"ещё"},"finish_reason":null}]}\n'
    ).encode()
    transport.llm_script.append(httpx.Response(200, content=body))
    calls = {"n": 0}

    def fake_monotonic() -> float:
        calls["n"] += 1
        if calls["n"] <= 2:
            return 0.0
        return settings.llm_timeout_seconds + 1

    monkeypatch.setattr("chat.llm.time.monotonic", fake_monotonic)
    client = LLMClient(settings, transport=transport)
    tokens: list[str] = []
    with pytest.raises(UpstreamTimeout):
        async for token in client.stream([{"role": "user", "content": "q"}], "req"):
            tokens.append(token)
    assert tokens == ["токен"]
    assert len(transport.llm_requests) == 1
    await client.close()


@pytest.mark.asyncio
async def test_embedding_uses_query_type_and_truncates():
    settings = make_settings(embedding_max_tokens=30)
    transport = ScriptedTransport(dim=768)
    client = EmbeddingClient(settings, transport=transport)
    question = "я" * 400
    vector = await client.embed_query(question, "req-9")
    assert len(vector) == 768
    sent = transport.embed_body()
    assert sent["input_type"] == "query"
    assert "title" not in sent
    assert sent["texts"] == [truncate_query(question, 30)]
    assert len(sent["texts"][0]) < len(question)
    assert transport.embed_requests[0].headers["x-request-id"] == "req-9"
    await client.close()


@pytest.mark.asyncio
async def test_embedding_unavailable_is_503_and_bad_dimension_is_502():
    settings = make_settings()
    transport = ScriptedTransport()
    transport.embed_script.extend([httpx.ConnectError("refused"), httpx.ConnectError("refused")])
    client = EmbeddingClient(settings, transport=transport)
    with pytest.raises(DependencyUnavailable):
        await client.embed_query("вопрос", "req")
    assert len(transport.embed_requests) == 2

    transport.embed_script.append(
        httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2]], "model": "m", "dimension": 2},
        )
    )
    with pytest.raises(UpstreamFailed):
        await client.embed_query("вопрос", "req")
    await client.close()


@pytest.mark.asyncio
async def test_qdrant_search_filters_by_user():
    settings = make_settings()

    class Stub:
        def __init__(self) -> None:
            self.kwargs = None

        async def query_points(self, **kwargs):
            self.kwargs = kwargs

            class Result:
                points = []

            return Result()

    stub = Stub()
    index = QdrantVectorIndex(settings, client=stub)
    hits = await index.search(USER_A, [0.1, 0.2], 5)
    assert hits == []
    assert stub.kwargs["collection_name"] == "documents"
    assert stub.kwargs["limit"] == 5
    assert stub.kwargs["query"] == [0.1, 0.2]
    condition = stub.kwargs["query_filter"].must[0]
    assert condition.key == "user_id"
    assert condition.match.value == USER_A

    class Broken:
        async def query_points(self, **kwargs):
            raise RuntimeError("down")

    with pytest.raises(DependencyUnavailable):
        await QdrantVectorIndex(settings, client=Broken()).search(USER_A, [0.1], 1)


class _Point:
    def __init__(self, payload: dict, score: float | None) -> None:
        self.payload = payload
        self.score = score


class _QueryResult:
    def __init__(self, points: list[_Point]) -> None:
        self.points = points


@pytest.mark.asyncio
async def test_qdrant_image_search_uses_offset_and_skips_incomplete_payloads():
    settings = make_settings(qdrant_images_collection="photos")
    complete = {
        "file_id": "file-1",
        "document_id": "other",
        "file_name": "a.jpg",
        "s3_key": "k",
        "s3_url": "s3://bucket/k",
        "user_id": USER_A,
    }
    from_document = {
        "document_id": "file-2",
        "file_name": "b.jpg",
        "s3_key": "b",
        "s3_url": "s3://bucket/b",
        "user_id": USER_A,
        "score": 0.4,
    }
    missing_key = {
        "file_id": "file-3",
        "file_name": "c.jpg",
        "s3_url": "s3://bucket/c",
    }

    class Stub:
        def __init__(self) -> None:
            self.kwargs = None

        async def query_points(self, **kwargs):
            self.kwargs = kwargs
            return _QueryResult(
                [
                    _Point(missing_key, 0.99),
                    _Point(from_document, None),
                    _Point(complete, 0.2),
                    _Point({"file_name": "d.jpg", "s3_key": "d", "s3_url": "s3://bucket/d"}, 0.8),
                ]
            )

    stub = Stub()
    scan = await QdrantVectorIndex(settings, client=stub).search_images(USER_A, [0.1, 0.2], 2, 5)
    hits = scan.hits
    assert scan.scanned == 4
    assert [hit.file_id for hit in hits] == ["file-2", "file-1"]
    assert hits[0].score == 0.4
    assert hits[0].s3_key == "b"
    assert hits[1].file_name == "a.jpg"
    assert stub.kwargs["collection_name"] == "photos"
    assert stub.kwargs["limit"] == 2
    assert stub.kwargs["offset"] == 5
    assert stub.kwargs["query"] == [0.1, 0.2]
    assert "score_threshold" not in stub.kwargs
    condition = stub.kwargs["query_filter"].must[0]
    assert condition.key == "user_id"
    assert condition.match.value == USER_A
    assert len(stub.kwargs["query_filter"].must) == 1

    class Broken:
        async def query_points(self, **kwargs):
            raise RuntimeError("down")

    with pytest.raises(DependencyUnavailable):
        await QdrantVectorIndex(settings, client=Broken()).search_images(USER_A, [0.1], 1, 0)


def test_query_vector_cache_is_lru_and_expires():
    now = [0.0]
    cache = QueryVectorCache(2, 60, clock=lambda: now[0])
    cache.put("user", "one", [1.0])
    cache.put("user", "two", [2.0])
    assert cache.get("user", "one") == [1.0]
    cache.put("user", "three", [3.0])
    assert cache.get("user", "two") is None
    assert cache.get("user", "three") == [3.0]
    assert cache.get("other", "one") is None
    now[0] = 59.0
    assert cache.get("user", "one") == [1.0]
    now[0] = 60.0
    assert cache.get("user", "one") is None
    cache.put("user", "one", [1.0, 2.0])
    copied = cache.get("user", "one")
    assert copied == [1.0, 2.0]
    assert copied is not None
    copied.append(3.0)
    assert cache.get("user", "one") == [1.0, 2.0]


@pytest.mark.asyncio
async def test_streamed_tokens_are_only_non_empty_content():
    settings = make_settings()
    transport = ScriptedTransport()
    transport.llm_script.append(lambda: httpx.Response(200, content=openai_sse(["А", "Б"])))
    client = LLMClient(settings, transport=transport)
    assert [token async for token in client.stream([], "r")] == ["А", "Б"]
    await client.close()
