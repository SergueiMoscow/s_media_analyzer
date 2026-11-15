"""Юнит-тесты определения типа файлов и нормализации folder_path."""
from services.scanner import file_kind, kinds_for, normalize_folder_path


def test_file_kind():
    assert file_kind('a.jpg') == 'image'
    assert file_kind('b.HEIC') == 'image'
    assert file_kind('c.mp4') == 'video'
    assert file_kind('d.txt') == 'other'
    assert file_kind('noext') == 'other'


def test_kinds_for():
    assert kinds_for('image') == ['faces', 'geo']
    assert kinds_for('video') == ['geo']
    assert kinds_for('other') == []


def test_normalize_folder_path():
    assert normalize_folder_path('2000') == '2000'
    assert normalize_folder_path('/2000/') == '2000'
    assert normalize_folder_path('/a/b/') == 'a/b'
    assert normalize_folder_path('') == ''
