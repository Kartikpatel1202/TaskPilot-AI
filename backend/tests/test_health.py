from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.schemas.common import HealthResponse


def test_health_returns_200_and_matches_schema(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = HealthResponse.model_validate(response.json())
    assert body.status == "healthy"
    assert body.service == "taskpilot-backend"
    assert body.version == "0.1.0"
    assert set(response.json()) == {"status", "service", "version", "timestamp"}


def test_health_timestamp_is_dynamic_utc(client: TestClient) -> None:
    ts = datetime.fromisoformat(client.get("/api/v1/health").json()["timestamp"].replace("Z", "+00:00"))
    assert ts.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - ts) < timedelta(seconds=5)


def test_request_id_header_and_unknown_route_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "Traceback" not in response.text


def test_cors_allows_configured_origin_only(client: TestClient) -> None:
    ok = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/api/v1/health",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert bad.headers.get("access-control-allow-origin") is None
