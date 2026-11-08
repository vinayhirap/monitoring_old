"""numpy values must survive FastAPI serialisation (regression: HTTP 500 on
/api/astro-lab/measure and /api/calibration/quick)."""
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.json_compat  # noqa: F401  (registers the encoders)


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/x")
    def x():
        return {
            "flag": np.bool_(True),
            "n": np.int64(7),
            "f": np.float32(1.5),
            "arr": np.array([1, 2, 3]),
            "nested": [{"ok": np.bool_(False)}],
        }

    return TestClient(app)


def test_numpy_values_serialise():
    r = _client().get("/x")
    assert r.status_code == 200
    assert r.json() == {
        "flag": True, "n": 7, "f": 1.5, "arr": [1, 2, 3],
        "nested": [{"ok": False}],
    }
