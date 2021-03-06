# -*- coding: utf-8 -*-
from Screens.Screen import Screen
from Screens.Setup import SetupSummary
from Screens.MessageBox import MessageBox
from Components.ConfigList import ConfigList, ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSelection, ConfigText, ConfigClock, ConfigSubsection, ConfigYesNo, ConfigSubDict, ConfigNothing, ConfigInteger, configfile
from Components.ServiceEventTracker import ServiceEventTracker
from Components.ActionMap import ActionMap
from Components.Label import Label
from Screens.SessionGlobals import SessionGlobals
from Components.Sources.StaticText import StaticText
from Components.MenuList import MenuList
from enigma import iPlayableService, iServiceInformation, eTimer, eConsoleAppContainer, gFont, addFont, loadPNG, eListboxPythonMultiContent, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER, RT_VALIGN_CENTER, eLabel, eWidget, eSlider, fontRenderClass, ePoint, eSize, eDBoxLCD, ePicLoad, gPixmapPtr, eEPGCache
from Plugins.Plugin import PluginDescriptor
from Queue import Queue, PriorityQueue
import datetime
from Tools.BoundFunction import boundFunction
from Screens.ChannelSelection import SimpleChannelSelection, service_types_tv, service_types_radio
from twisted.web.client import downloadPage, getPage, error
from twisted.internet import reactor, defer
from Screens.Screen import Screen
from Plugins.Plugin import PluginDescriptor
from ServiceReference import ServiceReference
from enigma import ePixmap, eServiceCenter, eServiceReference, eTimer, eEPGCache
from Tools.Directories import pathExists, fileExists
from Tools.BoundFunction import boundFunction
from threading import Thread
import threading, re, os, requests, json
from urllib import quote, unquote_plus, unquote, urlencode, time, quote_plus
import base64
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from datetime import datetime, timedelta
from Tools import Notifications
from Screens.Screen import Screen
from os.path import splitext, basename
from urlparse import urlparse
import skin
import uuid
from pyDes import *

import NavigationInstance
from RecordTimer import RecordTimerEntry, RecordTimer, parseEvent, AFTEREVENT
from Components.TimerSanityCheck import TimerSanityCheck
import Screens.Standby

def getkeychallenge():
    k = triple_des((str(uuid.getnode()) * 2)[0:24], CBC, "\0\0\0\0\0\0\0\0", padmode=PAD_PKCS5)
    d = k.encrypt(open(base64.b64decode("L3N5cy9jbGFzcy9uZXQvZXRoMC9hZGRyZXNz"), "r").readline().strip())
    return quote_plus(base64.b64encode(d))

def getpayload(session):
	key = str(getkeychallenge())
	if str(config.plugins.epgShare.supporterKey.value) != "":
		url = "http://timeforplanb.linevast-hosting.in/dologin.php?key=%s&supporter=%s" % (key, str(config.plugins.epgShare.supporterKey.value))
	else:
		url = "http://timeforplanb.linevast-hosting.in/dologin.php?key=%s" % key
	payload = session.get(url, timeout=10).text
	try:
		return json.loads(payload)
	except:
		return payload

epgDownloadThread = None
updatethread = None
eventinfo_orig = None

config.plugins.epgShare = ConfigSubsection()
config.plugins.epgShare.auto = ConfigYesNo(default=True)
config.plugins.epgShare.hours = ConfigInteger(12, (1, 24))
config.plugins.epgShare.onstartup = ConfigYesNo(default=False)
config.plugins.epgShare.useimprover = ConfigYesNo(default=False)
config.plugins.epgShare.onstartupdelay = ConfigInteger(2, (1, 60))
config.plugins.epgShare.debug = ConfigYesNo(default=False)
config.plugins.epgShare.writelog = ConfigYesNo(default=False)
config.plugins.epgShare.autorefreshtime = ConfigClock(default=6 * 3600)
config.plugins.epgShare.starttimedelay = ConfigInteger(default=10)
config.plugins.epgShare.titleSeasonEpisode = ConfigYesNo(default=False)
config.plugins.epgShare.titleDate = ConfigYesNo(default=False)
config.plugins.epgShare.sendTransponder = ConfigYesNo(default=True)
config.plugins.epgShare.supporterKey = ConfigText(default="", fixed_size=False)
config.plugins.epgShare.lastupdate = ConfigText(default="", fixed_size=False)
config.plugins.epgShare.afterAuto = ConfigSelection(default = "0", choices = [("0", "keine"), ("1", "in Standby gehen"), ("2", "in Deep-Standby gehen")])

def getSingleEventList(ref):
	epgcache = eEPGCache.getInstance()
	test = ['RIBDTEX', (str(ref), 0, time(), -1)]
	event = epgcache.lookupEvent(test)
	return event

def getServiceList(ref):
	root = eServiceReference(str(ref))
	serviceHandler = eServiceCenter.getInstance()
	return serviceHandler.list(root).getContent("SN", True)

def getTVBouquets():
	return getServiceList(service_types_tv + ' FROM BOUQUET "bouquets.tv" ORDER BY bouquet')

def getRefList():
	l = []
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		for (serviceref, servicename) in bouquetlist:
			if not serviceref in l:
				l.append(serviceref)
	return l

def getRefListJson(getextradata=False):
	refs = []
	l = []
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		colorprint("Bouquets: %s" % len(tvbouquets))
		colorprint("Bouquets %s" % tvbouquets)
		for (serviceref, servicename) in bouquetlist:
			if not serviceref in refs:
				refs.append(serviceref)
				if getextradata:
					lasteventtime = 0
				else:
					try:
						lastevent = eEPGCache.getInstance().lookupEvent(["IB", (str(serviceref), 3)])
						(event_id, starttime) = lastevent[0]
						lasteventtime = starttime
					except:
						lasteventtime = 0
				colorprint("%s - %s - %s" % (servicename, str(serviceref), str(lasteventtime)))
				l.append({'ref': str(serviceref), 'time': lasteventtime, 'name': servicename})
	return l

def builFullChannellist():
	allchannels = []
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		for (serviceref, servicename) in bouquetlist:
			if len(filter(lambda channel: channel[1] == serviceref, allchannels)) == 0:
				allchannels.append((servicename, serviceref))
	return allchannels

def fixTitle(title):
	if title.lower() == "csi: ny":
		title = "CSI: New York"
	return title

def getRefFromChannelName(channelname):
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		for (serviceref, servicename) in bouquetlist:
			if channelname == servicename:
				return serviceref

def colorprint(stringvalue):
	if config.plugins.epgShare.writelog.value:
		writeLog(stringvalue)
	if config.plugins.epgShare.debug.value:
		color_print = "\033[92m"
		color_end = "\33[0m"
		print color_print + "[EPG Share] " + str(stringvalue) + color_end

def writeLog(text):
	logFile = "/tmp/epgshare.log"
	if not fileExists(logFile):
		open(logFile, 'w').close()

	writeLogFile = open(logFile, "a")
	writeLogFile.write('%s\n' % (text))
	writeLogFile.close()

def getlasteventtime(serviceref):
	try:
		lasteventtime = 0
		lastevent = eEPGCache.getInstance().lookupEvent(["IB", (str(serviceref), 3)])
		(event_id, starttime) = lastevent[0]
		lasteventtime = starttime
		if lasteventtime > 0:
			return lasteventtime
		else:
			return None
	except:
		return None

class autoGetEpg():
	def __init__(self, session):
		assert not autoGetEpg.instance, "only one autoGetEp instance is allowed!"
		autoGetEpg.instance = self
		self.session = session
		self.Timer = eTimer()
		self.Timer.callback.append(self.getepg)
		self.timerRunning = False

	def startTimer(self):
		if config.plugins.epgShare.auto.value:
			self.Timer.stop()
			now = datetime.now()
			now = now.hour * 60 + now.minute
			start_time = config.plugins.epgShare.autorefreshtime.value[0] * 60 + config.plugins.epgShare.autorefreshtime.value[1]
			if now < start_time:
				start_time -= now
			else:
				start_time += 1440 - now
			self.Timer.start(start_time * 60 * 1000,True)
			self.timerRunning = True
			now = str(datetime.now().strftime('%d.%m.%Y %H:%M:%S'))
			colorprint("Auto EPG Update startet in %s min. um %s:%s Uhr." % (str(start_time), str(config.plugins.epgShare.autorefreshtime.value[0]), str(config.plugins.epgShare.autorefreshtime.value[1])))
			return
		else:
			colorprint("Auto EPG Update ist nicht in den Einstellungen aktiviert.")

	def stopTimer(self):
		colorprint("Auto EPG Update STOPPED.")
		if self.timerRunning:
			self.Timer.stop()
			self.timerRunning = False

	def isRunning(self):
		colorprint("Auto EPG Update STATUS: %s" % str(self.timerRunning))
		return self.timerRunning

	def getepg(self):
		global epgDownloadThread
		if epgDownloadThread is None:
			epgDownloadThread = epgShareDownload(self.session, False, True)
			epgDownloadThread.start()
			Notifications.AddPopup("Epg Share Autoupdate wurde gestartet...", MessageBox.TYPE_INFO, timeout=5)
		else:
			if not epgDownloadThread.isRunning:
				epgDownloadThread = None
				epgDownloadThread = epgShareDownload(self.session, False, True)
				epgDownloadThread.start()
				Notifications.AddPopup("Epg Share Autoupdate wurde gestartet...", MessageBox.TYPE_INFO, timeout=5)

class delayEpgDownload():

	def __init__(self, session):
		assert not delayEpgDownload.instance, "only one delayEpgDownload instance is allowed!"
		delayEpgDownload.instance = self
		self.session = session

	def startTimer(self):
		if config.plugins.epgShare.onstartup.value:
			self.delaytimer = eTimer()
			self.delaytimer.callback.append(self.delayEpgDownload)
			self.delaytimer.start(60000 * int(config.plugins.epgShare.onstartupdelay.value))

	def delayEpgDownload(self):
		self.delaytimer.stop()
		epgDown = epgShareDownload(self.session)
		epgDown.start()


class epgShareDownload(threading.Thread):

	def __init__(self, session, callback=False, autoupdate=False):
		self.session = session
		self.callback = callback
		self.callback_infos = None
		self.autoupdate = autoupdate
		self.isRunning = False
		self.epgcache = eEPGCache.getInstance()
		self.starttime_unix = 0
		self.endtime_unix = 0
		threading.Thread.__init__(self)

	def setCallback(self, callback_infos):
		self.callback_infos = callback_infos

	def msgCallback(self, txt):
		if self.callback_infos:
			self.callback_infos(txt)

	def stop(self):
		self.isRunning = False

	def run(self):
		self.starttime_unix = time.time()
		colorprint("---------------------------------------------------------- START -------------------------------------------------------------------------")
		colorprint("Starte EPG-Download %s" % time.strftime("%d.%m.%Y - %H:%M", time.gmtime()))
		s = requests.Session()
		p = getpayload(s)
		if isinstance(p, dict):
			payload = p['payloaddata'][0]['payload']
			sessionkey = p['payloaddata'][0]['sessionkey']
			if payload > 0 and str(sessionkey) != '':
				self.isRunning = True
				colorprint("Hole EPG Daten vom Server")
				self.msgCallback("Hole EPG Daten vom Server.. Bitte warten")
				requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
				if config.plugins.epgShare.useimprover.value:
					refs = getRefListJson(getextradata=True)
				else:
					refs = getRefListJson(getextradata=True) # lasttime erstmal deaktiviert
				for ref in refs:
					colorprint("Loading ChannelEPG: %s / %s" % (str(ref['ref']), str(ref['name'])))
					try:
						if config.plugins.epgShare.useimprover.value:
							data = s.post("http://timeforplanb.linevast-hosting.in/download_epg_2.php?sessionkey=" + sessionkey + "&extradata=true&finished=false", data=json.dumps(ref), timeout=180).json()
						else:
							data = s.post("http://timeforplanb.linevast-hosting.in/download_epg_2.php?sessionkey=" + sessionkey + "&extradata=false&finished=false", data=json.dumps(ref), timeout=180).json()
						events = data['events']
					except Exception, ex:
						events = None
						colorprint("Fehler beim EPG Download !!!")
						if self.callback:
							self.msgCallback("Fehler beim EPG Download %s" % str(ex))
					if events is not None:
						events_list = []
						count_refs = len(events)
						for event in events:
							if not self.isRunning:
								break
							gotextradata = False
							#print event
							if 'extradata' in event:
								if not event['extradata'] is None:
									gotextradata = True

							if not gotextradata:
								events_list.append((long(event['starttime']), int(event['duration']), str(event['title']).encode('utf-8'), str(event['subtitle']).encode('utf-8'), str(event['handlung']).encode('utf-8'), 0, long(event['event_id'])),)
							else:
								title = str(event['title'])
								#print "GotExtradata: %s" % str(event['extradata'])
								if config.plugins.epgShare.titleSeasonEpisode.value:
									extradata = json.loads(event['extradata'])
									if 'categoryName' in str(extradata):
										if 'Serie' in str(extradata):
											if 'season' and 'episode' in str(extradata):
												season = str(extradata['season'])
												episode = str(extradata['episode'])
												if season and episode != '':
													if int(season) < 10:
														season = "S0"+str(season)
													else:
														season = "S"+str(season)
													if int(episode) < 10:
														episode = "E0"+str(episode)
													else:
														episode = "E"+str(episode)
													title = "%s - %s%s" % (title, season, episode)			
								events_list.append((long(event['starttime']), int(event['duration']), str(title).encode('utf-8'), str(event['subtitle']).encode('utf-8'), "%s \n<x>%s</x>" % (str(event['handlung']).encode('utf-8'), str(event['extradata']).encode('utf-8')), 0, long(event['event_id'])),)
								count_refs += 1
						self.epgcache.importLockedEventswithID(str(ref['ref']), events_list)
						colorprint("Import %s Events for Channel: %s" % (len(events_list), str(ref['name'])))
						if self.callback:
							self.msgCallback("Import %s Events for Channel: %s" % (len(events_list), str(ref['name'])))
				colorprint("EPG Download beendet.")
				self.epgcache.save()
				s.post("http://timeforplanb.linevast-hosting.in/download_epg_2.php?sessionkey=" + sessionkey + "&finished=true&extradata=false", data=json.dumps(ref), timeout=180)
				if self.callback:
					self.msgCallback("EPG Download beendet.")
				else:
					if self.autoupdate:
						Notifications.AddPopup("Epg Share Autoupdate abgeschlossen...", MessageBox.TYPE_INFO, timeout=5)
					else:
						Notifications.AddPopup("Epg Share Update abgeschlossen...", MessageBox.TYPE_INFO, timeout=5)
					self.isRunning = False
			else:
				if self.callback:
					self.msgCallback("Maximale Downloads pro Tag erreicht. Reset erfolgt um 0 Uhr")
		else:
			if self.callback:
				self.msgCallback(str(p))
		global epgDownloadThread
		epgDownloadThread = None
		if self.autoupdate:
			self.afterAuto()
		self.endtime_unix = time.time()
		duration_time_unix = int((self.endtime_unix - self.starttime_unix))
		if self.callback:
			self.msgCallback("Der EPG Download dauerte %s sekunden" % str(duration_time_unix))
		colorprint("Der EPG Download dauerte %s sekunden" % str(duration_time_unix))
		colorprint("---------------------------------------------------------- ENDE -------------------------------------------------------------------------")

	def afterAuto(self):
		if config.plugins.epgShare.afterAuto.value == 1:
			#self.msgCallback("gehe in Standby")
			colorprint("gehe in Standby")
			Notifications.AddNotification(Screens.Standby.Standby)
		elif config.plugins.epgShare.afterAuto.value == "2":
			if not NavigationInstance.instance.RecordTimer.isRecording():
				#self.msgCallback("gehe in Deep-Standby")
				colorprint("gehe in Deep-Standby")
				if Screens.Standby.inStandby:
					RecordTimerEntry.TryQuitMainloop()
				else:
					Notifications.AddNotificationWithID("Shutdown", Screens.Standby.TryQuitMainloop, 1)
			else:
				#self.msgCallback("Eine laufenden Aufnahme verhindert den Deep-Standby")
				colorprint("Eine laufenden Aufnahme verhindert den Deep-Standby")

class epgShareUploader(threading.Thread):

	def __init__(self, session):
		self.session = session
		self.stopped = False
		self.channelqueue = Queue()
		self.queuelist = []
		self.epgcache = eEPGCache.getInstance()
		threading.Thread.__init__(self)

	def stopme(self):
		self.channelqueue = None
		self.queuelist = None
		self.stopped = True

	def run(self):
		colorprint("Grab Channel EPG")
		while not self.stopped:
			try:
				if not self.channelqueue.empty():
					while not self.channelqueue.empty():
						if not self.stopped:
							channel_ref = None
							try:
								info = self.channelqueue.get()
								if info:
									(channel_name, channel_ref) = info
									colorprint("%s %s" % (channel_name, channel_ref))

									dvb_events = []
									count_dvb_events = 0
									dvb_events_real = []
									count_dvb_events_real = 0
									test = [ 'IBDTSEv', (channel_ref, 0, time.time(), -1)]
									dvb_events = self.epgcache.lookupEvent(test)
									count_dvb_events = len(dvb_events)
									time.sleep(1)
									colorprint("Checking Eventcount")
									while len(self.epgcache.lookupEvent(test)) > count_dvb_events:
										if not self.stopped:
											colorprint("Eventcount is increasing")
											colorprint("Waiting 1 Second")
											time.sleep(1)
											dvb_events = self.epgcache.lookupEvent(test)
											count_dvb_events = len(dvb_events)
										else:
											break
									colorprint("Eventcount is not increasing... no Channelupdate running")
									dvb_events_real = filter(lambda x: str(x[6]) in ['NOWNEXT', 'SCHEDULE','PRIVATE_UPDATE'], dvb_events)
									count_dvb_events_real = str(len(dvb_events_real))
									colorprint("Count %s from %s Events" % (str(count_dvb_events_real), str(count_dvb_events)))
									if len(dvb_events_real) > 0:
										postdata = []
										for event in dvb_events_real:
											if not self.stopped:
												(event_id, starttime, duration, title, subtitle, handlung, import_type) = event
												ev = {}
												ev['event_id'] = str(event_id)
												ev['addtime'] = str(int(time.time()))
												ev['channel_name'] = str(channel_name.replace('\xc2\x86', '').replace('\xc2\x87', ''))
												ev['channel_ref'] = str(channel_ref)
												ev['starttime'] = str(starttime)
												ev['duration'] = str(duration)
												ev['title'] = str(title).encode('utf-8')
												ev['subtitle'] = str(subtitle).strip().encode('utf-8')
												ev['handlung'] = str(handlung).strip().encode('utf-8')
												postdata.append(ev)
										if not self.stopped:
											requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
											post = {'events': json.dumps(postdata)}
											colorprint(str(requests.post('http://timeforplanb.linevast-hosting.in/import_epg.php', data=post, timeout=10).text))
							except Exception, ex:
								colorprint("Grab Channel EPG - Error: %s" % str(ex))
							if channel_ref:
								if self.queuelist:
									self.queuelist.remove(channel_ref)
								else:
									self.stopped = True
			except:
				pass
			time.sleep(1)

	def addChannel(self, channel):
		if not channel[1] in self.queuelist:
			self.queuelist.append(channel[1])
			self.channelqueue.put(channel)

	def getChannelNameRef(self):
		service = self.session.nav.getCurrentService()
		service_ref = self.session.nav.getCurrentlyPlayingServiceReference().toString().replace(str(self.session.nav.getCurrentlyPlayingServiceReference().getPath()), "")
		if service and service is not None:
			service_name = service.info().getName()
			return [service_name, service_ref]
		else:
			return None


class epgShare(Screen):

	def __init__(self, session):
		Screen.__init__(self, session)
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
		{
			iPlayableService.evUpdatedInfo: self.__evUpdatedInfo,
			iPlayableService.evStart: self.__evStart
		})
		self.Timer = eTimer()
		self.Timer.callback.append(self.delaytimer)
		self.container = None
		self.newService = False
		self.epgUp = epgShareUploader(self.session)
		self.epgUp.start()
		self.transcache = {}
		self.onClose.append(self.__onClose)

	def __evStart(self):
		self.newService = True

	def __evUpdatedInfo(self):
		if self.newService:
			try:
				if self.session.nav.getCurrentlyPlayingServiceReference().getPath() == "":
					self.Timer.start(10000)
					self.newService = False
			except:
				pass

	def __onClose(self):
		#self.epgUp.stopme()
		#self.epgUp = None
		return

	def delaytimer(self):
		self.Timer.stop()
		try:
			if config.plugins.epgShare.sendTransponder.value:
				cur_ref = self.session.nav.getCurrentlyPlayingServiceReference()
				pos = service_types_tv.rfind(':')
				refstr = '%s (channelID == %08x%04x%04x) && %s ORDER BY name' % (service_types_tv[:pos+1],
									cur_ref.getUnsignedData(4),
									cur_ref.getUnsignedData(2),
									cur_ref.getUnsignedData(3),
									service_types_tv[pos+1:])
				doupdate = False
				if refstr in self.transcache:
					if self.transcache[refstr] < time.time() - 3600:
						doupdate = True
				else:
					doupdate = True
				if doupdate:
					self.transcache[refstr] = time.time()
					for (serviceref, servicename) in getServiceList(refstr):
						self.epgUp.addChannel([servicename, serviceref])
			else:
				self.epgUp.addChannel(self.getChannelNameRef())
		except:
			pass

	def getChannelNameRef(self):
		service = self.session.nav.getCurrentService()
		service_ref = self.session.nav.getCurrentlyPlayingServiceReference().toString().replace(str(self.session.nav.getCurrentlyPlayingServiceReference().getPath()), "")
		if service and service is not None:
			service_name = service.info().getName()
			return [service_name, service_ref]
		else:
			return None


class epgShareScreen(Screen):
	skin = """
		<screen name="EPG Share" title="EPG Share" position="center,center" size="1280,720">
			<widget name="info" position="10,10" size="600,50" zPosition="5" transparent="0" halign="left" valign="top" font="Regular; 30" />
			<widget name="list" position="10,80" size="1260,570" scrollbarMode="showOnDemand" scrollbarSliderBorderWidth="0" scrollbarWidth="5" scrollbarBackgroundPicture="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/scrollbarbg.png" />
			<widget name="key_red" position="99,680" size="265,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<widget name="key_green" position="411,680" size="265,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<widget name="key_yellow" position="761,680" size="265,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<widget name="key_blue" position="1073,680" size="200,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<ePixmap position="59,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_red.png" alphatest="on" />
			<ePixmap position="374,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_green.png" alphatest="on" />
			<ePixmap position="726,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_yellow.png" alphatest="on" />
			<ePixmap position="1037,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_blue.png" alphatest="on" />
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self["actions"]  = ActionMap(["OkCancelActions", "ShortcutActions", "WizardActions", "ColorActions", "SetupActions", "NumberActions", "MenuActions", "EPGSelectActions"], {
			"cancel":	self.keyCancel,
			"red"	:	self.keyCancel,
			"yellow" :	self.keyRun,
			"blue"	:	self.keyConfig
		}, -1)

		self.chooseMenuList = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
		font, size = skin.parameters.get("EPGShareListFont", ('Regular', 20))
		self.itemheight = int(skin.parameters.get("EPGShareListItemHeight", (38,))[0])
		self.listwidth = int(skin.parameters.get("EPGShareListWidth", (1260,))[0])
		self.chooseMenuList.l.setFont(0, gFont(font, int(size)))
		self.chooseMenuList.l.setItemHeight(self.itemheight)
		self.chooseMenuList.selectionEnabled(False)

		self['info'] = Label(_("Info"))
		self['list'] = self.chooseMenuList
		self['key_red'] = Label(_("Exit"))
		self['key_green'] = Label(_(" "))
		self['key_yellow'] = Label(_("EPG Download"))
		self['key_blue'] = Label(_("Einstellungen"))
		self.list = []
		self.onLayoutFinish.append(self.startrun)

	def startrun(self):
		self.onLayoutFinish.remove(self.startrun)
		global epgDownloadThread
		if not epgDownloadThread is None:
			self.isEpgDownload = True
			epgDownloadThread.setCallback(self.callbacks)
			if epgDownloadThread.isRunning:
				self['key_yellow'].hide()
		else:
			self.isEpgDownload = False

	def callbacks(self, text):
		if text == "EPG Download beendet.":
			self['key_yellow'].show()
			self.isEpgDownload = False
		self.showInfo(text)

	def showInfo(self, text):
		try:
			self.list.insert(0, text)
			self.chooseMenuList.setList(map(self.showList, self.list))
		except:
			pass

	def showList(self, entry):
		return [entry,
			(eListboxPythonMultiContent.TYPE_TEXT, 10, 0, self.listwidth - 20, self.itemheight, 0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, entry)
			]

	def keyConfig(self):
		self.session.open(epgShareSetup)

	def keyRun(self):
		canrun = False

		global epgDownloadThread
		if epgDownloadThread is None:
			epgDownloadThread = epgShareDownload(self.session, True)
			canrun = True
		else:
			if not epgDownloadThread.isRunning:
				epgDownloadThread = None
				epgDownloadThread = epgShareDownload(self.session, True)
				canrun = True
			else:
				epgDownloadThread.setCallback(self.callbacks)
				self['key_yellow'].hide()
		if canrun:
			self.list = []
			self.isEpgDownload = True
			epgDownloadThread.setCallback(self.callbacks)
			epgDownloadThread.start()
			self['key_yellow'].hide()

	def keyCancel(self):
		if self.isEpgDownload:
			global epgDownloadThread
			self.isEpgDownload = False
			if not epgDownloadThread is None:
				epgDownloadThread.setCallback(None)
		self.close()


class epgShareSetup(Screen, ConfigListScreen):
	skin = """
		<screen name="EPG Share Setup" title="EPG Share Setup" position="center,center" size="1280,720">
			<widget name="info" position="10,10" size="600,50" zPosition="5" transparent="0" halign="left" valign="top" font="Regular; 30" />
			<widget name="config" position="10,80" size="1260,570" font="Regular;22" textOffset="20,2" itemHeight="50" scrollbarMode="showOnDemand" scrollbarSliderBorderWidth="0" scrollbarWidth="5" scrollbarBackgroundPicture="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/scrollbarbg.png" />
			<widget name="key_red" position="99,680" size="265,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<widget name="key_green" position="411,680" size="265,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<widget name="key_yellow" position="761,680" size="265,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<widget name="key_blue" position="1073,680" size="200,30" zPosition="1" font="Regular;22" halign="left" foregroundColor="#00ffffff" transparent="0" />
			<ePixmap position="59,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_red.png" alphatest="on" />
			<ePixmap position="374,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_green.png" alphatest="on" />
			<ePixmap position="726,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_yellow.png" alphatest="on" />
			<ePixmap position="1037,684" size="25,25" zPosition="-1" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/button_blue.png" alphatest="on" />
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self["actions"] = ActionMap(["OkCancelActions", "ShortcutActions", "WizardActions", "ColorActions", "SetupActions", "NumberActions", "MenuActions", "EPGSelectActions"], {
			"cancel":	self.keyCancel,
			"red"	:	self.keyCancel,
			"green"	:	self.keySave,
			"left"	:	self.keyLeft,
			"right"	:	self.keyRight
		}, -1)
		self.useimprovervalue = config.plugins.epgShare.useimprover.value
		self['info'] = Label(_("EPG Share Einstellung"))
		self['key_red'] = Label(_("Cancel"))
		self['key_green'] = Label(_("Save"))
		self['key_yellow'] = Label(_(" "))
		self['key_blue'] = Label("")
		self.list = []
		self.isEpgDownload = False
		self.createConfigList()
		ConfigListScreen.__init__(self, self.list)

	def createConfigList(self):
		self.list = []
		self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen"), config.plugins.epgShare.auto))
		if config.plugins.epgShare.auto.value:
			self.list.append(getConfigListEntry(_("Uhrzeit"), config.plugins.epgShare.autorefreshtime))
			self.list.append(getConfigListEntry(_("Aktion nach dem automatischen EPG Download:"), config.plugins.epgShare.afterAuto))
		self.list.append(getConfigListEntry(_("EPG mit Extradaten verbessern"), config.plugins.epgShare.useimprover))
		if config.plugins.epgShare.useimprover.value:
			self.list.append(getConfigListEntry(_("Season und Episode (S01E01) zum Sendungs-Titel hinzufügen"), config.plugins.epgShare.titleSeasonEpisode))
		#self.list.append(getConfigListEntry(_("Supporter Key"), config.plugins.epgShare.supporterKey))
		self.list.append(getConfigListEntry(_("Debug Ausgabe in der Console"), config.plugins.epgShare.debug))
		self.list.append(getConfigListEntry(_("Debug Ausgabe in Log schreiben /tmp/epgshare.log"), config.plugins.epgShare.writelog))

	def changedEntry(self):
		self.createConfigList()
		self["config"].setList(self.list)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.changedEntry()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.changedEntry()

	def keySave(self):
		global bg_timer
		global eventinfo_orig
		config.plugins.epgShare.auto.save()
		config.plugins.epgShare.autorefreshtime.save()
		config.plugins.epgShare.onstartup.save()
		config.plugins.epgShare.onstartupdelay.save()
		config.plugins.epgShare.titleSeasonEpisode.save()
		config.plugins.epgShare.useimprover.save()
		config.plugins.epgShare.sendTransponder.save()
		config.plugins.epgShare.supporterKey.save()
		config.plugins.epgShare.debug.save()
		config.plugins.epgShare.save()
		config.plugins.epgShare.afterAuto.save()
		config.plugins.epgShare.writelog.save()
		configfile.save()
		if config.plugins.epgShare.auto.value:
			if not bg_timer.isRunning():
				bg_timer.startTimer()
			else:
				bg_timer.stopTimer()
				bg_timer.startTimer()
		else:
			if bg_timer.isRunning():
				bg_timer.stopTimer()
		self.close()

	def keyCancel(self):
		self.close()

def epgshare_init_shutdown():
	colorprint("Initializing Shutdown")
	global updateservice
	if not updateservice is None:
		updateservice.epgUp.stopme()
		updateservice.epgUp = None
		updateservice.close()
	global epgDownloadThread
	if not epgDownloadThread is None:
		epgDownloadThread.stop()
		epgDownloadThread = None
	if config.plugins.epgShare.auto.value:
		now = time.localtime()
		current_time = int(time.time())
		begin = int(time.mktime((now.tm_year,
		                         now.tm_mon,
		                         now.tm_mday,
		                         config.plugins.epgShare.autorefreshtime.value[0],
                                 config.plugins.epgShare.autorefreshtime.value[1],
                                 0,
                                 now.tm_wday,
                                 now.tm_yday,
                                 now.tm_isdst)))
		if int(current_time) > int(begin):
			begin += 86400
		begin -= 120
		os.system("touch /ect/enigma2/epgshareds")
		wt = time.strftime("%d.%m.%Y - %H:%M", time.localtime(int(begin)))
		colorprint("Deep-Standby WakeUp um %s" % wt)
		return begin


def autostart(reason, **kwargs):
	if "session" in kwargs:
		session = kwargs["session"]
		# Starte Upload Service
		global updateservice
		updateservice = epgShare(session)
		autoGetEpg(session)
		global bg_timer
		bg_timer = autoGetEpg.instance
		if config.plugins.epgShare.auto.value:
			bg_timer.startTimer()

def main(session, **kwargs):
	session.open(epgShareScreen)

def Plugins(path, **kwargs):
	list = []
	list.append(PluginDescriptor(where=[PluginDescriptor.WHERE_SESSIONSTART, PluginDescriptor.WHERE_AUTOSTART], fnc=autostart, wakeupfnc=epgshare_init_shutdown))
	list.append(PluginDescriptor(name = ("EPG Share"), description = ("EPG Service for your VU+"), where = PluginDescriptor.WHERE_PLUGINMENU, fnc=main))
	return list
