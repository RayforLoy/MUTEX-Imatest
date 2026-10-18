"""Sparse CTF measurements stay visibly distinct from a resolution map."""
import copy
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from mutex_imatest.models import AnalysisResult,ChartDefinition,Measurement,Region
from mutex_imatest.heatmap import heatmap_data


def test_sparse_ctf_explanation_tooltips_and_resolution_shortcut(qtbot,tmp_path):
    from mutex_imatest.ui.main_window import MainWindow
    path=tmp_path/'display-fixture.png';Image.new('RGB',(100,100),'white').save(path)
    points=[(x,y) for y in [25,50,75] for x in [25,50,75]]
    regions=[Region(f'u{i}-bars','usaf',((x-5)/100,(y-5)/100,.1,.1),
                    params={'unit_id':f'u{i}','multi_frequency':True,'frequency_index':22,'group':3,'element':5})
             for i,(x,y) in enumerate(points)]
    chart=ChartDefinition('sparse','Sparse CTF display',regions)
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    window.charts=[chart];window.refresh_charts(chart.id);window.import_paths([str(path)])
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']) and window.worker.current is None,timeout=30000)
    metadata=window.entries[0]['metadata']
    rows=[Measurement(f'u{i}-combined-summary',f'unit {i}','usaf_summary','G',(x,y),(x-2,y-2,4,4),
                      {'resolution_limit':.2,'ctf20':.1+i*.01 if (x,y) in [(25,75),(75,25)] else None,'ctf10':None})
          for i,(x,y) in enumerate(points)]
    summary={'units':[{'unit_id':f'u{i}','position':p,'located':True,'rgb_shifts':{},'directions':{}} for i,p in enumerate(points)],
             'threshold':.2,'threshold_mode':'relative','statistics':{},'frequency_indices':[22]}
    result=AnalysisResult(metadata,chart.id,chart.name,rows,{},chart.to_dict(),
                          registration={'homography':[[100,0,0],[0,100,0],[0,0,1]]},optical_summary=summary)
    before=copy.deepcopy(result.to_dict());window.entries[0]['result']=result
    window.metric_selector.setCurrentIndex(window.metric_selector.findData('ctf20'))
    window.update_visuals();qtbot.wait(50)
    assert window.coverage_notice.isVisible() and '2/9' in window.coverage_notice.text()
    assert 'CTF20' in window.coverage_notice.text() and window.resolution_map_button.isVisible()
    tooltips=[a.toolTip() for a in window.viewer.annotations]
    assert any('阈值交点' in tip for tip in tooltips)
    assert np.isnan(heatmap_data(result,'ctf20',width=101,height=101)['field'][50,50])
    qtbot.mouseClick(window.resolution_map_button,Qt.MouseButton.LeftButton)
    assert window.metric_selector.currentData()=='resolution_limit'
    assert not window.coverage_notice.isVisible() and not window.resolution_map_button.isVisible()
    assert len(window.viewer.refresh_overlay()['values'])==9
    window.metric_selector.setCurrentIndex(window.metric_selector.findData('ctf10'));window.update_visuals()
    assert '0/9' in window.coverage_notice.text() and '不代表零分辨率' in window.legend.text()
    assert not np.isfinite(window.viewer.refresh_overlay()['field']).any()
    assert result.to_dict()==before
    window.close()
