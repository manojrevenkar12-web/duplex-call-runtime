"""The HTTP side of the runtime, without models: webhook, API, evaluation reports."""

import base64
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dcr import config
from dcr.server import create_app, twilio_signature_ok
from dcr.store import Store


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DCR_REPORTS", str(tmp_path / "reports"))
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DCR_PUBLIC_URL", raising=False)
    store = Store(tmp_path / "calls.sqlite")
    store.save(
        {
            "id": "call-1",
            "started_at": "2026-10-24T20:00:00+00:00",
            "lang": "en",
            "scenario": "en-book-basic",
            "options": {"turn_mode": "model", "speculate": True, "aec": True, "barge_in": True},
            "events": [{"t": 1.0, "kind": "call_start"}],
            "summary": {"turns": [{"turn": 1}], "response_ms": [812.0], "counts": {"interrupt": 0}, "providers": {}, "hedged": 0},
            "outcome": {"bookings": [], "transferred": None},
        }
    )
    return TestClient(create_app(config.settings(), store))  # no `with`: startup (model warm-up) does not run


def test_health_and_metrics(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"ok": True, "live_calls": 0}
    assert "dcr_response_seconds" in client.get("/metrics").text


def test_twiml_connects_the_call_to_the_media_socket(client: TestClient) -> None:
    r = client.post("/twilio/voice?lang=de", headers={"host": "voice.example"})
    assert r.status_code == 200
    assert '<Stream url="wss://voice.example/media">' in r.text
    assert '<Parameter name="lang" value="de"/>' in r.text
    assert 'value="en"' in client.post("/twilio/voice?lang=fr").text  # unknown language: English


def _sign(token: str, url: str, params: dict[str, str]) -> str:
    payload = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def test_twiml_requires_a_valid_twilio_signature_when_a_token_is_set(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("DCR_PUBLIC_URL", "https://voice.example")
    params = {"CallSid": "CA123", "From": "+4915100000000"}
    good = _sign("test-token", "https://voice.example/twilio/voice", params)
    form = {"content-type": "application/x-www-form-urlencoded"}
    assert client.post("/twilio/voice", data=params, headers={**form, "x-twilio-signature": good}).status_code == 200
    assert client.post("/twilio/voice", data=params, headers={**form, "x-twilio-signature": "forged"}).status_code == 403
    assert client.post("/twilio/voice", data={**params, "From": "+1"}, headers={**form, "x-twilio-signature": good}).status_code == 403


def test_signature_matches_twilios_documented_algorithm() -> None:
    # sorted parameters appended name+value to the URL, HMAC-SHA1, base64
    sig = _sign("tok", "https://a.example/x", {"b": "2", "a": "1"})
    assert twilio_signature_ok("tok", "https://a.example/x", {"a": "1", "b": "2"}, sig)
    assert not twilio_signature_ok("other", "https://a.example/x", {"a": "1", "b": "2"}, sig)


def test_calls_api_lists_and_returns_calls(client: TestClient) -> None:
    rows = client.get("/api/calls").json()
    assert [r["id"] for r in rows] == ["call-1"]
    assert rows[0]["turns"] == 1 and rows[0]["response_ms"] == [812.0]
    assert client.get("/api/calls?scenario=en-").json()[0]["scenario"] == "en-book-basic"
    assert client.get("/api/calls?scenario=de-").json() == []
    assert client.get("/api/calls/call-1").json()["events"][0]["kind"] == "call_start"
    assert client.get("/api/calls/nope").status_code == 404


def test_evals_api_lists_every_report_and_skips_broken_ones(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/evals").json() == []
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "eval_dev.json").write_text(json.dumps({"set": "dev", "scenarios": ["a"], "summary": {"full": {}}, "calls": {"full": [1]}}))
    (rep / "eval_set1.json").write_text(json.dumps({"set": "set1", "scenarios": [], "summary": {}, "first_run": True}))
    (rep / "eval_bad.json").write_text("{not json")
    docs = client.get("/api/evals").json()
    assert [d["set"] for d in docs] == ["dev", "set1"]
    assert "calls" not in docs[0]  # summaries only
    assert docs[1]["first_run"] is True


def test_serving_reports_not_ready_before_startup(client: TestClient) -> None:
    assert client.get("/api/serving").json() == {"ready": False}
