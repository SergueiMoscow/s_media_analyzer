"""Юнит-тесты чистой логики обработки лиц."""
from services.faces_service import (
    cosine_similarity,
    iou,
    l2_normalize,
    normalize_bbox,
    update_centroid,
)


def test_l2_normalize():
    vec = l2_normalize([3.0, 4.0])
    assert abs(vec[0] - 0.6) < 1e-9
    assert abs(vec[1] - 0.8) < 1e-9


def test_l2_normalize_zero():
    assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]


def test_cosine_similarity():
    assert abs(cosine_similarity([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(cosine_similarity([1, 0], [0, 1])) < 1e-9


def test_normalize_bbox_clips():
    assert normalize_bbox([-10, -10, 110, 110], 100, 100) == {
        'x': 0.0,
        'y': 0.0,
        'w': 1.0,
        'h': 1.0,
    }


def test_normalize_bbox_center():
    assert normalize_bbox([25, 25, 75, 75], 100, 100) == {
        'x': 0.25,
        'y': 0.25,
        'w': 0.5,
        'h': 0.5,
    }


def test_iou_full_overlap():
    box = {'x': 0.0, 'y': 0.0, 'w': 0.5, 'h': 0.5}
    assert iou(box, box) == 1.0


def test_iou_no_overlap():
    a = {'x': 0.0, 'y': 0.0, 'w': 0.1, 'h': 0.1}
    b = {'x': 0.5, 'y': 0.5, 'w': 0.1, 'h': 0.1}
    assert iou(a, b) == 0.0


def test_update_centroid():
    centroid, size = update_centroid([1.0, 0.0], 1, [0.0, 1.0])
    assert size == 2
    # (1,0)+(0,1) = (1,1) -> нормализовано (0.707, 0.707)
    assert abs(centroid[0] - 0.7071) < 1e-3
    assert abs(centroid[1] - 0.7071) < 1e-3
