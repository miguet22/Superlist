import json
from unittest.mock import Mock

import fakeredis
import pytest
import redis
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(main, "_redis_client", client)
    monkeypatch.setattr(main, "_redis_mode", "test")
    yield client
    client.close()


def test_create_persists_normalized_item(storage):
    item = main.create_item(main.ItemCreate(name=" Leche ", quantity=" 2 l ", note=" Fria "))
    assert item["name"] == "Leche"
    assert item["quantity"] == "2 l"
    assert item["note"] == "Fria"
    assert item["completed"] is False
    assert json.loads(storage.hget(main.REDIS_KEY_ITEMS, item["id"])) == item


def test_list_stays_empty_without_sample_items():
    assert main.get_all_items() == []
    item = main.create_item(main.ItemCreate(name="Pan"))
    main.delete_item(item["id"])
    assert main.get_all_items() == []
    assert main.get_all_items() == []


def test_list_skips_invalid_json(storage):
    storage.hset(main.REDIS_KEY_ITEMS, "invalid", "{")
    assert main.get_all_items() == []


def test_partial_update_preserves_other_fields():
    item = main.create_item(main.ItemCreate(name="Pan", quantity="2"))
    updated = main.update_item(item["id"], main.ItemUpdate(completed=True))
    assert updated == {**item, "completed": True}
    assert main.update_item(item["id"], main.ItemUpdate(completed=False))["completed"] is False


def test_delete_removes_item(storage):
    item = main.create_item(main.ItemCreate(name="Pan"))
    main.delete_item(item["id"])
    assert not storage.hexists(main.REDIS_KEY_ITEMS, item["id"])


@pytest.mark.parametrize("operation", [lambda: main.update_item("missing", main.ItemUpdate(completed=True)), lambda: main.delete_item("missing")])
def test_missing_item_returns_404(operation):
    with pytest.raises(HTTPException) as exc:
        operation()
    assert exc.value.status_code == 404


def test_clear_only_completed_and_skips_invalid_json(storage):
    pending = main.create_item(main.ItemCreate(name="Pan"))
    done = main.create_item(main.ItemCreate(name="Leche"))
    main.update_item(done["id"], main.ItemUpdate(completed=True))
    storage.hset(main.REDIS_KEY_ITEMS, "invalid", "{")
    assert main.clear_completed_items()["removed_ids"] == [done["id"]]
    assert storage.hexists(main.REDIS_KEY_ITEMS, pending["id"])
    assert main.clear_completed_items()["removed_ids"] == []


def test_health_success():
    assert main.health_check()["redis_connected"] is True


def test_health_connection_failure(monkeypatch):
    monkeypatch.setattr(main, "_redis_client", Mock(ping=Mock(side_effect=redis.ConnectionError("offline"))))
    assert main.health_check()["status"] == "error"


@pytest.mark.parametrize("available", [True, False])
def test_redis_connection_and_fallback(monkeypatch, available):
    monkeypatch.setattr(main, "_redis_client", None)
    real = Mock()
    if not available:
        real.ping.side_effect = redis.ConnectionError("offline")
    monkeypatch.setattr(main.redis, "Redis", Mock(return_value=real))
    client = main.get_redis_client()
    assert (client is real) is available
    assert main.get_redis_client() is client
    if not available:
        assert client.ping()
        client.close()


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "x" * 101}, {"name": "Pan", "quantity": "x" * 31}])
def test_http_rejects_invalid_input(payload):
    with TestClient(main.app) as client:
        assert client.post("/api/items", json=payload).status_code == 422


def test_http_crud_contract():
    with TestClient(main.app) as client:
        response = client.post("/api/items", json={"name": "Pan"})
        assert response.status_code == 201
        item_id = response.json()["id"]
        assert client.put(f"/api/items/{item_id}", json={"completed": True}).status_code == 200
        assert client.delete("/api/items/completed/clear").json()["removed_ids"] == [item_id]
        assert client.delete(f"/api/items/{item_id}").status_code == 404


def test_redis_stats_endpoint():
    with TestClient(main.app) as client:
        # Create an item to have data in redis
        client.post("/api/items", json={"name": "Leche"})
        res = client.get("/api/redis/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "keys" in data
        assert any(k["key"] == main.REDIS_KEY_ITEMS for k in data["keys"])


def test_update_item_all_fields():
    item = main.create_item(main.ItemCreate(name="Original", category="otros", quantity="1", note="N"))
    updated = main.update_item(
        item["id"],
        main.ItemUpdate(name=" Modificado ", category="lacteos", quantity=" 2 un ", note=" Nueva nota ")
    )
    assert updated["name"] == "Modificado"
    assert updated["category"] == "lacteos"
    assert updated["quantity"] == "2 un"
    assert updated["note"] == "Nueva nota"


def test_redis_stats_with_string_and_raw_hash(storage):
    storage.set("simple_string", "test_value")
    storage.hset("custom_hash", "raw_field", "non_json_value")
    with TestClient(main.app) as client:
        res = client.get("/api/redis/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        keys_map = {k["key"]: k for k in data["keys"]}
        assert "simple_string" in keys_map
        assert keys_map["simple_string"]["data"] == "test_value"
        assert "custom_hash" in keys_map
        assert keys_map["custom_hash"]["data"]["raw_field"] == "non_json_value"


def test_redis_stats_error_handling(monkeypatch):
    mock_client = Mock()
    mock_client.keys.side_effect = Exception("Redis error")
    monkeypatch.setattr(main, "_redis_client", mock_client)
    with TestClient(main.app) as client:
        res = client.get("/api/redis/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "error"
        assert "Redis error" in data["error"]


@pytest.mark.parametrize("url,expected_mode", [
    ("redis://user:pass@remote-host:6379", "Servidor Redis (remote-host:6379)"),
    ("redis://localhost:6379", "Servidor Redis (redis://localhost:6379)"),
])
def test_redis_connection_from_url(monkeypatch, url, expected_mode):
    monkeypatch.setattr(main, "REDIS_URL", url)
    monkeypatch.setattr(main, "_redis_client", None)
    real = Mock()
    monkeypatch.setattr(main.redis, "from_url", Mock(return_value=real))
    client = main.get_redis_client()
    assert client is real
    assert main._redis_mode == expected_mode


def test_identify_api_node_middleware():
    with TestClient(main.app) as client:
        response = client.get("/api/health")
        assert "X-API-Node" in response.headers


def test_suggestions_monolith_empty():
    res = main.suggestions.get_suggestions([], force_mode="monolith")
    assert res["mode"] == "monolith"
    assert res["status"] == "online"
    assert res["degraded"] is False
    assert len(res["suggestions"]) > 0


def test_suggestions_monolith_associations():
    items = [{"name": "Fideos Tallarines", "category": "despensa"}]
    res = main.suggestions.get_suggestions(items, force_mode="monolith")
    names = [s["name"] for s in res["suggestions"]]
    assert "Salsa de Tomate" in names or "Queso Rallado" in names


def test_suggestions_microservice_success(monkeypatch):
    mock_response = Mock()
    mock_response.read.return_value = json.dumps({
        "suggestions": [{"name": "Queso", "category": "lacteos", "quantity": "1", "reason": "test"}],
        "insights": {"item_count": 1, "categories_present": ["despensa"], "tip": "test tip"}
    }).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=None)

    monkeypatch.setattr(main.suggestions.urllib.request, "urlopen", Mock(return_value=mock_response))
    res = main.suggestions.get_suggestions([], service_url="http://mock:8001/api/suggestions")
    assert res["mode"] == "microservice"
    assert res["status"] == "online"
    assert res["degraded"] is False
    assert res["suggestions"][0]["name"] == "Queso"


def test_suggestions_microservice_graceful_degradation(monkeypatch):
    monkeypatch.setattr(
        main.suggestions.urllib.request,
        "urlopen",
        Mock(side_effect=Exception("Connection refused"))
    )
    res = main.suggestions.get_suggestions([], service_url="http://mock:8001/api/suggestions")
    assert res["mode"] == "microservice"
    assert res["status"] == "degraded"
    assert res["degraded"] is True
    assert "Fallo al conectar" in res["error_detail"]
    assert len(res["suggestions"]) > 0


def test_suggestions_endpoint():
    with TestClient(main.app) as client:
        res = client.get("/api/suggestions?force_mode=monolith")
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "monolith"
        assert "suggestions" in data


