import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/rag")
os.environ.setdefault("QDRANT_URL", "http://qdrant:6333")
os.environ.setdefault("EMBEDDING_URL", "http://embedding:8091")
os.environ.setdefault("LLM_BASE_URL", "http://llm:4000/v1")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "test-model")
