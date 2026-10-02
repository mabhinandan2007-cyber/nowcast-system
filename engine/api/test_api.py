import os
import sys
import pytest
from fastapi.testclient import TestClient

# Ensure engine path is available for imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

from api.main import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "endpoints" in data
    assert data["endpoints"]["status"] == "/status"
    assert data["endpoints"]["hazards"] == "/hazards"


def test_dashboard_endpoint():
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert "NOWCAST" in response.text
    assert "leaflet" in response.text


def test_status_endpoint():
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "data_sources" in data
    
    sources = data["data_sources"]
    expected_sources = [
        "insat", "dwr_proxy", "lightning_proxy", 
        "convective_initiation", "nowcast_optical_flow", "nowcast_convlstm"
    ]
    for src in expected_sources:
        assert src in sources
        assert "type" in sources[src]
        assert "is_mock" in sources[src]
        assert "status" in sources[src]
        
    # Check honest indicator requirements
    assert sources["insat"]["is_mock"] is True
    assert "pending MOSDAC approval" in sources["insat"]["note"]
    assert sources["dwr_proxy"]["is_mock"] is False
    assert sources["lightning_proxy"]["is_mock"] is True
    assert sources["convective_initiation"]["is_mock"] is False


def test_hazards_endpoint():
    response = client.get("/hazards")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert isinstance(data["features"], list)
    assert len(data["features"]) > 0
    
    first = data["features"][0]
    assert "geometry" in first
    assert "properties" in first
    assert "hazard_type" in first["properties"]
    assert "severity" in first["properties"]


def test_hazards_filtering():
    response = client.get("/hazards?severity=severe")
    assert response.status_code == 200
    data = response.json()
    for feat in data["features"]:
        assert feat["properties"]["severity"].lower() == "severe"


def test_forecast_available_model():
    response = client.get("/forecast?model=optical_flow")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "available"
    assert data["model"] == "optical_flow"
    assert len(data["frames"]) > 0
    
    first_frame = data["frames"][0]
    assert "lead_time_minutes" in first_frame
    assert first_frame["lead_time_minutes"] == 30
    assert "geojson" in first_frame
    assert first_frame["geojson"]["type"] == "FeatureCollection"


def test_forecast_lead_time_filter():
    response = client.get("/forecast?model=optical_flow&lead_time=60")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "available"
    assert len(data["frames"]) == 1
    assert data["frames"][0]["lead_time_minutes"] == 60


def test_forecast_missing_model_defensive():
    # convlstm has not run yet, so it must return a defensive not_yet_available response
    response = client.get("/forecast?model=convlstm")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_yet_available"
    assert data["total_frames"] == 0
    assert data["frames"] == []
    assert "not yet available" in data["message"].lower()


def test_replay_endpoint():
    response = client.get("/replay")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "replay_demo"
    assert "status" in data
    assert "hazards" in data
    assert "forecast" in data


def test_websocket_live():
    with client.websocket_connect("/live") as websocket:
        # Receive initial welcome message
        initial_msg = websocket.receive_json()
        assert initial_msg["event"] == "connected"
        assert "status" in initial_msg
        
        # Send ping, receive pong
        websocket.send_json({"action": "ping"})
        pong_msg = websocket.receive_json()
        assert pong_msg["event"] == "pong"
        assert "timestamp" in pong_msg


if __name__ == "__main__":
    pytest.main(["-v", __file__])
