import json
import numpy as np
from hyperlab.__main__ import main
from hyperlab.io import Cube, save_cube, load_cube, make_synthetic_cube


def test_cli_rgb_roi_is_numeric_and_sam_refused(tmp_path, capsys):
    path = tmp_path/'rgb.npy'
    save_cube(Cube(np.ones((4,5,3),np.uint8), {'data_level':'raw_frame','channel_labels':['R','G','B'],'pixel_format':'RGB8'}),path)
    assert main(['analyze',str(path),'roi']) == 0
    assert json.loads(capsys.readouterr().out)['mean'] == [1,1,1]
    assert main(['analyze',str(path),'angle','--output',str(tmp_path/'angle.npy')]) == 2
    assert 'not a spectral' in capsys.readouterr().err


def test_cli_numeric_export_contains_feature_mapping(tmp_path, capsys):
    cube=make_synthetic_cube()
    cube.metadata['band_validity']=[False]+[True]*(cube.shape[2]-1)
    path=tmp_path/'cube.npy'
    save_cube(cube,path)
    target=tmp_path/'pca.hdr'
    assert main(['analyze',str(path),'pca','--output',str(target)]) == 0
    with load_cube(target) as result:
        assert result.metadata['data_level']=='derived_map'
        assert 0 not in result.metadata['feature_indices']
        assert result.valid_mask.any()
