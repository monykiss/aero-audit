from aero_audit.vision.apron import DEFAULT_ZONES, occupancy, point_in_polygon, zone_findings
from aero_audit.vision.detect import Detection


def _d(cx, cy):
    return Detection("airplane", 0.9, 0, 0, 10, 10, cx, cy)


def test_point_in_polygon():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert point_in_polygon(0.5, 0.5, sq) and not point_in_polygon(1.5, 0.5, sq)


def test_occupancy_and_findings():
    dets = [_d(0.1, 0.5), _d(0.2, 0.5), _d(0.3, 0.5)]  # 3 on the left, 0 on the right
    occ = occupancy(dets, DEFAULT_ZONES)
    assert occ == {"left-half": 3, "right-half": 0}
    rules = {f.rule_id for f in zone_findings(occ, DEFAULT_ZONES, "img", 0)}
    assert rules == {"OPS-VIS-001", "OPS-VIS-002"}


def test_nms_keeps_highest_confidence_among_overlaps():
    from aero_audit.vision.detect import iou, nms

    a = Detection("airplane", 0.9, 0, 0, 100, 100, 0.1, 0.1)
    b = Detection("airplane", 0.6, 10, 10, 110, 110, 0.1, 0.1)  # heavy overlap with a
    c = Detection("airplane", 0.7, 500, 500, 600, 600, 0.5, 0.5)  # disjoint
    assert iou(a, b) > 0.5 and iou(a, c) == 0
    kept = nms([a, b, c])
    assert kept == [a, c]
