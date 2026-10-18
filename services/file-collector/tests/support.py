from file_collector.app import create_app
from file_collector.config import Settings
from tests.fakes import FakeFiles, FakeObjects, FakePublisher

USER_A = "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d"
USER_B = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def make_settings(**overrides) -> Settings:
    values = {
        "mongodb_uri": "mongodb://mongo:27017/rag",
        "s3_endpoint": "http://minio:9000",
        "s3_access_key": "test-access",
        "s3_secret_key": "test-secret",
        "rabbitmq_url": "amqp://rabbit:5672/",
        "max_upload_bytes": 1_000_000,
        "stale_processing_seconds": 900,
        "log_level": "warning",
    }
    values.update(overrides)
    return Settings(**values)


def build_app(**overrides):
    settings = make_settings(**overrides)
    files = FakeFiles()
    objects = FakeObjects()
    publisher = FakePublisher()
    app = create_app(settings, files=files, objects=objects, publisher=publisher)
    return app, files, objects, publisher
