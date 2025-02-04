
import sys

if sys.maxsize <= 2**32:
	raise Exception("64 bit Python is required.")

if sys.hexversion < 0x3060000:
	raise Exception("Python 3.6 or higher is required for this script.")

import traceback, os, pkg_resources
from pkg_resources import DistributionNotFound, VersionConflict

try:
	with open('packages.txt') as f:
		pkg_resources.require(f.read().splitlines())
except (DistributionNotFound, VersionConflict) as ex:
	traceback.print_exc()
	print("\nDependencies not met. Run `pip install -r packages.txt` to install missing dependencies.")
	sys.exit(1)
	



import subprocess, signal
import json
import threading, psutil
import time
import re
import random
import math
import configparser
from subprocess import call
import datetime
import urllib.request, urllib.error, urllib.parse
from socket import timeout
from shutil import copy, copytree, rmtree, get_terminal_size as tsize
from zipfile import ZipFile
import tempfile
from PIL import Image, ImageChops
import multiprocessing as mp

from crop import crop
from ref import ref
from zoom import zoom, zoomRenderboxes
from updateLib import update as updateLib



kwargs = {
	'dayonly': False,
	'nightonly': False,
	'hd': False,
	'no-altmode': False,
	'no-tags': False,
	'tag-range': 5.2,
	'build-range': 5.2,
	'connect-range': 1.2,
	'factorio': None,
	'modpath': "../../mods",
	'basepath': "FactorioMaps",
	'date': datetime.date.today().strftime("%d/%m/%y"),
	'verbosegame': False,
	'verbose': False,
	'noupdate': False,
	'reverseupdatetest': False,
	'maxthreads': mp.cpu_count(),	
	'cropthreads': None,
	'refthreads': None,
	'zoomthreads': None,
	'screenshotthreads': None,
	'delete': False,
	'dry': False,
	'surface': []
}
changedKwargs = []





def printErase(arg):
	try:
		tsiz = tsize()[0]
		print("\r{}{}\n".format(arg, " " * (tsiz*math.ceil(len(arg)/tsiz)-len(arg) - 1)), end="", flush=True)
	except:
		#raise
		pass


def startGameAndReadGameLogs(results, condition, popenArgs, tmpDir, pidBlacklist, rawTags, **kwargs):

	pipeOut, pipeIn = os.pipe()
	p = subprocess.Popen(popenArgs, stdout=pipeIn)

	printingStackTraceback = False
	# TODO: keep printing multiline stuff until new print detected
	prevPrinted = False
	def handleGameLine(line):
		nonlocal prevPrinted
		line = line.rstrip('\n')
		if re.match(r'^\ *\d+(?:\.\d+)? *[^\n]*$', line) is None:
			if prevPrinted:
				printErase(line)
			return
		
		prevPrinted = False
		
		m = re.match(r'^\ *\d+(?:\.\d+)? *Script *@__L0laapk3_FactorioMaps__\/data-final-fixes\.lua:\d+: FactorioMaps_Output_RawTagPaths:([^:]+):(.*)$', line, re.IGNORECASE)
		if m is not None:
			rawTags[m.group(1)] = m.group(2)
			if rawTags["__used"]:
				raise Exception("Tags added after they were used.")
		else:
			if printingStackTraceback or line == "stack traceback:":
				printErase("[GAME] %s" % line)
				prevPrinted = True
				return True
			m = re.match(r'^\ *\d+(?:\.\d+)? *Script *@__L0laapk3_FactorioMaps__\/(.*?)(?:(\[info\]) ?(.*))?$', line, re.IGNORECASE)
			if m is not None and m.group(2) is not None:
				printErase(m.group(3))
				prevPrinted = True
			elif m is not None and kwargs["verbose"]:
				printErase(m.group(1))
				prevPrinted = True
			elif line.lower() in ("error", "warn", "exception", "fail", "invalid") or (kwargs["verbosegame"] and len(line) > 0):
				printErase("[GAME] %s" % line)
				prevPrinted = True
		return False


	with os.fdopen(pipeOut, 'r') as pipef:
		
		line = pipef.readline().rstrip("\n")
		printingStackTraceback = handleGameLine(line)
		isSteam = False
		if line.endswith("Initializing Steam API."):
			isSteam = True
		elif not re.match(r'^ *\d+\.\d{3} \d{4}-\d\d-\d\d \d\d:\d\d:\d\d; Factorio (\d+\.\d+\.\d+) \(build (\d+), [^)]+\)$', line):
			raise Exception("Unrecognised output from factorio (maybe your version is outdated?)\n\nOutput from factorio:\n" + line)

		if isSteam:
			print("WARNING: Running in limited support mode trough steam. Consider using standalone factorio instead.\n\t If you have any default arguments set in steam for factorio, delete them and restart the script.\n\t Please alt tab to steam and confirm the steam 'start game with arguments' popup.\n\t (Yes, you'll have to click this every time the game starts for the steam version)")
			attrs = ('pid', 'name', 'create_time')

			# on some devices, the previous check wasn't enough apparently, so explicitely wait until the log file is created.
			while not os.path.exists(os.path.join(tmpDir, "factorio-current.log")):
				time.sleep(0.4)

			oldest = None
			pid = None
			while pid is None:
				for proc in psutil.process_iter(attrs=attrs):
					pinfo = proc.as_dict(attrs=attrs)
					if pinfo["name"] == "factorio.exe" and pinfo["pid"] not in pidBlacklist and (pid is None or pinfo["create_time"] < oldest):
						oldest = pinfo["create_time"]
						pid = pinfo["pid"]
				if pid is None:
					time.sleep(1)
			# print(f"PID: {pid}")
		else:
			pid = p.pid

		results.extend((isSteam, pid))
		with condition:
			condition.notify()

		if isSteam:
			pipef.close()
			with open(os.path.join(tmpDir, "factorio-current.log"), "r") as f:
				while psutil.pid_exists(pid):
					where = f.tell()
					line = f.readline()
					if not line:
						time.sleep(0.4)
						f.seek(where)
					else:
						printingStackTraceback = handleGameLine(line)

		else:
			while True:
				line = pipef.readline()
				printingStackTraceback = handleGameLine(line)

				
		psutil.Process(pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)




def auto(*args):

	lock = threading.Lock()
	def kill(pid, onlyStall=False):
		if pid:
			with lock:
				if not onlyStall and psutil.pid_exists(pid):

					if os.name == 'nt':
						subprocess.check_call(("taskkill", "/pid", str(pid)), stdout=subprocess.DEVNULL, shell=True)
					else:
						subprocess.check_call(("killall", "factorio"), stdout=subprocess.DEVNULL)	# TODO: kill correct process instead of just killing all

					while psutil.pid_exists(pid):
						time.sleep(0.1)

					printErase("killed factorio")

		#time.sleep(0.1)
		



	
	def parseArg(arg):
		if arg[0:2] != "--":
			return True
		key = arg[2:].split("=",2)[0].lower()
		if key in kwargs:
			changedKwargs.append(key)
			if isinstance(kwargs[key], list):
				kwargs[key].append(arg[2:].split("=",2)[1])
			else:
				kwargs[key] = arg[2:].split("=",2)[1].lower() if len(arg[2:].split("=",2)) > 1 else True
				if kwargs[key] == "true":
					kwargs[key] = True
				if kwargs[key] == "false":
					kwargs[key] = False
		else:
			print(f'Bad flag: "{key}"')
			raise ValueError(f'Bad flag: "{key}"')
		return False



	newArgs = list(filter(parseArg, args))
	if kwargs["verbose"]:
		print(args)
	if len(newArgs) > 0:
		foldername = newArgs[0]
	else:
		foldername = os.path.splitext(os.path.basename(max([os.path.join("../../saves", basename) for basename in os.listdir("../../saves") if basename not in { "_autosave1.zip", "_autosave2.zip", "_autosave3.zip" }], key=os.path.getmtime)))[0]
		print("No save name passed. Using most recent save: %s" % foldername)
	savenames = newArgs[1:] or [ foldername ]

	for saveName in savenames:
		savePath = os.path.join("../../saves", saveName)
		if not (os.path.isdir(savePath) or os.path.isfile(savePath) or os.path.isfile(savePath + ".zip")):
			print(f'Cannot find savefile: "{saveName}"')
			raise ValueError(f'Cannot find savefile: "{saveName}"')

	windowsPaths = [
		"Program Files/Factorio/bin/x64/factorio.exe",
		"Games/Factorio/bin/x64/factorio.exe",
		"Program Files (x86)/Steam/steamapps/common/Factorio/bin/x64/factorio.exe",
		"Steam/steamapps/common/Factorio/bin/x64/factorio.exe",
	]
	possiblePaths = [driveletter + ":/" + path for driveletter in 'CDEFGHIJKL' for path in windowsPaths] + [
		"../../bin/x64/factorio.exe",
		"../../bin/x64/factorio",
	]
	try:
		factorioPath = next(x for x in map(os.path.abspath, [kwargs["factorio"]] if kwargs["factorio"] else possiblePaths) if os.path.isfile(x))
	except StopIteration:
		raise Exception("Can't find factorio.exe. Please pass --factorio=PATH as an argument.")

	print("factorio path: {}".format(factorioPath))

	psutil.Process(os.getpid()).nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 5)

	basepath = os.path.join("../../script-output", kwargs["basepath"])
	workthread = None

	workfolder = os.path.join(basepath, foldername)
	print("output folder: {}".format(os.path.relpath(workfolder, "../..")))

 
	try:
		os.makedirs(workfolder)
	except FileExistsError:
		pass


	if not kwargs["noupdate"]:
		try:
			print("checking for updates")
			latestUpdates = json.loads(urllib.request.urlopen('https://cdn.jsdelivr.net/gh/L0laapk3/FactorioMaps@latest/updates.json', timeout=30).read())
			with open("updates.json", "r") as f:
				currentUpdates = json.load(f)
			if kwargs["reverseupdatetest"]:
				latestUpdates, currentUpdates = currentUpdates, latestUpdates

			updates = []
			majorUpdate = False
			currentVersion = (0, 0, 0)
			for verStr, changes in currentUpdates.items():
				ver = tuple(map(int, verStr.split(".")))
				if currentVersion[0] < ver[0] or (currentVersion[0] == ver[0] and currentVersion[1] < ver[1]):
					currentVersion = ver
			for verStr, changes in latestUpdates.items():
				if verStr not in currentUpdates:
					ver = tuple(map(int, verStr.split(".")))
					updates.append((verStr, changes))
			updates.sort(key = lambda u: u[0])
			if len(updates) > 0:

				padding = max(map(lambda u: len(u[0]), updates))
				changelogLines = []
				for update in updates:
					if isinstance(update[1], str):
						updateText = update[1]
					else: 
						updateText = str(("\r\n      " + " "*padding).join(update[1]))
					if updateText[0] == "!":
						majorUpdate = True
						updateText = updateText[1:]
					changelogLines.append("    %s: %s" % (update[0].rjust(padding), updateText))
				print("")
				print("")
				print("================================================================================")
				print("")
				print(("  an " + ("important" if majorUpdate else "incremental") + " update has been found!"))
				print("")
				print("  heres what changed:")
				for line in changelogLines:
					print(line)
				print("")
				print("")
				print("  Download: https://git.io/factoriomaps")
				if majorUpdate:
					print("")
					print("You can dismiss this by using --noupdate (not recommended)")
				print("")
				print("================================================================================")
				print("")
				print("")
				if majorUpdate or kwargs["reverseupdatetest"]:
					sys.exit(1)(1)


		except (urllib.error.URLError, timeout) as e:
			print("Failed to check for updates. %s: %s" % (type(e).__name__, e))




	updateLib(False)



	#TODO: integrity check, if done files arent there or there are any bmp's left, complain.


	def linkDir(src, dest):
		if os.name == 'nt':
			subprocess.check_call(("MKLINK", "/J", os.path.abspath(src), os.path.abspath(dest)), stdout=subprocess.DEVNULL, shell=True)
		else:
			os.symlink(os.path.abspath(dest), os.path.abspath(src))
		

	print("enabling FactorioMaps mod")
	modListPath = os.path.join(kwargs["modpath"], "mod-list.json")
	
	if not os.path.samefile(kwargs["modpath"], "../../mods"):
		for f in os.listdir(kwargs["modpath"]):
			if re.match(r'^L0laapk3_FactorioMaps_', f, flags=re.IGNORECASE):
				print("Found other factoriomaps mod in custom mod folder, deleting.")
				path = os.path.join(kwargs["modpath"], f)
				if os.path.islink(path):
					os.unlink(path)
				else:
					os.remove(path)

		linkDir(os.path.join(kwargs["modpath"], os.path.basename(os.path.abspath("."))), ".")
	
		
	
	def changeModlist(newState):
		done = False
		with open(modListPath, "r") as f:
			modlist = json.load(f)
		for mod in modlist["mods"]:
			if mod["name"] == "L0laapk3_FactorioMaps":
				mod["enabled"] = newState
				done = True
		if not done:
			modlist["mods"].append({"name": "L0laapk3_FactorioMaps", "enabled": newState})
		with open(modListPath, "w") as f:
			json.dump(modlist, f, indent=2)

	changeModlist(True)


	manager = mp.Manager()
	rawTags = manager.dict()
	rawTags["__used"] = False



			
	if kwargs["delete"]:
		print("deleting output folder")
		try:
			rmtree(workfolder)
		except (FileNotFoundError, NotADirectoryError):
			pass






	datapath = os.path.join(workfolder, "latest.txt")
	allTmpDirs = []

	isFirstSnapshot = True

	try:

		for index, savename in () if kwargs["dry"] else enumerate(savenames):



			printErase("cleaning up")
			if os.path.isfile(datapath):
				os.remove(datapath)



			printErase("building autorun.lua")
			if (os.path.isfile(os.path.join(workfolder, "mapInfo.json"))):
				with open(os.path.join(workfolder, "mapInfo.json"), "r") as f:
					mapInfoLua = re.sub(r'"([^"]+)" *:', lambda m: '["'+m.group(1)+'"] = ', f.read().replace("[", "{").replace("]", "}"))
					if isFirstSnapshot:
						f.seek(0)
						mapInfo = json.load(f)
						if "options" in mapInfo:
							for kwarg in changedKwargs:
								if kwarg in ("hd", "dayonly", "nightonly", "build-range", "connect-range", "tag-range"):
									printErase("Warning: flag '" + kwarg + "' is overriden by previous setting found in existing timeline.")
						isFirstSnapshot = False

			else:
				mapInfoLua = "{}"
				isFirstSnapshot = False

			if (os.path.isfile(os.path.join(workfolder, "chunkCache.json"))):
				with open(os.path.join(workfolder, "chunkCache.json"), "r") as f:
					chunkCache = re.sub(r'"([^"]+)" *:', lambda m: '["'+m.group(1)+'"] = ', f.read().replace("[", "{").replace("]", "}"))
			else:
				chunkCache = "{}"

			with open("autorun.lua", "w") as f:
				surfaceString = '{"' + '", "'.join(kwargs["surface"]) + '"}' if len(kwargs["surface"]) > 0 else "nil"
				autorunString = (f'fm.autorun = {{\n'
				f'HD = {str(kwargs["hd"] == True).lower()},\n'
				f'day = {str(kwargs["nightonly"] != True).lower()},\n'
				f'night = {str(kwargs["dayonly"] != True).lower()},\n'
				f'alt_mode = {str(kwargs["no-altmode"] != True).lower()},\n'
				f'tags = {str(kwargs["no-tags"] != True).lower()},\n'
				f'around_tag_range = {float(kwargs["tag-range"])},\n'
				f'around_build_range = {float(kwargs["build-range"])},\n'
				f'around_connect_range = {float(kwargs["connect-range"])},\n'
				f'connect_types = {{"lamp", "electric-pole", "radar", "straight-rail", "curved-rail", "rail-signal", "rail-chain-signal", "locomotive", "cargo-wagon", "fluid-wagon", "car"}},\n'
				f'date = "{datetime.datetime.strptime(kwargs["date"], "%d/%m/%y").strftime("%d/%m/%y")}",\n'
				f'surfaces = {surfaceString},\n'
				f'name = "{foldername + "/"}",\n'
				f'mapInfo = {mapInfoLua},\n'
				f'chunkCache = {chunkCache},\n'
				f'}}')
				f.write(autorunString)
				if kwargs["verbose"]:
					printErase(autorunString)


			printErase("building config.ini")
			tmpDir = os.path.join(tempfile.gettempdir(), "FactorioMaps-%s" % random.randint(1, 999999999))
			allTmpDirs.append(tmpDir)
			try:
				rmtree(tmpDir)
			except (FileNotFoundError, NotADirectoryError):
				pass
			os.makedirs(os.path.join(tmpDir, "config"))

			configPath = os.path.join(tmpDir, "config/config.ini")
			config = configparser.ConfigParser()
			config.read("../../config/config.ini")

			config["interface"]["show-tips-and-tricks"] = "false"
			
			config["path"]["write-data"] = tmpDir
			config["graphics"]["screenshots-threads-count"] = str(int(kwargs["screenshotthreads" if kwargs["screenshotthreads"] else "maxthreads"]))
			config["graphics"]["max-threads"] = config["graphics"]["screenshots-threads-count"]
			
			with open(configPath, 'w+') as outf:
				outf.writelines(("; version=3\n", ))
				config.write(outf, space_around_delimiters=False)
				

			linkDir(os.path.join(tmpDir, "script-output"), "../../script-output")
			copy("../../player-data.json", os.path.join(tmpDir, "player-data.json"))

			pid = None
			isSteam = None
			pidBlacklist = [p.info["pid"] for p in psutil.process_iter(attrs=['pid', 'name']) if p.info['name'] == "factorio.exe"]

			popenArgs = (factorioPath, '--load-game', os.path.abspath(os.path.join("../../saves", savename)), '--disable-audio', '--config', configPath, "--mod-directory", os.path.abspath(kwargs["modpath"]), "--disable-migration-window")
			if kwargs["verbose"]:
				printErase(popenArgs)


			condition = mp.Condition()


			results = manager.list()

			printErase("starting factorio")
			startLogProcess = mp.Process(target=startGameAndReadGameLogs, args=(results, condition, popenArgs, tmpDir, pidBlacklist, rawTags), kwargs=kwargs)
			startLogProcess.daemon = True
			startLogProcess.start()


			with condition:
				condition.wait()
			isSteam, pid = results[:]


			if isSteam is None:
				raise Exception("isSteam error")
			if pid is None:
				raise Exception("pid error")
				



			while not os.path.exists(datapath):
				time.sleep(0.4)
			

			open("autorun.lua", 'w').close()

				

			latest = []
			with open(datapath, 'r') as f:
				for line in f:
					latest.append(line.rstrip("\n"))
			if kwargs["verbose"]:
				printErase(latest)

			
			firstOtherInputs = latest[-1].split(" ")
			firstOutFolder = firstOtherInputs.pop(0).replace("/", " ")
			waitfilename = os.path.join(basepath, firstOutFolder, "Images", firstOtherInputs[0], firstOtherInputs[1], firstOtherInputs[2], "done.txt")

			
			isKilled = [False]
			def waitKill(isKilled, pid):
				while not isKilled[0]:
					#print(f"Can I kill yet? {os.path.isfile(waitfilename)} {waitfilename}")
					if os.path.isfile(waitfilename):
						isKilled[0] = True
						kill(pid)
						break
					else:
						time.sleep(0.4)

			killThread = threading.Thread(target=waitKill, args=(isKilled, pid))
			killThread.daemon = True
			killThread.start()



			if workthread and workthread.isAlive():
				#print("waiting for workthread")
				workthread.join()





			timestamp = None
			daytimeSurfaces = {}
			for jindex, screenshot in enumerate(latest):
				otherInputs = list(map(lambda s: s.replace("|", " "), screenshot.split(" ")))
				outFolder = otherInputs.pop(0).replace("/", " ")
				print("Processing {}/{} ({} of {})".format(outFolder, "/".join(otherInputs), len(latest) * index + jindex + 1, len(latest) * len(savenames)))

				timestamp = otherInputs[0]
				if otherInputs[2] in daytimeSurfaces:
					daytimeSurfaces[otherInputs[2]].append(otherInputs[1])
				else:
					daytimeSurfaces[otherInputs[2]] = [otherInputs[1]]

				#print("Cropping %s images" % screenshot)
				crop(outFolder, otherInputs[0], otherInputs[1], otherInputs[2], basepath, **kwargs)
				waitlocalfilename = os.path.join(basepath, outFolder, "Images", otherInputs[0], otherInputs[1], otherInputs[2], "done.txt")
				if not os.path.exists(waitlocalfilename):
					#print("waiting for done.txt")
					while not os.path.exists(waitlocalfilename):
						time.sleep(0.4)



				def refZoom():
					needsThumbnail = index + 1 == len(savenames)
					#print("Crossreferencing %s images" % screenshot)
					ref(outFolder, otherInputs[0], otherInputs[1], otherInputs[2], basepath, **kwargs)
					#print("downsampling %s images" % screenshot)
					zoom(outFolder, otherInputs[0], otherInputs[1], otherInputs[2], basepath, needsThumbnail, **kwargs)

					if jindex == len(latest) - 1:
						print("zooming renderboxes", timestamp)
						zoomRenderboxes(daytimeSurfaces, workfolder, timestamp, os.path.join(basepath, firstOutFolder, "Images"), **kwargs)

				if screenshot != latest[-1]:
					refZoom()
				else:
					
					startLogProcess.terminate()

					# I have receieved a bug report from feidan in which he describes what seems like that this doesnt kill factorio?
					
					onlyStall = isKilled[0]
					isKilled[0] = True
					kill(pid, onlyStall)

					if savename == savenames[-1]:
						refZoom()

					else:
						workthread = threading.Thread(target=refZoom)
						workthread.daemon = True
						workthread.start()

			



		

			

		if os.path.isfile(os.path.join(workfolder, "mapInfo.out.json")):
			print("generating mapInfo.json")
			with open(os.path.join(workfolder, "mapInfo.json"), 'r+') as destf, open(os.path.join(workfolder, "mapInfo.out.json"), "r") as srcf:
				data = json.load(destf)
				for mapIndex, mapStuff in json.load(srcf)["maps"].items():
					for surfaceName, surfaceStuff in mapStuff["surfaces"].items():
						if "chunks" in surfaceStuff:
							data["maps"][int(mapIndex)]["surfaces"][surfaceName]["chunks"] = surfaceStuff["chunks"]
						for linkIndex, link in enumerate(surfaceStuff["links"]):
							data["maps"][int(mapIndex)]["surfaces"][surfaceName]["links"][linkIndex]["path"] = link["path"]
							data["maps"][int(mapIndex)]["surfaces"][surfaceName]["links"][linkIndex]["zoom"]["min"] = link["zoom"]["min"]
				destf.seek(0)
				json.dump(data, destf)
				destf.truncate()
			os.remove(os.path.join(workfolder, "mapInfo.out.json"))



		print("updating labels")
		tags = {}
		with open(os.path.join(workfolder, "mapInfo.json"), 'r+') as mapInfoJson:
			data = json.load(mapInfoJson)
			for mapStuff in data["maps"]:
				for surfaceName, surfaceStuff in mapStuff["surfaces"].items():
					if "tags" in surfaceStuff:
						for tag in surfaceStuff["tags"]:
							if "iconType" in tag:
								tags[tag["iconType"] + tag["iconName"][0].upper() + tag["iconName"][1:]] = tag

		rmtree(os.path.join(workfolder, "Images", "labels"), ignore_errors=True)
		
		modVersions = sorted(
				map(lambda m: (m.group(2).lower(), (m.group(3), m.group(4), m.group(5), m.group(6) is None), m.group(1)),
					filter(lambda m: m,
						map(lambda f: re.search(r"^((.*)_(\d+)\.(\d+)\.(\d+))(\.zip)?$", f, flags=re.IGNORECASE),
							os.listdir(os.path.join(basepath, kwargs["modpath"]))))),
				key = lambda t: t[1],
				reverse = True)


		rawTags["__used"] = True
		if not kwargs["no-tags"]:
			for _, tag in tags.items():
				dest = os.path.join(workfolder, tag["iconPath"])
				os.makedirs(os.path.dirname(dest), exist_ok=True)
				

				rawPath = rawTags[tag["iconType"] + tag["iconName"][0].upper() + tag["iconName"][1:]]


				icons = rawPath.split('|')
				img = None
				for i, path in enumerate(icons):
					m = re.match(r"^__([^\/]+)__[\/\\](.*)$", path)
					if m is None:
						raise Exception("raw path of %s %s: %s not found" % (tag["iconType"], tag["iconName"], path))

					iconColor = m.group(2).split("?")
					icon = iconColor[0]
					if m.group(1) in ("base", "core"):
						src = os.path.join(os.path.split(factorioPath)[0], "../../data", m.group(1), icon + ".png")
					else:
						mod = next(mod for mod in modVersions if mod[0] == m.group(1).lower())
						if not mod[1][3]: #true if mod is zip
							zipPath = os.path.join(basepath, kwargs["modpath"], mod[2] + ".zip")
							with ZipFile(zipPath, 'r') as zipObj:
								if len(icons) == 1:
									zipInfo = zipObj.getinfo(os.path.join(mod[2], icon + ".png").replace('\\', '/'))
									zipInfo.filename = os.path.basename(dest)
									zipObj.extract(zipInfo, os.path.dirname(os.path.realpath(dest)))
									src = None
								else:
									src = zipObj.extract(os.path.join(mod[2], icon + ".png").replace('\\', '/'), os.path.join(tempfile.gettempdir(), "FactorioMaps"))
						else:
							src = os.path.join(basepath, kwargs["modpath"], mod[2], icon + ".png")
					
					if len(icons) == 1:
						if src is not None:
							copy(src, dest)
					else:
						newImg = Image.open(src).convert("RGBA")
						if len(iconColor) > 1:
							newImg = ImageChops.multiply(newImg, Image.new("RGBA", newImg.size, color=tuple(map(lambda s: int(round(float(s))), iconColor[1].split("%")))))
						if i == 0:
							img = newImg
						else:
							img.paste(newImg.convert("RGB"), (0, 0), newImg)
				if len(icons) > 1:
					img.save(dest)







		#TODO: download leaflet shit

		print("generating mapInfo.js")
		with open(os.path.join(workfolder, "mapInfo.js"), 'w') as outf, open(os.path.join(workfolder, "mapInfo.json"), "r") as inf:
			outf.write('"use strict";\nwindow.mapInfo = JSON.parse(')
			outf.write(json.dumps(inf.read()))
			outf.write(");")
			
			
		print("creating index.html")
		copy("web/index.html", os.path.join(workfolder, "index.html"))
		copy("web/index.css", os.path.join(workfolder, "index.css"))
		copy("web/index.js", os.path.join(workfolder, "index.js"))
		try:
			rmtree(os.path.join(workfolder, "lib"))
		except (FileNotFoundError, NotADirectoryError):
			pass
		copytree("web/lib", os.path.join(workfolder, "lib"))



	except KeyboardInterrupt:
		print("keyboardinterrupt")
		kill(pid)
		raise

	finally:

		try:
			kill(pid)
		except:
			pass

		print("disabling FactorioMaps mod")
		changeModlist(False)



		print("cleaning up")
		for tmpDir in allTmpDirs:
			try:
				os.unlink(os.path.join(tmpDir, "script-output"))
				rmtree(tmpDir)
			except (FileNotFoundError, NotADirectoryError):
				pass









if __name__ == '__main__':
	auto(*sys.argv[1:])