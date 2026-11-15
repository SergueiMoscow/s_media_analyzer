"""Юнит-тесты обёртки модели (без загрузки InsightFace)."""
from common.settings import settings
from services import model as model_service


def test_model_dir_exists_detects_onnx(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MODEL_ROOT', str(tmp_path))
    assert model_service.model_dir_exists() is False

    model_dir = tmp_path / 'models' / settings.MODEL_NAME
    model_dir.mkdir(parents=True)
    (model_dir / 'buffalo_l.onnx').write_bytes(b'fake')
    assert model_service.model_dir_exists() is True


def test_model_root_default():
    assert isinstance(model_service.model_root(), str)
    assert model_service.model_available() in (True, False)
