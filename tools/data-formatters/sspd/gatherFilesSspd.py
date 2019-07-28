import glob, os, sys
import shutil
import json
import numpy as np
import random
import cv2
from distutils.dir_util import copy_tree
from PIL import Image
import operator

imageWidth = 640
imageHeight = 480

def extractRange(xArr):
	return np.max(xArr) - np.min(xArr)

def createJPEGImagesAndLabelsJSONFoldersAndContent(mask_fix):
	print('copying pics and labels')
	if not os.path.exists('../sspdFormat'):
		os.makedirs('../sspdFormat')
		os.makedirs('../sspdFormat/JPEGImages')
		os.makedirs('../sspdFormat/maskPolyColor')
		os.makedirs('../sspdFormat/labelsJSON')
		os.makedirs('../sspdFormat/labels')
		os.makedirs('../sspdFormat/mask')


	if (mask_fix):
		mask_folder = '../sspdFormat/maskPolyColor'
	else:
		mask_folder = '../sspdFormat/mask'

	allSubdirs = [x[0] for x in os.walk('./')]
	counter = 0
	counterJson = 0
	counterCs = 0
	for dir in allSubdirs:
		print(dir)
		for file in os.listdir(dir):
			if file.endswith(".json") and not file.endswith("settings.json"):
				shutil.copy(os.path.join(dir, file), os.path.join('../sspdFormat/labelsJSON', format(counterJson, '06') + '.json'))
				counterJson += 1
			if file.endswith(".png") and not file.endswith("cs.png") and not file.endswith("depth.png") and not file.endswith("is.png"):
				im = Image.open(os.path.join(dir, file))
				rgb_im = im.convert('RGB')
				rgb_im.save(os.path.join('../sspdFormat/JPEGImages', format(counter, '06') + '.jpg'))
				counter += 1
			if file.endswith("cs.png"):
				shutil.copy(os.path.join(dir, file), os.path.join(mask_folder, format(counter, '06') + '.cs.png'))
				counterCs += 1

def createLabelContent():
	print('creating labels and deleting pics where the obj is partly outside of frame')
	allSubdirs = [x[0] for x in os.walk('../sspdFormat/labelsJSON')]
	counter = 0
	createdCounter = 0
	for dir in allSubdirs:
		for file in os.listdir(dir):
			with open(os.path.join(dir, file)) as json_file:  
				data = json.load(json_file)
				created = False

				for obj in data['objects']:
					c_x = obj['projected_cuboid_centroid'][0] / imageWidth
					c_y = obj['projected_cuboid_centroid'][1] / imageHeight

					bb_x1 = int(obj['bounding_box']['top_left'][1])
					bb_y1 = int(obj['bounding_box']['top_left'][0])

					bb_x2 = int(obj['bounding_box']['bottom_right'][1])
					bb_y2 = int(obj['bounding_box']['bottom_right'][0])

					if (bb_x1 < 0 or bb_x1 > imageWidth or bb_x2 < 0 or bb_x2 > imageWidth or
						bb_y1 < 0 or bb_y1 > imageHeight or bb_y2 < 0 or bb_y2 > imageHeight):
						created = False
						break
					if (c_x <= 1 and c_x >= 0 and c_y <= 1 and c_y >= 0):
						bb_x1 = obj['projected_cuboid'][7][0] / imageWidth
						bb_y1 = obj['projected_cuboid'][7][1] / imageHeight

						bb_x2 = obj['projected_cuboid'][4][0] / imageWidth
						bb_y2 = obj['projected_cuboid'][4][1] / imageHeight

						bb_x3 = obj['projected_cuboid'][6][0] / imageWidth
						bb_y3 = obj['projected_cuboid'][6][1] / imageHeight

						bb_x4 = obj['projected_cuboid'][5][0] / imageWidth
						bb_y4 = obj['projected_cuboid'][5][1] / imageHeight







						bb_x5 = obj['projected_cuboid'][3][0] / imageWidth
						bb_y5 = obj['projected_cuboid'][3][1] / imageHeight

						bb_x6 = obj['projected_cuboid'][0][0] / imageWidth
						bb_y6 = obj['projected_cuboid'][0][1] / imageHeight

						bb_x7 = obj['projected_cuboid'][2][0] / imageWidth
						bb_y7 = obj['projected_cuboid'][2][1] / imageHeight

						bb_x8 = obj['projected_cuboid'][1][0] / imageWidth
						bb_y8 = obj['projected_cuboid'][1][1] / imageHeight




						

						range_x = extractRange(np.array([bb_x1,bb_x2,bb_x3,bb_x4,bb_x5,bb_x6,bb_x7,bb_x8]))
						range_y = extractRange(np.array([bb_y1,bb_y2,bb_y3,bb_y4,bb_y5,bb_y6,bb_y7,bb_y8]))

						bbox = obj['bounding_box']
						tl = bbox['top_left']
						br = bbox['bottom_right']

						y_range = float(br[0] - tl[0]/imageHeight)
						x_range = float(br[1] - tl[1]/imageWidth)

						f = open(os.path.join('../sspdFormat/labels',format(createdCounter, '06') + '.txt'), "w+")
						f.write("0 %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f" % (c_x, c_y, bb_x1, bb_y1, bb_x2, bb_y2, bb_x3, bb_y3, bb_x4, bb_y4, bb_x5, bb_y5, bb_x6, bb_y6, bb_x7, bb_y7, bb_x8, bb_y8, range_x, range_y))
						created = True
						createdCounter += 1
						f.close()
						break
				if not created:
					print('deleting ' +  format(counter, '06') + '.png')
					if (os.path.isfile('../sspdFormat/JPEGImages/' + format(counter, '06') + '.jpg')):
						os.remove('../sspdFormat/JPEGImages/' + format(counter, '06') + '.jpg')
					if (os.path.isfile('../sspdFormat/mask/' + format(counter, '06') + '.png')):
						os.remove('../sspdFormat/mask/' + format(counter, '06') + '.png')
				
				counter += 1

def renumberInFolder(folder):
	print('renumbering because of deleted files')
	allSubdirs = [x[0] for x in os.walk(folder)]
	counter = 0
	for dir in allSubdirs:
		for file in os.listdir(dir):
			end = file.split('.')[-1]
			os.rename(folder + file, folder + format(counter, '06') + '.' + end)
			counter+=1

def createBinaryMask():
	print('creating binary mask')
	allSubdirs = [x[0] for x in os.walk('../sspdFormat/labelsJSON')]
	counter = 0
	for dir in allSubdirs:
		for file in os.listdir(dir):
			if os.path.isfile("../sspdFormat/mask/" + format(counter, '06') + ".png"):
				counter += 1
				continue
			with open(os.path.join(dir, file)) as json_file:  
				data = json.load(json_file)
				created = False

				for obj in data['objects']:
					c_x = int(obj['projected_cuboid_centroid'][0])
					c_y = int(obj['projected_cuboid_centroid'][1])
					

					if (c_x <= imageWidth and c_x >= 0 and c_y <= imageHeight and c_y >= 0):
						bb_x1 = int(obj['bounding_box']['top_left'][0])
						bb_y1 = int(obj['bounding_box']['top_left'][1])

						bb_x2 = int(obj['bounding_box']['bottom_right'][0])
						bb_y2 = int(obj['bounding_box']['bottom_right'][1])

						img = cv2.imread("../sspdFormat/maskPolyColor/" + format(counter, '06') + ".cs.png")
						if (c_y == imageHeight):
							c_y -= 1
						if (c_x == imageWidth):
							c_x -= 1
						pspColor = np.array(img[c_y, c_x])

						# Everything outside of the bb is black
						img[0:bb_x1,0:imageWidth] = (0,0,0)
						img[bb_x2:imageHeight,0:imageWidth] = (0,0,0)
						img[0:imageHeight,0:bb_y1] = (0,0,0)
						img[0:imageHeight,bb_y2:imageWidth] = (0,0,0)

						color_dict = {}
						img_copy = np.zeros((imageHeight,imageWidth,3), np.uint8)

						if (bb_x1 > imageHeight or bb_x2 > imageHeight 
							or bb_y2 > imageWidth or bb_y2 > imageWidth
							or bb_x1 < 0 or bb_x2 < 0 or bb_y1 < 0 or bb_y2 < 0):
							cv2.imwrite("../sspdFormat/mask/" + format(counter, '06') + ".png", img_copy)
							created = True
							break

						for i in range(bb_x1, bb_x2):
							for j in range(bb_y1, bb_y2):
								if (i < imageHeight and i >= 0 and j < imageWidth and j >= 0):
									img_copy[i, j] = img[i, j]


						for i in range(bb_x1, bb_x2):
							for j in range(bb_y1, bb_y2):
								if (i < imageHeight and i >= 0 and j < imageWidth and j >= 0):
									color = np.array2string(img[i, j], separator=',')
									if color in color_dict:
										color_dict[color] += 1
									else:
										color_dict[color] = 1

						sorted_c_d = sorted(color_dict.items(), key=operator.itemgetter(1), reverse=True)

						# Precision color the psp white and everything else in the bb black
						for k in range(len(sorted_c_d)):
							color = np.fromstring(sorted_c_d[k][0][1:-1], dtype=int, sep=',')
							print(color)
							for i in range(bb_x1, bb_x2):
								for j in range(bb_y1, bb_y2):
									if (i < imageHeight and i >= 0 and j < imageWidth and j >= 0):
										if np.any(img[i, j] == color):
											img_copy[i, j] = (255,255,255)
										else:
											img_copy[i, j] = (0,0,0)
							corners = 0
							# Check if one of the corners is of the object. If so the segmentation is wrong
							if (np.any(img_copy[bb_x1, bb_y1] == (255,255,255))):
								corners+=1
							if (np.any(img_copy[bb_x1, bb_y2-1] == (255,255,255))):
								corners+=1
							if (np.any(img_copy[bb_x2-1, bb_y1] == (255,255,255))):
								corners+=1
							if (np.any(img_copy[bb_x2-1, bb_y2-1] == (255,255,255))):
								corners+=1

							if (corners == 0):
								#cv2.imshow('title',img)
								cv2.imwrite("../sspdFormat/mask/" + format(counter, '06') + ".png", img_copy)
								created = True
								break
						break
				if (not created):
					img = np.zeros((imageHeight,imageWidth,3), np.uint8)
					cv2.imwrite("../sspdFormat/mask/" + format(counter, '06') + ".png", img)
				counter += 1

	

def createTestAndTrainFiles(counter, objectless_count):
	print('creating test and train files')
	test_size = int(counter * 0.3)
	test = random.sample(range(counter), test_size)

	f_test = open(os.path.join('../sspdFormat', 'test.txt'), "w+")
	f_train = open(os.path.join('../sspdFormat', 'train.txt'), "w+")
	f_train_range = open(os.path.join('../sspdFormat', 'training_range.txt'), "w+")

	obj_img_count = counter - objectless_count
	for i in range(counter):
		img_type = ".jpg"
		if (i in test):
			f_test.write('sspdFormat/JPEGImages/' + format(i, '06') + img_type + " \n")
		else:
			f_train.write('sspdFormat/JPEGImages/' + format(i, '06') + img_type + " \n")
			f_train_range.write(str(i) + " \n")
	
	f_test.close()
	f_train.close()
	f_train_range.close()


def calc_pts_diameter(pts):
	diameter = -1
	for pt_id in range(pts.shape[0]):
		pt_dup = np.tile(np.array([pts[pt_id, :]]), [pts.shape[0] - pt_id, 1])
		pts_diff = pt_dup - pts[pt_id:, :]
		max_dist = math.sqrt((pts_diff * pts_diff).sum(axis=1).max())
		if max_dist > diameter:
			diameter = max_dist
	return diameter

def copyObjectLessImgsAndCreateEmptyLabels(counter):

	counterLabels = counter
	counterMasks = counter

	# Copy the images that contain no objects of interest in them (negative examples)
	allSubdirs = [x[0] for x in os.walk('../objectlessImages')]
	print('Copying objectless images')
	for dir in allSubdirs:
		for file in os.listdir(dir):
			end = file.split('.')[-1]
			shutil.copy(os.path.join(dir, file), os.path.join('../sspdFormat/JPEGImages', format(counter, '06') + '.' + end))
			counter += 1


	img = np.zeros((imageHeight,imageWidth,3), np.uint8)
	print('Creating black masks')
	for dir in allSubdirs:
		for file in os.listdir(dir):
			cv2.imwrite("../sspdFormat/mask/" + format(counterMasks, '06') + ".png", img)
			counterMasks += 1

	# Generate empty labels files for them
	print('Generating empty label files')
	for dir in allSubdirs:
		print(dir)
		for file in os.listdir(dir):
			f = open(os.path.join('../sspdFormat/labels',format(counterLabels, '06') + '.txt'), "w+")
			f.write("")
			counterLabels += 1
			f.close()
	

def changeLabels():
	for file in glob.glob("../betaposeFormat/labels/*.txt"):
	    f = open(file, "r")
	    line = f.read()
	    lineVals = line.split()
	    newLine = lineVals[0] + ' ' + lineVals[1] + ' ' + lineVals[2] + ' ' + lineVals[19] + ' ' + lineVals[20]
	    with open('../betaposeFormat/labelsConverted/' + os.path.basename(f.name), 'w') as file:
	        file.write(newLine)

def cleanUselessFoldersSSPD():
	shutil.rmtree('../sspdFormat/maskPolyColor/')
	shutil.rmtree('../sspdFormat/labelsJSON/')








def reformatForSSPD(mask_fix):
	createJPEGImagesAndLabelsJSONFoldersAndContent(mask_fix)
	if (mask_fix):
		createBinaryMask()
	createLabelContent()
	renumberInFolder('../sspdFormat/mask/')
	renumberInFolder('../sspdFormat/JPEGImages/')
	copyObjectLessImgsAndCreateEmptyLabels(len(os.listdir('../sspdFormat/labels')))
	createTestAndTrainFiles(len(os.listdir('../sspdFormat/labels')), len(os.listdir('../objectlessImages')))
	cleanUselessFoldersSSPD()

if __name__ == "__main__":
    # Training settings
    # example: python bbCalcForLabels.py guitar 1499 gibson10x.ply
    with_binary_fix = True
    if (len(sys.argv) > 1):
        with_binary_fix   = False
        print('with max fix')
    else:
        print('without max fix')

    reformatForSSPD(with_binary_fix)
