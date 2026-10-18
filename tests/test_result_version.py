"""Result provenance follows the running software without rewriting history."""
import numpy as np
import tifffile
from mutex_imatest import __version__
from mutex_imatest.analysis.engine import analyze
from mutex_imatest.models import AnalysisResult,ChartDefinition,Region


def test_new_measurements_use_current_version_and_keep_saved_provenance(tmp_path,config):
    path=tmp_path/"input.tif"
    tifffile.imwrite(path,np.full((96,128,3),24000,np.uint16),photometric="rgb",metadata=None)
    chart=ChartDefinition("version-test","Version provenance",[Region("patch","flat",(.1,.1,.8,.8))])
    result=analyze(path,chart,config)
    assert result.measurements and result.app_version==__version__
    saved=tmp_path/"new.json";result.save(saved)
    assert AnalysisResult.load(saved).app_version==__version__
    old=result.to_dict();old["app_version"]="0.7.1"
    historical=AnalysisResult.from_dict(old)
    historical.save(tmp_path/"historical.json")
    assert AnalysisResult.load(tmp_path/"historical.json").app_version=="0.7.1"
    del old["app_version"]
    assert AnalysisResult.from_dict(old).app_version=="unknown"
