import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_composition_param_test_page_returns_200_and_has_media_query_and_autoload_logic():
    resp = client.get('/composition-param-test')
    assert resp.status_code == 200
    assert '@media (max-width: 767px)' in resp.text
    assert 'DOMContentLoaded' in resp.text
    assert 'loadSampleJson' in resp.text
    assert 'renderJson(data)' in resp.text


def test_static_sample_json_and_validate_endpoint():
    sample_resp = client.get('/static/examples/composition_param_sample.json')
    assert sample_resp.status_code == 200
    payload = sample_resp.json()

    validate_resp = client.post('/composition/validate-param-json', json=payload)
    assert validate_resp.status_code == 200
    body = validate_resp.json()
    assert body['valid'] is True
