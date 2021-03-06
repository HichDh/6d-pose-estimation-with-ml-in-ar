import glob, os, shutil
import random
import yaml
from utils import *
from MeshPly import MeshPly

if not os.path.exists('./labels'):
    os.makedirs('./labels')

w = 640
h = 480

def createTestAndTrainFiles(counter):
    print('creating test and train files')
    test_size = int(counter * 0.3)
    test = random.sample(range(counter), test_size)

    f_test = open('test.txt', "w+")
    f_train = open('train.txt', "w+")
    f_train_range = open('training_range.txt', "w+")

    for i in range(counter):
        img_type = ".jpg"
        if (i in test):
            f_test.write('/JPEGImages/' + format(i, '06') + img_type + "\n")
        else:
            f_train.write('/JPEGImages/' + format(i, '06') + img_type + "\n")
            f_train_range.write(str(i) + "\n")

    f_test.close()
    f_train.close()
    f_train_range.close()






def generate_empty_labels(from_i, n_empty):
    for i in range(from_i, from_i + n_empty):
        f = open('./labels/' + format(i, '06') + '.txt', "w+")
        f.close()







def generateYoloLabels(ply_name):
    global w, h

    mesh = MeshPly(ply_name)
    vertices = np.c_[np.array(mesh.vertices), np.ones((len(mesh.vertices), 1))].transpose()

    with open("./gt.yml", 'r') as stream:
        try:
            with open("./info.yml", 'r') as info_stream:
                
                yaml_gt = yaml.safe_load(stream)
                yaml_info = yaml.safe_load(info_stream)

                for i in range(len(yaml_gt)):

                    img_infos = yaml_gt[i][0]
                    R_gt = np.array(img_infos['cam_R_m2c']).reshape(3, 3)
                    Rt_gt = np.append(R_gt, np.array([img_infos['cam_t_m2c']]).T, axis=1)
                    np.set_printoptions(suppress=True)

                    img_infos = yaml_info[i]
                    i_c = np.array(img_infos['cam_K']).reshape(3, 3)

                    proj_2d_gt = compute_projection(vertices, Rt_gt, i_c)
                    proj_2d_gt = proj_2d_gt.astype(int)

                    max_x = np.max(proj_2d_gt[0])
                    min_x = np.min(proj_2d_gt[0])
                    max_y = np.max(proj_2d_gt[1])
                    min_y = np.min(proj_2d_gt[1])

                    w_x = max_x - min_x
                    w_y = max_y - min_y
                    c_x = min_x + (w_x/2)
                    c_y = min_y + (w_y/2)

                    newLine = '0 ' + str(c_x / w) + ' ' + str(c_y / h) + ' ' + str(w_x / w) + ' ' + str(w_y / h)
                    with open('./labels/' + format(i, '06') + '.txt', 'w') as file:
                        file.write(newLine)
                return len(yaml_gt)
        except yaml.YAMLError as exc:
            print(exc)
    return 0

if __name__ == "__main__":
    # Training settings
    # example: python project_single.py guitar 1499 gibson10x.ply
    if (len(sys.argv) == 1):
        ply_name = 'obj_01.ply'
    else:
        ply_name = sys.argv[1]
    label_count = generateYoloLabels(ply_name)
    label_empty = 2703
    generate_empty_labels(label_count, label_empty)
    createTestAndTrainFiles(label_count + label_empty)