import builtins
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from mutex_imatest import usaf_registration


def test_rotated_ink_match_survives_more_numerous_wrong_row_hypotheses(tmp_path, monkeypatch):
    """Coarse triplets cannot decide the orientation of a repetitive strip."""
    width, height = 400, 1000
    reference = np.full((height, width), 255, np.uint8)
    rng = np.random.default_rng(486)
    for y in range(35, height - 35, 35):
        for x in [18, width - 50]:
            text = str(rng.integers(10, 100))
            cv2.putText(reference, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .6, 0, 2)
    path = tmp_path / 'reference.png'
    Image.fromarray(reference).save(path)
    anchors = np.array([[x, .1 + row * .1 + column * .012]
                        for column, x in enumerate([.25, .5, .75]) for row in range(8)])
    truth = np.array([[-width, 0, width - 1], [0, -height, height - 1], [0, 0, 1.]])
    detected = usaf_registration._project(anchors, truth)
    monkeypatch.setattr(usaf_registration, '_triplets', lambda _: [
        {'center': point, 'period': 8., 'direction': 0} for point in detected])
    chart = SimpleNamespace(source_path=None, preview=str(path), fiducials=[
        {'kind': 'usaf', 'direction': 'vertical', 'k': 0, 'position': point.tolist()}
        for point in anchors])
    source = SimpleNamespace(config=SimpleNamespace(cache_path=lambda: tmp_path), fingerprint='synthetic-rotation')

    def count_biased_candidates(values, *args, **kwargs):
        ordered = builtins.sorted(values, *args, **kwargs)
        if ordered and isinstance(ordered[0], tuple) and len(ordered[0]) == 3 and isinstance(ordered[0][2], np.ndarray):
            # Simulate a cropped strip whose wrong orientation has more coarse
            # matches. Ruler ink still identifies the correct physical pose.
            wrong = np.diag([width, height, 1.])
            return [(len(anchors) + 1, 0., wrong.copy()) for _ in range(16)] + ordered
        return ordered

    monkeypatch.setattr(usaf_registration, 'sorted', count_biased_candidates, raising=False)
    fitted, status = usaf_registration._global_oriented(chart, source, np.rot90(reference, 2).copy(), 0)
    assert np.max(np.linalg.norm(usaf_registration._project(anchors, fitted) - detected, axis=1)) < 1.
    assert status['reference_ink_correlation'] > .95
