from app.services.fusion import FusionEngine

def test_sitting_is_not_danger():
    f = FusionEngine()
    for _ in range(10):
        d = f.update("1", {"position":"sitting","movement":0,"timestamp":0})
    assert d["event_type"] == "NORMAL"

def test_single_large_motion_is_not_incident():
    f = FusionEngine()
    d = f.update("1", {"position":"standing","movement":100,"timestamp":0})
    assert d["event_type"] == "NORMAL"
