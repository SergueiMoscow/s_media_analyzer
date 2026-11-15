"""Чистая логика обработки лиц: bbox, IoU, cosine, обновление центроида."""
import numpy as np


def l2_normalize(vec) -> list[float]:
    arr = np.asarray(vec, dtype=float)
    norm = float(np.linalg.norm(arr))
    if norm == 0:
        return arr.tolist()
    return (arr / norm).tolist()


def cosine_similarity(a, b) -> float:
    arr_a = np.asarray(a, dtype=float)
    arr_b = np.asarray(b, dtype=float)
    norm_a = float(np.linalg.norm(arr_a))
    norm_b = float(np.linalg.norm(arr_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(arr_a, arr_b) / (norm_a * norm_b))


def normalize_bbox(bbox, img_w: int, img_h: int) -> dict:
    """Пиксельный bbox (x1,y1,x2,y2) -> нормализованные (x,y,w,h) с обрезкой по границам."""
    x1, y1, x2, y2 = bbox
    x1 = max(0.0, min(float(x1), float(img_w)))
    y1 = max(0.0, min(float(y1), float(img_h)))
    x2 = max(0.0, min(float(x2), float(img_w)))
    y2 = max(0.0, min(float(y2), float(img_h)))
    return {
        'x': x1 / img_w,
        'y': y1 / img_h,
        'w': (x2 - x1) / img_w,
        'h': (y2 - y1) / img_h,
    }


def iou(box_a: dict, box_b: dict) -> float:
    """Intersection over Union для bbox в формате (x, y, w, h)."""
    ax1, ay1 = box_a['x'], box_a['y']
    ax2, ay2 = ax1 + box_a['w'], ay1 + box_a['h']
    bx1, by1 = box_b['x'], box_b['y']
    bx2, by2 = bx1 + box_b['w'], by1 + box_b['h']

    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    union = box_a['w'] * box_a['h'] + box_b['w'] * box_b['h'] - inter
    return inter / union if union > 0 else 0.0


def update_centroid(centroid, size: int, embedding) -> tuple[list[float], int]:
    """Скользящее среднее центроида с L2-нормировкой; возвращает (центроид, size)."""
    new = np.asarray(centroid, dtype=float) * size + np.asarray(embedding, dtype=float)
    return l2_normalize(new), size + 1
