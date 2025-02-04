import os, sys, math, time, json, psutil
from PIL import Image, ImageChops, ImageStat
import multiprocessing as mp
from functools import partial
from shutil import get_terminal_size as tsize
import traceback



ext = ".png"
outext = ".jpg"



def test(paths):
	newImg = Image.open(paths[0], mode='r').convert("RGB")
	oldImg = Image.open(paths[1], mode='r').convert("RGB")
	treshold = .03 * newImg.size[0]**2
	# jpeg artifacts always average out perfectly over 8x8 sections, we take advantage of that and scale down by 8 so we can compare compressed images with uncompressed images.
	size = (newImg.size[0] / 8, newImg.size[0] / 8)
	newImg.thumbnail(size, Image.BILINEAR)
	oldImg.thumbnail(size, Image.BILINEAR)
	diff = ImageChops.difference(newImg, oldImg)
	return sum(ImageStat.Stat(diff).sum2) > treshold


def compare(path, basePath, new, progressQueue):
	testResult = False
	try:
		testResult = test((os.path.join(basePath, new, *path[1:]), os.path.join(basePath, *path).replace(ext, outext)))
	except:
		print("\r")
		traceback.print_exc()
		print("\n")
		raise
	finally:
		progressQueue.put(True, True)
	return (testResult, path[1:])

def compare_renderbox(renderbox, basePath, new):
	newPath = os.path.join(basePath, new, renderbox[0]) + ext
	testResult = False
	try:
		testResult = test((newPath, os.path.join(basePath, renderbox[1], renderbox[0]) + outext))
	except:
		print("\r")
		raise
	return (testResult, newPath, renderbox[1], renderbox[2])


def neighbourScan(coord, keepList, cropList):
		"""
		x+ = UP, y+ = RIGHT
		corners:
		2   1
		X
		4   3
		"""
		surfaceName, daytime, z = coord[:3]
		x, y = int(coord[3]), int(os.path.splitext(coord[4])[0])
		return (((surfaceName, daytime, z, str(x+1), str(y+1) + ext) in keepList and cropList.get((surfaceName, daytime, z, x+1, y+1), 0) & 0b1000) \
			or ((surfaceName, daytime, z, str(x+1), str(y-1) + ext) in keepList and cropList.get((surfaceName, daytime, z, x+1, y-1), 0) & 0b0100) \
			or ((surfaceName, daytime, z, str(x-1), str(y+1) + ext) in keepList and cropList.get((surfaceName, daytime, z, x-1, y+1), 0) & 0b0010) \
			or ((surfaceName, daytime, z, str(x-1), str(y-1) + ext) in keepList and cropList.get((surfaceName, daytime, z, x-1, y-1), 0) & 0b0001) \
			or ((surfaceName, daytime, z, str(x+1), str(y  ) + ext) in keepList and cropList.get((surfaceName, daytime, z, x+1, y  ), 0) & 0b1100) \
			or ((surfaceName, daytime, z, str(x-1), str(y  ) + ext) in keepList and cropList.get((surfaceName, daytime, z, x-1, y  ), 0) & 0b0011) \
			or ((surfaceName, daytime, z, str(x  ), str(y+1) + ext) in keepList and cropList.get((surfaceName, daytime, z, x  , y+1), 0) & 0b1010) \
			or ((surfaceName, daytime, z, str(x  ), str(y-1) + ext) in keepList and cropList.get((surfaceName, daytime, z, x  , y-1), 0) & 0b0101), coord)







def base64Char(i):
	assert(i >= 0 and i < 64) # Did you change image size? it could make this overflow
	if i == 63:
		return "/"
	elif i == 62:
		return "+"
	elif i > 51:
		return chr(i - 4)
	elif i > 25:
		return chr(i + 71)
	return chr(i + 65)
def getBase64(number, isNight): #coordinate to 18 bit value (3 char base64)
	number = int(number) + (2**16 if isNight else (2**17 + 2**16)) # IMAGES CURRENTLY CONTAIN 16 TILES. IF IMAGE SIZE CHANGES THIS WONT WORK ANYMORE. (It will for a long time until it wont)
	return base64Char(number % 64) + base64Char(int(number / 64) % 64) + base64Char(int(number / 64 / 64))









def ref(*args, **kwargs):

	psutil.Process(os.getpid()).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)


	toppath = os.path.join((args[4] if len(args) > 4 else "../../script-output/FactorioMaps"), args[0])
	datapath = os.path.join(toppath, "mapInfo.json")
	maxthreads = int(kwargs["refthreads" if kwargs["refthreads"] else"maxthreads"])



	pool = mp.Pool(processes=maxthreads)

	with open(datapath, "r") as f:
		data = json.load(f)
	if os.path.isfile(datapath[:-5] + ".out.json"):
		with open(datapath[:-5] + ".out.json", "r") as f:
			outdata = json.load(f)
	else:
		outdata = {}


	if len(args) > 1:
		for i, mapObj in enumerate(data["maps"]):
			if mapObj["path"] == args[1]:
				new = i
				break
	else:
		new = len(data["maps"]) - 1



	changed = False
	if "maps" not in outdata:
		outdata["maps"] = {}
	if str(new) not in outdata["maps"]:
		outdata["maps"][str(new)] = { "surfaces": {} }


	newMap = data["maps"][new]
	allImageIndex = {}
	allDayImages = {}

	for daytime in ("day", "night"):
		newComparedSurfaces = []
		compareList = []
		keepList = []
		firstRemoveList = []
		cropList = {}
		didAnything = False
		if len(args) <= 3 or daytime == args[3]:
			for surfaceName, surface in newMap["surfaces"].items():
				if (len(args) <= 2 or surfaceName == args[2]) and daytime in surface and str(surface[daytime]) and (len(args) <= 3 or daytime == args[3]):
					didAnything = True
					z = surface["zoom"]["max"]


					dayImages = []

					newComparedSurfaces.append((surfaceName, daytime))
					
					oldMapsList = []
					for old in range(new):
						if surfaceName in data["maps"][old]["surfaces"]:
							oldMapsList.append(old)


					def readCropList(path, combinePrevious):
						with open(path, "r") as f:
							version = 2 if f.readline().rstrip('\n') == "v2" else 1
							for line in f:
								if version == 1:
									split = line.rstrip("\n").split(" ", 5)
									key = (surfaceName, daytime, str(z), int(split[0]), int(os.path.splitext(split[1])[0]))
									value = split[4]
								else:
									split = line.rstrip("\n").split(" ", 5)
									pathSplit = split[5].split("/", 2)
									if pathSplit[0] != str(z):
										continue
									key = (surfaceName, daytime, str(z), int(pathSplit[1]), int(os.path.splitext(pathSplit[2])[0]))
									value = split[2]
								
								cropList[key] = int(value, 16) | cropList.get(key, 0) if combinePrevious else int(value, 16)

					for old in oldMapsList:
						readCropList(os.path.join(toppath, "Images", data["maps"][old]["path"], surfaceName, daytime, "crop.txt"), False)
								
					readCropList(os.path.join(toppath, "Images", newMap["path"], surfaceName, daytime, "crop.txt"), True)



					oldImages = {}
					for old in oldMapsList:
						if surfaceName in data["maps"][old]["surfaces"] and daytime in surface and z == surface["zoom"]["max"]:
							if surfaceName not in allImageIndex:
								allImageIndex[surfaceName] = {}
							path = os.path.join(toppath, "Images", data["maps"][old]["path"], surfaceName, daytime, str(z))
							for x in os.listdir(path):
								for y in os.listdir(os.path.join(path, x)):
									oldImages[(x, y.replace(ext, outext))] = data["maps"][old]["path"]

					if daytime != "day":
						if not os.path.isfile(os.path.join(toppath, "Images", newMap["path"], surfaceName, "day", "ref.txt")):
							print("WARNING: cannot find day surface to copy non-day surface from. running ref.py on night surfaces is not very accurate.")
						else:
							if kwargs["verbose"]: print("found day surface, reuse results from ref.py from there")
							
							with open(os.path.join(toppath, "Images", newMap["path"], surfaceName, "day", "ref.txt"), "r") as f:
								for line in f:
									dayImages.append(tuple(line.rstrip("\n").split(" ", 2)))
									

						allDayImages[surfaceName] = dayImages
					

					path = os.path.join(toppath, "Images", newMap["path"], surfaceName, daytime, str(z))
					for x in os.listdir(path):
						for y in os.listdir(os.path.join(path, x)):
							if (x, os.path.splitext(y)[0]) in dayImages or (x, y.replace(ext, outext)) not in oldImages:
								keepList.append((surfaceName, daytime, str(z), x, y))
							elif (x, y.replace(ext, outext)) in oldImages:
								compareList.append((oldImages[(x, y.replace(ext, outext))], surfaceName, daytime, str(z), x, y))

			   


		if not didAnything:
			continue


	

		if kwargs["verbose"]: print("found %s new images" % len(keepList))
		if len(compareList) > 0:
			if kwargs["verbose"]: print("comparing %s existing images" % len(compareList))
			m = mp.Manager()
			progressQueue = m.Queue()
			#compare(compareList[0], treshold=treshold, basePath=os.path.join(toppath, "Images"), new=str(newMap["path"]), progressQueue=progressQueue)
			workers = pool.map_async(partial(compare, basePath=os.path.join(toppath, "Images"), new=str(newMap["path"]), progressQueue=progressQueue), compareList, 128)
			doneSize = 0
			print("ref  {:5.1f}% [{}]".format(0, " " * (tsize()[0]-15)), end="")
			for i in range(len(compareList)):
				progressQueue.get(True)
				doneSize += 1
				progress = float(doneSize) / len(compareList)
				tsiz = tsize()[0]-15
				print("\rref  {:5.1f}% [{}{}]".format(round(progress * 100, 1), "=" * int(progress * tsiz), " " * (tsiz - int(progress * tsiz))), end="")
			workers.wait()
			resultList = workers.get()

			newList = [x[1] for x in [x for x in resultList if x[0]]]
			firstRemoveList += [x[1] for x in [x for x in resultList if not x[0]]]
			if kwargs["verbose"]: print("found %s changed in %s images" % (len(newList), len(compareList)))
			keepList += newList
			print("\rref  {:5.1f}% [{}]".format(100, "=" * (tsize()[0]-15)))
		

		if kwargs["verbose"]: print("scanning %s chunks for neighbour cropping" % len(firstRemoveList))
		resultList = pool.map(partial(neighbourScan, keepList=keepList, cropList=cropList), firstRemoveList, 64)
		neighbourList = [x[1] for x in [x for x in resultList if x[0]]]
		removeList = [x[1] for x in [x for x in resultList if not x[0]]]
		if kwargs["verbose"]: print("keeping %s neighbouring images" % len(neighbourList))


		if kwargs["verbose"]: print("deleting %s, keeping %s of %s existing images" % (len(removeList), len(keepList) + len(neighbourList), len(keepList) + len(neighbourList) + len(removeList)))


		if kwargs["verbose"]: print("removing identical images")
		for x in removeList:
			os.remove(os.path.join(toppath, "Images", newMap["path"], *x))


		if kwargs["verbose"]: print("creating render index")
		for surfaceName, daytime in newComparedSurfaces:
			z = surface["zoom"]["max"]
			with open(os.path.join(toppath, "Images", newMap["path"], surfaceName, daytime, "ref.txt"), "w") as f:
				for aList in (keepList, neighbourList):
					for coord in aList:
						if coord[0] == surfaceName and coord[1] == daytime and coord[2] == str(z):
							f.write("%s %s\n" % (coord[3], os.path.splitext(coord[4])[0]))




		if kwargs["verbose"]: print("creating client index")
		for aList in (keepList, neighbourList):
			for coord in aList:
				x = int(coord[3])
				y = int(os.path.splitext(coord[4])[0])
				if coord[0] not in allImageIndex:
					allImageIndex[coord[0]] = {}
				if coord[1] not in allImageIndex[coord[0]]:
					allImageIndex[coord[0]][coord[1]] = {}
				if y not in allImageIndex[coord[0]][coord[1]]:
					allImageIndex[coord[0]][coord[1]][y] = [x]
				elif x not in allImageIndex[coord[0]][coord[1]][y]:
					allImageIndex[coord[0]][coord[1]][y].append(x)


					
					



		if kwargs["verbose"]: print("comparing renderboxes")
		if "renderboxesCompared" not in outdata["maps"][str(new)]:
			changed = True
			outdata["maps"][str(new)]["renderboxesCompared"] = True

			compareList = {}
			totalCount = 0
			for surfaceName, surface in newMap["surfaces"].items():
				linksByPath = {}
				for linkIndex, link in enumerate(surface["links"]):

					if surfaceName not in outdata["maps"][str(new)]["surfaces"]:
						outdata["maps"][str(new)]["surfaces"][surfaceName] = { "links": [] }
					outdata["maps"][str(new)]["surfaces"][surfaceName]["links"].append({ "path": newMap["path"] })

					for daytime in ("day", "night"):
						if link["type"] == "link_renderbox_area" and (link["daynight"] or daytime == "day"):
							path = os.path.join(link["toSurface"], daytime if link["daynight"] else "day", "renderboxes", str(surface["zoom"]["max"]), link["filename"])

							if path not in linksByPath:
								linksByPath[path] = [ (surfaceName, linkIndex) ]
							else:
								linksByPath[path].append((surfaceName, linkIndex))

							totalCount += 1

				for old in range(new-1, -1, -1):
					if surfaceName in data["maps"][old]["surfaces"]:
						for linkIndex, link in enumerate(data["maps"][old]["surfaces"][surfaceName]["links"]):
							for daytime in ("day", "night"):
								if link["type"] == "link_renderbox_area" and (link["daynight"] or daytime == "day"):
									path = os.path.join(link["toSurface"], daytime if link["daynight"] else "day", "renderboxes", str(surface["zoom"]["max"]), link["filename"])
									if path in linksByPath and path not in compareList:
										oldPath = link["path"] if "path" in link else outdata["maps"][str(old)]["surfaces"][surfaceName]["links"][linkIndex]["path"]
										compareList[path] = (path, oldPath, linksByPath[path])


			compareList = compareList.values()
			resultList = pool.map(partial(compare_renderbox, basePath=os.path.join(toppath, "Images"), new=str(newMap["path"])), compareList, 16)

			count = 0
			for (isDifferent, path, oldPath, links) in resultList:
				if not isDifferent:
					os.remove(path)

					for (surfaceName, linkIndex) in links:
						outdata["maps"][str(new)]["surfaces"][surfaceName]["links"][linkIndex] = { "path": oldPath }
						
				else:
					count += 1

			if kwargs["verbose"]: print("removed %s of %s compared renderboxes, found %s new" % (count, len(compareList), totalCount))
					









	# compress and build string
	for surfaceName, daytimeImageIndex in allImageIndex.items():
		indexList = []
		daytime = "night" if "night" in daytimeImageIndex and data["maps"][new]["surfaces"][surfaceName] and str(data["maps"][new]["surfaces"][surfaceName]["night"]) else "day"
		surfaceImageIndex = daytimeImageIndex[daytime]
		for y, xList in surfaceImageIndex.items():
			string = getBase64(y, False)
			isLastChangedImage = False
			isLastNightImage = False
			
			for x in range(min(xList), max(xList) + 2):
				isChangedImage = x in xList                                                             #does the image exist at all? 
				isNightImage = daytime == "night" and (str(x), str(y)) not in allDayImages[surfaceName] #is this image only in night?
				if isLastChangedImage != isChangedImage or (isChangedImage and isLastNightImage != isNightImage): #differential encoding
					string += getBase64(x, isNightImage if isChangedImage else isLastNightImage)
					isLastChangedImage = isChangedImage
					isLastNightImage = isNightImage
			indexList.append(string)
			
			
		if surfaceName not in outdata["maps"][str(new)]["surfaces"]:
			outdata["maps"][str(new)]["surfaces"][surfaceName] = {}
		outdata["maps"][str(new)]["surfaces"][surfaceName]["chunks"] = '='.join(indexList)
		if len(indexList) > 0:
			changed = True
			



	if changed:
		if kwargs["verbose"]: print("writing mapInfo.out.json")
		with open(datapath[:-5] + ".out.json", "w+") as f:
			json.dump(outdata, f)

		if kwargs["verbose"]: print("deleting empty folders")
		for curdir, subdirs, files in os.walk(toppath, *args[1:4]):
			if len(subdirs) == 0 and len(files) == 0:
				os.rmdir(curdir)


		










if __name__ == '__main__':
	ref(*sys.argv[1:])