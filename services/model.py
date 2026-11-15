"""Обёртка над InsightFace: детекция + эмбеддинги (CPU, ленивая загрузка)."""
import os
import threading
from dataclasses import dataclass

from common.settings import settings

_model = None
_model_lock = threading.Lock()


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (пиксели детект-изображения)
    det_score: float
    embedding: list[float]  # 512, L2-нормализован


def model_root() -> str:
    """Базовый каталог InsightFace (MODEL_ROOT или ~/.insightface).

    Сам каталог моделей — ``<root>/models/<MODEL_NAME>`` (соглашение InsightFace).
    """
    return settings.MODEL_ROOT or os.path.expanduser('~/.insightface')


def model_dir_exists() -> bool:
    """Модель скачана на диск (не загружая её в память)."""
    model_dir = os.path.join(model_root(), 'models', settings.MODEL_NAME)
    if not os.path.isdir(model_dir):
        return False
    return any(name.endswith('.onnx') for name in os.listdir(model_dir))


def model_ready() -> bool:
    """Модель загружена в память."""
    return _model is not None


def model_available() -> bool:
    """Модель доступна: загружена или скачана на диск."""
    return model_ready() or model_dir_exists()


def load_model():
    """Загружает (при первом вызове — скачивает) модель; возвращает FaceAnalysis."""
    global _model
    with _model_lock:
        if _model is None:
            from insightface.app import FaceAnalysis

            _model = FaceAnalysis(
                name=settings.MODEL_NAME,
                root=model_root(),
                providers=['CPUExecutionProvider'],
            )
            _model.prepare(ctx_id=0, det_size=(640, 640))
        return _model


def detect_and_embed(img_bgr, det_score_min: float) -> list[Detection]:
    """Детекция лиц и расчёт эмбеддингов на BGR-изображении."""
    model = load_model()
    faces = model.get(img_bgr)
    result = []
    for face in faces:
        if face.det_score < det_score_min:
            continue
        result.append(
            Detection(
                bbox=tuple(float(c) for c in face.bbox),
                det_score=float(face.det_score),
                embedding=[float(x) for x in face.normed_embedding],
            )
        )
    return result
