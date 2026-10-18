from types import SimpleNamespace
import numpy as np
from mutex_imatest.detection import transform_box
from mutex_imatest.analysis_audit import reason_for
from mutex_imatest.models import Measurement


def test_fully_off_frame_boxes_have_zero_never_negative_dimensions():
    for x,y in [(1.2,.5),(-1,.5),(.5,1.2),(.5,-1)]:
        box,outside=transform_box((x,y,.1,.1),np.diag([100,100,1.]),100,100)
        assert outside and min(box[2:])==0 and min(box)>=0
        assert box[0]+box[2]<=100 and box[1]+box[3]<=100


def test_registration_audit_separates_uncovered_and_in_frame_failures():
    m=Measurement('unit-combined-summary','','usaf_summary','G',(1,1),(0,0,0,0),flags=['registration_failed'])
    r=SimpleNamespace(registration={'unit_diagnostics':{'unit':{'status':'outside_image'}}},optical_summary={})
    assert reason_for(r,m,'ctf20')=='outside_image'
    r.registration['unit_diagnostics']['unit']['status']='insufficient_matches'
    assert reason_for(r,m,'ctf20')=='insufficient_matches'
