import os
import sys
import itertools

import numpy as np
import cv2
import yaml
from opt import opt

#from utils_recon.model import Model3D
from utils.model import Model3D
''' The following were copied over from the 6DB toolkit'''
def load_yaml(path):
    with open(path, 'r') as f:
        content = yaml.load(f)
        return content


def load_info(path):
    with open(path, 'r') as f:
        info = yaml.load(f)
        for eid in info.keys():
            if 'cam_K' in info[eid].keys():
                info[eid]['cam_K'] = np.array(info[eid]['cam_K']).reshape((3, 3))
            if 'cam_R_w2c' in info[eid].keys():
                info[eid]['cam_R_w2c'] = np.array(info[eid]['cam_R_w2c']).reshape((3, 3))
            if 'cam_t_w2c' in info[eid].keys():
                info[eid]['cam_t_w2c'] = np.array(info[eid]['cam_t_w2c']).reshape((3, 1))
    return info

def load_gt(path):
    with open(path, 'r') as f:
        gts = yaml.load(f)
        for im_id, gts_im in gts.items():
            for gt in gts_im:
                if 'cam_R_m2c' in gt.keys():
                    gt['cam_R_m2c'] = np.array(gt['cam_R_m2c']).reshape((3, 3))
                if 'cam_t_m2c' in gt.keys():
                    gt['cam_t_m2c'] = np.array(gt['cam_t_m2c']).reshape((3, 1))
    return gts

class Frame:
    def __init__(self):
        self.nr = None
        self.color = None
        self.depth = None
        self.cam = np.identity(3)
        self.gt = []


class Benchmark:
    def __init__(self):
        self.cam = np.identity(3)
        self.models = {}
        self.frames = []


def load_sixd(base_path, seq, nr_frames=0, load_mesh=True, offset=0, max=0):

    bench = Benchmark()
    bench.scale_to_meters = 1
    if os.path.exists(os.path.join(base_path, 'camera.yml')):
        cam_info = load_yaml(os.path.join(base_path,  'camera.yml'))
        bench.cam[0, 0] = cam_info['fx']
        bench.cam[0, 2] = cam_info['cx']
        bench.cam[1, 1] = cam_info['fy']
        bench.cam[1, 2] = cam_info['cy']
        #bench.scale_to_meters = 0.001 * cam_info['depth_scale']

    #collect model info
    model_info = load_yaml(os.path.join(base_path, 'models', 'models_info.yml'))
    for key, val in model_info.items():
        name = '{:02d}'.format(int(key))
        bench.models[name] = Model3D()
        bench.models[name].diameter = val['diameter']
        
    if seq is None:
        return bench

    path = os.path.join(base_path, 'test/{:02d}/'.format(seq))
    info = load_info(os.path.join(path, 'info.yml'))
    gts = load_gt(os.path.join(path, 'gt.yml'))
    # Load frames
    nr_frames = nr_frames if nr_frames > 0 else len(info)
    from_v = offset
    to_v = offset + opt.batch_size
    if (max < to_v):
        to_v = max
    for i in range(from_v, to_v):
        print(i)
        fr = Frame()
        fr.nr = i
        nr_string = '{:04d}'.format(i)
        fr.path = path + "rgb/" + nr_string + ".jpg"
        fr.color = cv2.imread(path + "rgb/" + nr_string + ".jpg").astype(np.float32) / 255.0
        #print ("fr.color's shape:")
        #print (fr.color.shape)
        nr_string = '{:04d}'.format(i)        
        #fr.depth = cv2.imread(path + "depth/" + nr_string + ".png", -1).astype(np.float32) * bench.scale_to_meters
        #print ("fr.depth's shape:")
        #print (fr.depth.shape)
        if os.path.exists(path + 'mask'):
            fr.mask = cv2.imread(path + 'mask/' + nr_string + ".png", -1)

        for gt in gts[i]:
            pose = np.identity(4)
            pose[:3, :3] = gt['cam_R_m2c']
            pose[:3, 3] = np.squeeze(gt['cam_t_m2c']) * bench.scale_to_meters
            fr.gt.append((gt['obj_id'], pose, gt['obj_bb']))

        fr.cam = info[i]['cam_K']
        bench.frames.append(fr)
    print('>>>>>>>>>>>>>>>>>>>>>>>>>')
    if load_mesh:
        # Build a set of all used model IDs for this sequence
        all_gts = list(itertools.chain(*[f.gt for f in bench.frames]))
        #for ID in set([gt[0] for gt in all_gts]):
        #for ID in range(1,16):
        for ID in range(1,opt.total_obj_number):
            name = 'obj_{:02d}'.format(ID)
            bench.models['{:02d}'.format(ID)].load(os.path.join(base_path, 'models/' + name + '.ply'), scale=bench.scale_to_meters)
            # bench.models['{:02d}'.format(ID)].load(os.path.join(base_path, 'models/' + name + '.ply'))

    return bench

if __name__ == '__main__':
    print ("Testing load_sixd ...")
    sixd_base = "/media/data_2/hinterstoisser/"
    nr_frames = 0
    sequence = 4
    bench = load_sixd(sixd_base, nr_frames=nr_frames, seq=sequence)
    model = bench.models
