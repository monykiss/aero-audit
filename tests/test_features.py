from aero_audit.features import haversine_nm, heading_delta


def test_haversine_jfk_lax():
    d = haversine_nm(40.6413, -73.7781, 33.9416, -118.4085)
    assert 2130 < d < 2170  # published great-circle distance ~2151 nm


def test_heading_delta_wraps():
    assert heading_delta(350, 10) == 20
    assert heading_delta(10, 350) == -20
    assert heading_delta(90, 270) == 180
