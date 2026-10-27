import pytest
from pydantic import ValidationError

from takt.config import Settings

from .helpers import client_for


@pytest.mark.asyncio
async def test_health_and_openapi_have_stable_operation_ids():
    async with client_for() as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        paths = (await client.get("/openapi.json")).json()["paths"]
        assert paths["/api/v1/time/calculate"]["post"]["operationId"] == "calculateWorkday"


@pytest.mark.asyncio
async def test_calculation_endpoint_validates_timestamps_and_intervals():
    async with client_for() as client:
        payload = {
            "work_date": "2026-10-27",
            "required_minutes": 360,
            "as_of": "2026-10-27T13:10:00+03:00",
            "intervals": [
                {
                    "started_at": "2026-10-27T08:30:00+03:00",
                    "breaks": [
                        {
                            "started_at": "2026-10-27T12:00:00+03:00",
                            "ended_at": "2026-10-27T12:30:00+03:00",
                        }
                    ],
                }
            ],
        }
        response = await client.post("/api/v1/time/calculate", json=payload)
        assert response.status_code == 200
        assert response.json()["credited_seconds"] == 15000
        payload["intervals"][0]["started_at"] = "2026-10-27T08:30:00"
        assert (await client.post("/api/v1/time/calculate", json=payload)).status_code == 422
        payload["intervals"][0]["started_at"] = "2026-10-27T14:00:00+03:00"
        response = await client.post("/api/v1/time/calculate", json=payload)
        assert response.json()["detail"]["code"] == "invalid_intervals"


@pytest.mark.asyncio
async def test_readiness_fails_when_database_is_unavailable():
    settings = Settings(database_url="postgresql+psycopg://invalid:invalid@127.0.0.1:1/absent")
    async with client_for(settings) as client:
        assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.parametrize("url", ["sqlite:///test.db", "postgresql://localhost/takt", "not-a-url"])
def test_configuration_requires_postgresql(url):
    with pytest.raises(ValidationError):
        Settings(database_url=url)


def test_configuration_rejects_unknown_time_zone():
    with pytest.raises(ValidationError):
        Settings(time_zone="invalid/time-zone")
