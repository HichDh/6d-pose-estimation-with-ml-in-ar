import os
import sys
import time
import math
from multiprocessing import Queue as pQueue
from threading import Thread

import cv2
import numpy as np
import torch
import torch.multiprocessing as mp
import torch.utils.data as data
import torchvision.transforms as transforms
from PIL import Image, ImageDraw
from torch.autograd import Variable

from KPD.src.utils.eval import getPrediction
from KPD.src.utils.img import load_image, cropBox, im_to_torch
from opt import opt
from pPose_nms import pose_nms
from utils.utils import pnp
from yolo.darknet import Darknet
from yolo.preprocess import prep_image, prep_frame
from yolo.util import dynamic_write_results

# import the Queue class from Python 3
if sys.version_info >= (3, 0):
    from queue import Queue, LifoQueue
# otherwise, import the Queue class for Python 2.7
else:
    from Queue import Queue, LifoQueue

# if opt.vis_fast:
#     from fn import vis_frame_fast as vis_frame
# else:
#     from fn import vis_frame

# This class is deprecated, use the next one instead.
class Image_loader(data.Dataset):
    def __init__(self, im_names, format='yolo'):
        super(Image_loader, self).__init__()
        self.img_dir = opt.inputpath
        self.imglist = im_names
        self.transform = transforms.Compose([
            # transforms.ToTensor(),
            # transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
            transforms.Resize(size=(reso, reso), interpolation=3),
            transforms.ToTensor()
        ])
        self.format = format

    def getitem_ssd(self, index):
        im_name = self.imglist[index].rstrip('\n').rstrip('\r')
        im_name = os.path.join(self.img_dir, im_name)
        im = Image.open(im_name)
        inp = load_image(im_name)
        if im.mode == 'L':
            im = im.convert('RGB')

        ow = oh = 512
        im = im.resize((ow, oh))
        im = self.transform(im)
        return im, inp, im_name

    def getitem_yolo(self, index):
        inp_dim = int(opt.inp_dim)
        im_name = self.imglist[index].rstrip('\n').rstrip('\r')
        im_name = os.path.join(self.img_dir, im_name)

        # For data preprocessing

        im, orig_img, im_dim = prep_image(im_name, inp_dim)
        im_dim = torch.FloatTensor([im_dim]).repeat(1, 2)
        inp = self.transform(Image.open(im_name))

        # inp = load_image(im_name)
        return im, inp, orig_img, im_name, im_dim

    def __getitem__(self, index):
        if self.format == 'ssd':
            return self.getitem_ssd(index)
        elif self.format == 'yolo':
            return self.getitem_yolo(index)
        else:
            raise NotImplementedError

    def __len__(self):
        return len(self.imglist)

class ImageLoader:
    def __init__(self, im_names, batchSize=1, format='yolo', queueSize=50, reso=608):
        self.img_dir = opt.inputpath
        self.imglist = im_names
        self.transform = transforms.Compose([
            # transforms.ToTensor(),
            # transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
            transforms.Resize(size=(reso, reso), interpolation=3),
            transforms.ToTensor()
        ])
        self.format = format # 'yolo'

        self.batchSize = batchSize
        self.datalen = len(self.imglist) # total data length
        leftover = 0
        if (self.datalen) % batchSize:
            leftover = 1
        self.num_batches = self.datalen // batchSize + leftover

        # initialize the queue used to store data
        if opt.sp: # torch 0.4.1 can only use sp
            self.Q = Queue(maxsize=queueSize)
        else:
            self.Q = mp.Queue(maxsize=queueSize)

    def start(self):
        # start a thread to read frames from the file video stream
        if self.format == 'ssd':
            if opt.sp:
                p = Thread(target=self.getitem_ssd, args=())
            else:
                p = mp.Process(target=self.getitem_ssd, args=())
        elif self.format == 'yolo':
            if opt.sp:
                p = Thread(target=self.getitem_yolo, args=())
            else:
                p = mp.Process(target=self.getitem_yolo, args=())
        else:
            raise NotImplementedError        
        p.daemon = True
        p.start()
        return self

    def getitem_ssd(self):
        length = len(self.imglist)
        for index in range(length):
            im_name = self.imglist[index].rstrip('\n').rstrip('\r')
            im_name = os.path.join(self.img_dir, im_name)
            im = Image.open(im_name)
            inp = load_image(im_name)
            if im.mode == 'L':
                im = im.convert('RGB')

            ow = oh = 512
            im = im.resize((ow, oh))
            im = self.transform(im)
            while self.Q.full():
                time.sleep(2)
            self.Q.put((im, inp, im_name))

    def getitem_yolo(self):
        for i in range(self.num_batches):
            img = []
            orig_img = []
            im_name = []
            im_dim_list = []
            for k in range(i*self.batchSize, min((i +  1)*self.batchSize, self.datalen)):
                inp_dim = int(opt.inp_dim)
                im_name_k = self.imglist[k].rstrip('\n').rstrip('\r')
                im_name_k = os.path.join(self.img_dir, im_name_k)
                img_k, orig_img_k, im_dim_list_k = prep_image(im_name_k, inp_dim)
                # For data preprocessing
                img_k = self.transform(Image.open(im_name_k).convert('RGB')).unsqueeze(0)

                img.append(img_k)
                orig_img.append(orig_img_k)
                im_name.append(im_name_k)
                im_dim_list.append(im_dim_list_k)

            with torch.no_grad():

                img = torch.cat(img)
                im_dim_list = torch.FloatTensor(im_dim_list).repeat(1,2)
                im_dim_list_ = im_dim_list


            while self.Q.full():
                time.sleep(2)
            
            self.Q.put((img, orig_img, im_name, im_dim_list))

    def getitem(self):
        # called in det_loader
        return self.Q.get()

    def length(self):
        return len(self.imglist)

    def len(self):
        return self.Q.qsize()

# Original function in alphapose
class VideoLoader:
    def __init__(self, path, batchSize=1, queueSize=50):
        # initialize the file video stream along with the boolean
        # used to indicate if the thread should be stopped or not
        self.path = path
        self.stream = cv2.VideoCapture(path)
        assert self.stream.isOpened(), 'Cannot capture source'
        self.stopped = False
        

        self.batchSize = batchSize
        self.datalen = int(self.stream.get(cv2.CAP_PROP_FRAME_COUNT))
        leftover = 0
        if (self.datalen) % batchSize:
            leftover = 1
        self.num_batches = self.datalen // batchSize + leftover

        # initialize the queue used to store frames read from
        # the video file
        if opt.sp:
            self.Q = Queue(maxsize=queueSize)
        else:
            self.Q = mp.Queue(maxsize=queueSize)

    def length(self):
        return self.datalen

    def start(self):
        # start a thread to read frames from the file video stream
        if opt.sp: # True
            t = Thread(target=self.update, args=())
            t.daemon = True
            t.start()
        else:
            p = mp.Process(target=self.update, args=())
            p.daemon = True
            p.start()
        return self

    def update(self):
        stream = cv2.VideoCapture(self.path)
        assert stream.isOpened(), 'Cannot capture source'

        for i in range(self.num_batches):
            img = []
            orig_img = []
            im_name = []
            im_dim_list = []
            for k in range(i*self.batchSize, min((i +  1)*self.batchSize, self.datalen)):
                inp_dim = int(opt.inp_dim)
                (grabbed, frame) = stream.read()
                # if the `grabbed` boolean is `False`, then we have
                # reached the end of the video file
                if not grabbed:
                    self.Q.put((None, None, None, None))
                    print('===========================> This video get '+str(k)+' frames in total.')
                    sys.stdout.flush()
                    return
                # process and add the frame to the queue
                img_k, orig_img_k, im_dim_list_k = prep_frame(frame, inp_dim)
            
                img.append(img_k)
                orig_img.append(orig_img_k)
                im_name.append(str(k)+'.jpg')
                im_dim_list.append(im_dim_list_k)

            with torch.no_grad():
            
                img = torch.cat(img)
                im_dim_list = torch.FloatTensor(im_dim_list).repeat(1,2)
                im_dim_list_ = im_dim_list


            while self.Q.full():
                time.sleep(2)
            
            self.Q.put((img, orig_img, im_name, im_dim_list))

    def videoinfo(self):
        # indicate the video info
        fourcc=int(self.stream.get(cv2.CAP_PROP_FOURCC))
        fps=self.stream.get(cv2.CAP_PROP_FPS)
        frameSize=(int(self.stream.get(cv2.CAP_PROP_FRAME_WIDTH)),int(self.stream.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        return (fourcc,fps,frameSize)

    def getitem(self):
        # return next frame in the queue
        return self.Q.get()

    def len(self):
        return self.Q.qsize()


class DetectionLoader:
    def __init__(self, dataloder, obj_id, batchSize=1, queueSize=1024):
        # initialize the file video stream along with the boolean
        # used to indicate if the thread should be stopped or not
        cfg_path = "yolo/cfg/yolo-kuka-single-tight.cfg"
        weights_path = 'models/yolo/{:02d}.weights'.format(obj_id)
        self.det_model = Darknet(cfg_path, reso=int(opt.inp_dim))
        self.det_model.load_weights(weights_path)
        print("Loading YOLO cfg from", cfg_path)
        print("Loading YOLO weights from", weights_path)
        self.det_model.eval()
        self.det_model.net_info['height'] = opt.inp_dim #input_dimension
        self.det_inp_dim = int(self.det_model.net_info['height'])
        assert self.det_inp_dim % 32 == 0
        assert self.det_inp_dim > 32
        self.det_model.cuda()
        self.det_model.eval()

        self.stopped = False
        self.dataloder = dataloder
        self.batchSize = batchSize
        self.datalen = self.dataloder.length()
        leftover = 0
        if (self.datalen) % batchSize:
            leftover = 1
        self.num_batches = self.datalen // batchSize + leftover
        # initialize the queue used to store frames read from
        # the video file
        if opt.sp:
            self.Q = Queue(maxsize=queueSize)
        else:
            self.Q = mp.Queue(maxsize=queueSize)

    def start(self):
        # start a thread to read frames from the file video stream
        if opt.sp:
            t = Thread(target=self.update, args=())
            t.daemon = True
            t.start()
        else:
            p = mp.Process(target=self.update, args=())
            p.daemon = True
            p.start()
        return self

    def update(self):
        # keep looping the whole dataset
        for i in range(self.num_batches):
            img, orig_img, im_name, im_dim_list = self.dataloder.getitem()
            if img is None:
                self.Q.put((None, None, None, None, None, None, None))
                return

            with torch.no_grad():
                img = img.cuda()
                # Critical, use yolo to do object detection here!

                prediction = self.det_model(img)
                # NMS process
                dets = dynamic_write_results(prediction, opt.confidence, opt.num_classes, nms=True, nms_conf=opt.nms_thesh)
                if isinstance(dets, int) or dets.shape[0] == 0:
                    for k in range(len(orig_img)):
                        if self.Q.full():
                            time.sleep(2)
                        self.Q.put((orig_img[k], im_name[k], None, None, None, None, None))
                    continue
                dets = dets.cpu()

                # Scale for SIXD dataset

                reso = self.det_inp_dim
                im_dim_list = torch.index_select(im_dim_list,0, dets[:, 0].long())
                w, h = im_dim_list[:,0], im_dim_list[:,1]
                w_ratio = w / reso
                h_ratio = h / reso
                boxes = dets[:, 1:5]
                boxes[:,0] = boxes[:,0] * w_ratio
                boxes[:,1] = boxes[:,1] * h_ratio
                boxes[:,2] = boxes[:,2] * w_ratio
                boxes[:,3] = boxes[:,3] * h_ratio
                scores = dets[:, 5:6]
                
                # im_dim_list = torch.index_select(im_dim_list,0, dets[:, 0].long())
                # scaling_factor = torch.min(self.det_inp_dim / im_dim_list, 1)[0].view(-1, 1)

                # # coordinate transfer
                # dets[:, [1, 3]] -= (self.det_inp_dim - scaling_factor * im_dim_list[:, 0].view(-1, 1)) / 2
                # dets[:, [2, 4]] -= (self.det_inp_dim - scaling_factor * im_dim_list[:, 1].view(-1, 1)) / 2

                # dets[:, 1:5] /= scaling_factor
                # for j in range(dets.shape[0]):
                #     dets[j, [1, 3]] = torch.clamp(dets[j, [1, 3]], 0.0, im_dim_list[j, 0])
                #     dets[j, [2, 4]] = torch.clamp(dets[j, [2, 4]], 0.0, im_dim_list[j, 1])
                # boxes = dets[:, 1:5]
                # scores = dets[:, 5:6]

            img = Image.open(im_name[0])
            draw = ImageDraw.Draw(img)
            for i in range(boxes.shape[0]):
                x1, y1, x2, y2 = boxes[i,0], boxes[i,1], boxes[i,2], boxes[i,3]
                objectness = 'conf: %.2f' % scores
                draw.rectangle((x1, y1, x2, y2), outline='red')

            # img.save(im_name[0].replace('rgb', 'results'))

            for k in range(len(orig_img)):
                boxes_k = boxes[dets[:,0]==k]
                if isinstance(boxes_k, int) or boxes_k.shape[0] == 0:
                    if self.Q.full():
                        time.sleep(2)
                    self.Q.put((orig_img[k], im_name[k], None, None, None, None, None))
                    continue
                inps = torch.zeros(boxes_k.size(0), 3, opt.inputResH, opt.inputResW)
                pt1 = torch.zeros(boxes_k.size(0), 2)
                pt2 = torch.zeros(boxes_k.size(0), 2)
                if self.Q.full():
                    time.sleep(2)
                self.Q.put((orig_img[k], im_name[k], boxes_k, scores[dets[:,0]==k], inps, pt1, pt2))

    def read(self):
        # return next frame in the queue
        return self.Q.get()

    def len(self):
        # return queue len
        return self.Q.qsize()


class DetectionProcessor:
    def __init__(self, detectionLoader, queueSize=1024):
        # initialize the file video stream along with the boolean
        # used to indicate if the thread should be stopped or not
        self.detectionLoader = detectionLoader
        self.stopped = False
        self.datalen = self.detectionLoader.datalen

        # initialize the queue used to store data
        if opt.sp:
            self.Q = Queue(maxsize=queueSize)
        else:
            self.Q = pQueue(maxsize=queueSize)

    def start(self):
        # start a thread to read frames from the file video stream
        if opt.sp:
            t = Thread(target=self.update, args=())
            t.daemon = True
            t.start()
        else:
            p = mp.Process(target=self.update, args=())
            p.daemon = True
            p.start()
        return self

    def update(self):
        # keep looping the whole dataset
        for i in range(self.datalen):
            
            with torch.no_grad():
                (orig_img, im_name, boxes, scores, inps, pt1, pt2) = self.detectionLoader.read()
                if orig_img is None:
                    self.Q.put((None, None, None, None, None, None, None))
                    return
                if boxes is None or boxes.nelement() == 0:
                    while self.Q.full():
                        time.sleep(0.2)
                    self.Q.put((None, orig_img, im_name, boxes, scores, None, None))
                    continue
                inp = im_to_torch(cv2.cvtColor(orig_img, cv2.COLOR_BGR2RGB))
                inps, pt1, pt2 = crop_from_dets(inp, boxes, inps, pt1, pt2)

                while self.Q.full():
                    time.sleep(0.2)
                self.Q.put((inps, orig_img, im_name, boxes, scores, pt1, pt2))

    def read(self):
        # return next frame in the queue
        return self.Q.get()

    def len(self):
        # return queue len
        return self.Q.qsize()


class VideoDetectionLoader:
    def __init__(self, path, batchSize=4, queueSize=256):
        # initialize the file video stream along with the boolean
        # used to indicate if the thread should be stopped or not
        self.det_model = Darknet("yolo/cfg/yolov3-spp.cfg", reso=int(opt.inp_dim))
        self.det_model.load_weights('models/yolo/yolov3-spp.weights')
        self.det_model.net_info['height'] = opt.inp_dim
        self.det_inp_dim = int(self.det_model.net_info['height'])
        assert self.det_inp_dim % 32 == 0
        assert self.det_inp_dim > 32
        self.det_model.cuda()
        self.det_model.eval()

        self.stream = cv2.VideoCapture(path)
        assert self.stream.isOpened(), 'Cannot capture source'
        self.stopped = False
        self.batchSize = batchSize
        self.datalen = int(self.stream.get(cv2.CAP_PROP_FRAME_COUNT))
        leftover = 0
        if (self.datalen) % batchSize:
            leftover = 1
        self.num_batches = self.datalen // batchSize + leftover
        # initialize the queue used to store frames read from
        # the video file
        self.Q = Queue(maxsize=queueSize)

    def length(self):
        return self.datalen

    def len(self):
        return self.Q.qsize()

    def start(self):
        # start a thread to read frames from the file video stream
        t = Thread(target=self.update, args=())
        t.daemon = True
        t.start()
        return self

    def update(self):
        # keep looping the whole video
        for i in range(self.num_batches):
            img = []
            inp = []
            orig_img = []
            im_name = []
            im_dim_list = []
            for k in range(i*self.batchSize, min((i +  1)*self.batchSize, self.datalen)):
                (grabbed, frame) = self.stream.read()
                # if the `grabbed` boolean is `False`, then we have
                # reached the end of the video file
                if not grabbed:
                    self.stop()
                    return
                # process and add the frame to the queue
                inp_dim = int(opt.inp_dim)
                img_k, orig_img_k, im_dim_list_k = prep_frame(frame, inp_dim)
                inp_k = im_to_torch(orig_img_k)

                img.append(img_k)
                inp.append(inp_k)
                orig_img.append(orig_img_k)
                im_dim_list.append(im_dim_list_k)

            with torch.no_grad():
                ht = inp[0].size(1)
                wd = inp[0].size(2)
                # Human Detection
                img = Variable(torch.cat(img)).cuda()
                im_dim_list = torch.FloatTensor(im_dim_list).repeat(1,2)
                im_dim_list = im_dim_list.cuda()

                prediction = self.det_model(img, CUDA=True)
                # NMS process
                dets = dynamic_write_results(prediction, opt.confidence,
                                    opt.num_classes, nms=True, nms_conf=opt.nms_thesh)
                if isinstance(dets, int) or dets.shape[0] == 0:
                    for k in range(len(inp)):
                        while self.Q.full():
                            time.sleep(0.2)
                        self.Q.put((inp[k], orig_img[k], None, None))
                    continue

                im_dim_list = torch.index_select(im_dim_list,0, dets[:, 0].long())
                scaling_factor = torch.min(self.det_inp_dim / im_dim_list, 1)[0].view(-1, 1)

                # coordinate transfer
                dets[:, [1, 3]] -= (self.det_inp_dim - scaling_factor * im_dim_list[:, 0].view(-1, 1)) / 2
                dets[:, [2, 4]] -= (self.det_inp_dim - scaling_factor * im_dim_list[:, 1].view(-1, 1)) / 2

                dets[:, 1:5] /= scaling_factor
                for j in range(dets.shape[0]):
                    dets[j, [1, 3]] = torch.clamp(dets[j, [1, 3]], 0.0, im_dim_list[j, 0])
                    dets[j, [2, 4]] = torch.clamp(dets[j, [2, 4]], 0.0, im_dim_list[j, 1])
                boxes = dets[:, 1:5].cpu()
                scores = dets[:, 5:6].cpu()

            for k in range(len(inp)):
                while self.Q.full():
                    time.sleep(0.2)
                self.Q.put((inp[k], orig_img[k], boxes[dets[:,0]==k], scores[dets[:,0]==k]))

    def videoinfo(self):
        # indicate the video info
        fourcc=int(self.stream.get(cv2.CAP_PROP_FOURCC))
        fps=self.stream.get(cv2.CAP_PROP_FPS)
        frameSize=(int(self.stream.get(cv2.CAP_PROP_FRAME_WIDTH)),int(self.stream.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        return (fourcc,fps,frameSize)

    def read(self):
        # return next frame in the queue
        return self.Q.get()

    def more(self):
        # return True if there are still frames in the queue
        return self.Q.qsize() > 0

    def stop(self):
        # indicate that the thread should be stopped
        self.stopped = True


class WebcamLoader:
    def __init__(self, webcam, queueSize=256):
        # initialize the file video stream along with the boolean
        # used to indicate if the thread should be stopped or not
        self.stream = cv2.VideoCapture(int(webcam))
        assert self.stream.isOpened(), 'Cannot capture source'
        self.stopped = False
        # initialize the queue used to store frames read from
        # the video file
        self.Q = LifoQueue(maxsize=queueSize)

    def start(self):
        # start a thread to read frames from the file video stream
        t = Thread(target=self.update, args=())
        t.daemon = True
        t.start()
        return self

    def update(self):
        # keep looping infinitely
        while True:
            # otherwise, ensure the queue has room in it
            if not self.Q.full():
                # read the next frame from the file
                (grabbed, frame) = self.stream.read()
                # if the `grabbed` boolean is `False`, then we have
                # reached the end of the video file
                if not grabbed:
                    self.stop()
                    return
                # process and add the frame to the queue
                inp_dim = int(opt.inp_dim)
                img, orig_img, dim = prep_frame(frame, inp_dim)
                inp = im_to_torch(orig_img)
                im_dim_list = torch.FloatTensor([dim]).repeat(1, 2)

                self.Q.put((img, orig_img, inp, im_dim_list))
            else:
                with self.Q.mutex:
                    self.Q.queue.clear()
    def videoinfo(self):
        # indicate the video info
        fourcc=int(self.stream.get(cv2.CAP_PROP_FOURCC))
        fps=self.stream.get(cv2.CAP_PROP_FPS)
        frameSize=(int(self.stream.get(cv2.CAP_PROP_FRAME_WIDTH)),int(self.stream.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        return (fourcc,fps,frameSize)

    def read(self):
        # return next frame in the queue
        return self.Q.get()

    def len(self):
        # return queue size
        return self.Q.qsize()

    def stop(self):
        # indicate that the thread should be stopped
        self.stopped = True


# Checks if a matrix is a valid rotation matrix.
def isRotationMatrix(R) :
    Rt = np.transpose(R)
    shouldBeIdentity = np.dot(Rt, R)
    I = np.identity(3, dtype = R.dtype)
    n = np.linalg.norm(I - shouldBeIdentity)
    return n < 1e-6
 
 
# Calculates rotation matrix to euler angles
# The result is the same as MATLAB except the order
# of the euler angles ( x and z are swapped ).
def rotationMatrixToEulerAngles(R) :
 
    assert(isRotationMatrix(R))
     
    sy = math.sqrt(R[0,0] * R[0,0] +  R[1,0] * R[1,0])
     
    singular = sy < 1e-6
 
    if  not singular :
        x = math.atan2(R[2,1] , R[2,2])
        y = math.atan2(-R[2,0], sy)
        z = math.atan2(R[1,0], R[0,0])
    else :
        x = math.atan2(-R[1,2], R[1,1])
        y = math.atan2(-R[2,0], sy)
        z = 0
 
    return np.array([x, y, z])

def eulerAnglesToRotationMatrix(theta) :
     
    R_x = np.array([[1,         0,                  0                   ],
                    [0,         math.cos(theta[0]), -math.sin(theta[0]) ],
                    [0,         math.sin(theta[0]), math.cos(theta[0])  ]
                    ])
         
         
                     
    R_y = np.array([[math.cos(theta[1]),    0,      math.sin(theta[1])  ],
                    [0,                     1,      0                   ],
                    [-math.sin(theta[1]),   0,      math.cos(theta[1])  ]
                    ])
                 
    R_z = np.array([[math.cos(theta[2]),    -math.sin(theta[2]),    0],
                    [math.sin(theta[2]),    math.cos(theta[2]),     0],
                    [0,                     0,                      1]
                    ])
                     
                     
    R = np.dot(R_z, np.dot( R_y, R_x ))
 
    return R


class DataWriter:
    def __init__(self, cam_K, left_number, kp_model_vertices, save_video=False,
                savepath='examples/res/1.avi', fourcc=cv2.VideoWriter_fourcc(*'XVID'), fps=25, frameSize=(640,480),
                queueSize=1024):
        if save_video:
            # initialize the file video stream along with the boolean
            # used to indicate if the thread should be stopped or not
            self.stream = cv2.VideoWriter(savepath, fourcc, fps, frameSize)
            assert self.stream.isOpened(), 'Cannot open video for writing'
        self.save_video = save_video
        self.stopped = False
        self.final_result = []
        # initialize the queue used to store frames read from
        # the video file
        self.Q = Queue(maxsize=queueSize)
        if opt.save_img:
            if not os.path.exists(opt.outputpath + '/vis'):
                os.mkdir(opt.outputpath + '/vis')
        self.kp_3d = kp_model_vertices
        self.cam_K = cam_K
        self.left_number = left_number

    def start(self):
        # start a thread to read frames from the file video stream
        t = Thread(target=self.update, args=())
        t.daemon = True
        t.start()
        return self

    def update(self):
        # keep looping infinitely
        while True:
            # if the thread indicator variable is set, stop the
            # thread
            if self.stopped:
                if self.save_video:
                    self.stream.release()
                return
            # otherwise, ensure the queue is not empty
            if not self.Q.empty():
                (boxes, scores, hm_data, pt1, pt2, orig_img, im_name) = self.Q.get()
                orig_img = np.array(orig_img, dtype=np.uint8)
                if boxes is None:
                    if opt.save_img or opt.save_video or opt.vis:
                        img = orig_img
                        if opt.vis:
                            cv2.imshow("AlphaPose Demo", img)
                            cv2.waitKey(30)
                        if opt.save_img:
                            cv2.imwrite(os.path.join(opt.outputpath, 'vis', im_name), img)
                        if opt.save_video:
                            self.stream.write(img)
                else:
                    # location prediction (n, kp, 2) | score prediction (n, kp, 1)
                    
                    preds_hm, preds_img, preds_scores = getPrediction(
                        hm_data, pt1, pt2, opt.inputResH, opt.inputResW, opt.outputResH, opt.outputResW)

                    result = pose_nms(boxes, scores, preds_img, preds_scores)
                    result = {
                        'imgname': im_name,
                        'result': result
                    } # append imgname here.
                    # result here includes imgname, bbox, kps, kp_score, proposal_score
                    # Critical, run pnp algorithm here to get 6d pose.
                    # embed()
                    KP_REMAIN = self.left_number
                    if result['result']:
                        kp_score = np.array(result['result'][0]['kp_score'][:,0])
                        kp_2d = np.array(result['result'][0]['keypoints'])
                        kp_3d = np.array(self.kp_3d)
                        while(len(kp_2d)>KP_REMAIN):
                            delidx = np.argmin(kp_score, axis=0)
                            kp_score = np.delete(kp_score,delidx)
                            kp_2d = np.delete(kp_2d,delidx, axis=0)
                            kp_3d = np.delete(kp_3d,delidx, axis=0)
                        # embed()
                        
                        R, t = pnp(kp_3d, kp_2d, self.cam_K)
                        R    = R.T
                        R[1] = -R[1]
                        R = R.T 
                        result.update({'cam_R':-R, 'cam_t':-t/1000})
                    else:
                        result.update({'cam_R':[], 'cam_t':[]})
                    self.final_result.append(result)
                    # if opt.save_img or opt.save_video or opt.vis:
                    #     img = vis_frame(orig_img, result)
                    #     if opt.vis:
                    #         cv2.imshow("AlphaPose Demo", img)
                    #         cv2.waitKey(30)
                    #     if opt.save_img:
                    #         cv2.imwrite(os.path.join(opt.outputpath, 'vis', im_name), img)
                    #     if opt.save_video:
                    #         self.stream.write(img)
            else:
                time.sleep(0.1)

    def running(self):
        # indicate that the thread is still running
        time.sleep(0.2)
        return not self.Q.empty()

    def save(self, boxes, scores, hm_data, pt1, pt2, orig_img, im_name): # using update
        # save next frame in the queue
        self.Q.put((boxes, scores, hm_data, pt1, pt2, orig_img, im_name))

    def stop(self):
        # indicate that the thread should be stopped
        self.stopped = True
        time.sleep(0.2)

    def results(self):
        # return final result
        return self.final_result

    def len(self):
        # return queue len
        return self.Q.qsize()

class Mscoco(data.Dataset):
    def __init__(self, train=False, sigma=1,
                 scale_factor=(0.2, 0.3), rot_factor=40, label_type='Gaussian'):
        self.img_folder = './output01/eval'    # root image folders # used in training
        self.is_train = train           # training set or test set
        self.inputResH = opt.inputResH
        self.inputResW = opt.inputResW
        self.outputResH = opt.outputResH
        self.outputResW = opt.outputResW
        self.sigma = sigma
        self.scale_factor = scale_factor
        self.rot_factor = rot_factor
        self.label_type = label_type

        # Change number of keypoints here!
        self.nJoints_coco = 50
        self.nJoints_mpii = 50 #16
        self.nJoints = 50 #33

        self.accIdxs = tuple([i for i in range(1, 50 + 1)])
        self.flipRef = ()

    def __getitem__(self, index):
        pass

    def __len__(self):
        pass


def crop_from_dets(img, boxes, inps, pt1, pt2):
    '''
    Crop human from origin image according to Dectecion Results
    '''

    imght = img.size(1)
    imgwidth = img.size(2)
    tmp_img = img
    tmp_img[0].add_(-0.406)
    tmp_img[1].add_(-0.457)
    tmp_img[2].add_(-0.480)
    for i, box in enumerate(boxes):
        upLeft = torch.Tensor(
            (float(box[0]), float(box[1])))
        bottomRight = torch.Tensor(
            (float(box[2]), float(box[3])))

        ht = bottomRight[1] - upLeft[1]
        width = bottomRight[0] - upLeft[0]
        if width > 100:
            scaleRate = 0.2
        else:
            scaleRate = 0.3

        upLeft[0] = max(0, upLeft[0] - width * scaleRate / 2)
        upLeft[1] = max(0, upLeft[1] - ht * scaleRate / 2)
        bottomRight[0] = max(
            min(imgwidth - 1, bottomRight[0] + width * scaleRate / 2), upLeft[0] + 5)
        bottomRight[1] = max(
            min(imght - 1, bottomRight[1] + ht * scaleRate / 2), upLeft[1] + 5)

        try:
            inps[i] = cropBox(tmp_img, upLeft, bottomRight, opt.inputResH, opt.inputResW)
        except IndexError:
            print(tmp_img.shape)
            print(upLeft)
            print(bottomRight)
            print('===')
        pt1[i] = upLeft
        pt2[i] = bottomRight

    return inps, pt1, pt2
