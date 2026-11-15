def test_health_shape(client):
    response = client.get('/health')
    assert response.status_code in (200, 503)
    body = response.json()
    assert {'status', 'db', 'model', 'scan_roots', 'faces_dir'} <= set(body)


def test_root(client):
    response = client.get('/')
    assert response.status_code == 200
    body = response.json()
    assert body['service'] == 's_media_analyzer'
