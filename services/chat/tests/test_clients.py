import httpx
import pytest

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


@pytest.mark.asyncio
async def test_streamed_tokens_are_only_non_empty_content():
    settings = make_settings()
    transport = ScriptedTransport()
    transport.llm_script.append(lambda: httpx.Response(200, content=openai_sse(["А", "Б"])))
    client = LLMClient(settings, transport=transport)
    assert [token async for token in client.stream([], "r")] == ["А", "Б"]
    await client.close()
