from fastapi.testclient import TestClient

from tests.fakes import FakeEncoder


def test_query_prefix_is_question_answering(client: TestClient, encoder: FakeEncoder) -> None:
    response = client.post(
        "/embed",
        json={"texts": ["What causes the northern lights?"], "input_type": "query"},
    )
    assert response.status_code == 200
    assert encoder.seen == [["task: question answering | query: What causes the northern lights?"]]


def test_document_prefix_uses_the_file_name(client: TestClient, encoder: FakeEncoder) -> None:
    response = client.post(
        "/embed",
        json={"texts": ["текст чанка"], "input_type": "document", "title": "Отчёт.pdf"},
    )
    assert response.status_code == 200
    assert encoder.seen == [["title: Отчёт.pdf | text: текст чанка"]]
    assert response.json()["model"] == "google/embeddinggemma-2"


def test_prefix_strips_edges_and_keeps_one_separator(
    client: TestClient, encoder: FakeEncoder
) -> None:
    response = client.post(
        "/embed",
        json={
            "texts": ["  hello  ", "world"],
            "input_type": "document",
            "title": "  Report.pdf  ",
        },
    )
    assert response.status_code == 200
    assert encoder.seen == [
        [
            "title: Report.pdf | text: hello",
            "title: Report.pdf | text: world",
        ]
    ]


def test_request_id_is_forwarded_to_the_encoder(client: TestClient, encoder: FakeEncoder) -> None:
    request_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    response = client.post(
        "/embed",
        json={"texts": ["question"], "input_type": "query"},
        headers={"X-Request-Id": request_id},
    )
    assert response.status_code == 200
    assert encoder.request_ids == [request_id]
