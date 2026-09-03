from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_embedding_model_is_staged():
    """The ONNX embedder must be on disk; nothing downloads at runtime."""
    assert (settings.embed_model_dir / "onnx" / "model_qint8_avx512_vnni.onnx").exists()


def test_binds_loopback_only():
    assert settings.host == "127.0.0.1"
