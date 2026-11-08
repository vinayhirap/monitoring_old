"""Teach FastAPI's jsonable_encoder about numpy scalars and arrays.

Without this, any endpoint that returns a numpy.bool_ / numpy.int64 / ndarray
fails with: TypeError: 'numpy.bool_' object is not iterable  ->  HTTP 500.
Importing this module (done once from app.main) fixes every route at once.
"""
import numpy as np
from fastapi.encoders import ENCODERS_BY_TYPE


def _register() -> None:
    ENCODERS_BY_TYPE[np.bool_] = bool
    for t in (np.int8, np.int16, np.int32, np.int64,
              np.uint8, np.uint16, np.uint32, np.uint64):
        ENCODERS_BY_TYPE[t] = int
    for t in (np.float16, np.float32, np.float64):
        ENCODERS_BY_TYPE[t] = float
    ENCODERS_BY_TYPE[np.ndarray] = lambda a: a.tolist()


_register()
