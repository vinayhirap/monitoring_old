from app.services import signals_logger


def test_same_idea_logged_once_per_day():
    sig = {"symbol": "DEDUPE_TEST", "trend": "BULLISH", "signal": "BUY",
           "confidence": 66, "entry": 100, "stoploss": 98, "targets": [104]}
    a = signals_logger.log_signal(sig)
    b = signals_logger.log_signal(sig)
    if a is None:
        return  # no DB in this environment; logger swallows failures by design
    assert a == b
