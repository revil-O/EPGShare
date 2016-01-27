# -*- coding: utf-8 -*-
from Screens.Screen import Screen
from Screens.Setup import SetupSummary
from Screens.MessageBox import MessageBox
from Components.ConfigList import ConfigList, ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSelection, ConfigClock, ConfigSubsection, ConfigYesNo, ConfigSubDict, ConfigNothing, ConfigInteger, configfile
from Components.ServiceEventTracker import ServiceEventTracker
from Components.ActionMap import ActionMap
from Components.Label import Label
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
from urllib import quote, unquote_plus, unquote, urlencode, time
import base64
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from datetime import datetime, timedelta
from os.path import splitext, basename
from urlparse import urlparse
import skin
updatethread = None

config.plugins.epgShare = ConfigSubsection()
config.plugins.epgShare.auto = ConfigYesNo(default=True)
config.plugins.epgShare.hours = ConfigInteger(12, (1, 24))
config.plugins.epgShare.onstartup = ConfigYesNo(default=False)
config.plugins.epgShare.useimprover = ConfigYesNo(default=False)
config.plugins.epgShare.onstartupdelay = ConfigInteger(2, (1, 60))
config.plugins.epgShare.debug = ConfigYesNo(default=False)
config.plugins.epgShare.autorefreshtime = ConfigClock(default=6 * 3600)
config.plugins.epgShare.starttimedelay = ConfigInteger(default=10)
config.plugins.epgShare.titleSeasonEpisode = ConfigYesNo(default=False)
config.plugins.epgShare.titleDate = ConfigYesNo(default=False)
config.plugins.epgShare.sendTransponder = ConfigYesNo(default=False)

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
				l.append({'ref': str(serviceref), 'time': lasteventtime})
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
	if config.plugins.epgShare.debug.value:
		color_print = "\033[92m"
		color_end = "\33[0m"
		print color_print + "[EPG Share] " + str(stringvalue) + color_end

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
			colorprint("Auto EPG Update startet in %s std. um %s Uhr." % (str(config.plugins.epgShare.hours.value), str(now)))
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
		epgDown = epgShareDownload(self.session)
		epgDown.start()


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

	def __init__(self, session, callback=False):
		self.session = session
		self.callback = callback
		self.callback_infos = None
		self.isRunning = False
		self.epgcache = eEPGCache.getInstance()
		threading.Thread.__init__(self)

	def setCallback(self, callback_infos):
		self.callback_infos = callback_infos

	def msgCallback(self, txt):
		if self.callback_infos:
			self.callback_infos(txt)

	def stop(self):
		self.isRunning = False

	def run(self):
		self.isRunning = True
		colorprint("Hole EPG Daten vom Server")
		self.msgCallback("Hole EPG Daten vom Server.. Bitte warten")
		requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
		refs = {}
		if config.plugins.epgShare.useimprover.value:
			refs['refs'] = getRefListJson(getextradata=True)
			data = requests.post("http://timeforplanb.linevast-hosting.in/download_epg_ext.php", data=json.dumps(refs), timeout=180).text
		else:
			refs['refs'] = getRefListJson(getextradata=False)
			data = requests.post("http://timeforplanb.linevast-hosting.in/download_epg.php", data=json.dumps(refs), timeout=180).text
		if re.search('EPG ist aktuell', data, re.S|re.I):
			events = None
			if self.callback:
				self.msgCallback("EPG ist aktuell.")
				self.msgCallback("EPG Download beendet.")
		else:
			try:
				events = json.loads(data)['events']
				colorprint("Antwort vom Server")
				colorprint("Events: %d" % len(events))
			except Exception, ex:
				events = None
				colorprint("Fehler beim EPG Download !!!")
				if self.callback:
					self.msgCallback("Fehler beim EPG Download %s" % str(ex))
		if events is not None:
			reflist = getRefList()
			if len(reflist) > 0:
				last_channel_name = ''
				last_channel_ref = ''
				channels = []
				events_list = []
				count_refs = len(events)
				for event in events:
					if not self.isRunning:
						break
					if str(event['channel_ref']) in reflist:
						if str(event['channel_ref']) not in channels:
							channels.append(str(event['channel_ref']))
						if last_channel_ref in [str(event['channel_ref']), '']:
							if event['extradata'] is None:
								events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), str(event['handlung']), 0, long(event['event_id'])),)
							else:
								title = str(event['title'])
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
											
								events_list.append((long(event['starttime']), int(event['duration']), str(title), str(event['subtitle']), "%s \n<x>%s</x>" % (str(event['handlung']), str(event['extradata'])), 0, long(event['event_id'])),)
						else:
							colorprint("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
							if self.callback:
								self.msgCallback("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
							self.epgcache.importLockedEventswithID(last_channel_ref, events_list)
							events_list = []
							if event['extradata'] is None:
								events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), str(event['handlung']), 0, long(event['event_id'])),)
							else:
								title = str(event['title'])
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

								events_list.append((long(event['starttime']), int(event['duration']), str(title), str(event['subtitle']), "%s <x>%s</x>" % (str(event['handlung']), str(event['extradata'])), 0, long(event['event_id'])),)
						last_channel_ref = str(event['channel_ref'])
						last_channel_name = str(event['channel_name'])
						count_refs += 1

				if int(count_refs) == int(count_refs):
					self.epgcache.importLockedEventswithID(last_channel_ref, events_list)
					colorprint("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
					colorprint("EPG Download beendet.")
					if self.callback:
						self.msgCallback("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
						self.msgCallback("EPG Download beendet.")
			else:
				colorprint("Keine reflist vorhanden.")
		self.isRunning = False


class epgShareUploader(threading.Thread):

	def __init__(self, session):
		self.session = session
		self.stopped = False
		self.channelqueue = Queue()
		self.queuelist = []
		self.epgcache = eEPGCache.getInstance()
		threading.Thread.__init__(self)

	def stopme(self):
		self.stopped = True

	def run(self):
		colorprint("Grab Channel EPG")
		while not self.stopped:
			if not self.channelqueue.empty():
				while not self.channelqueue.empty():
					channel_ref = None
					try:
						info = self.channelqueue.get()
						if info:
							(channel_name, channel_ref) = info
							colorprint("%s %s" % (channel_name, channel_ref))
							test = [ 'IBDTSEv', (channel_ref, 0, time.time(), -1)]
							dvb_events = []
							count_dvb_events = 0
							dvb_events_real = []
							count_dvb_events_real = 0
							dvb_events = self.epgcache.lookupEvent(test)
							count_dvb_events = len(dvb_events)
							time.sleep(1)
							colorprint("Checking Eventcount")
							while len(self.epgcache.lookupEvent(test)) > count_dvb_events:
								colorprint("Eventcount is increasing")
								colorprint("Waiting 1 Second")
								time.sleep(1)
								dvb_events = self.epgcache.lookupEvent(test)
								count_dvb_events = len(dvb_events)
							colorprint("Eventcount is not increasing... not Channelupdate running")
							dvb_events_real = filter(lambda x: str(x[6]) in ['NOWNEXT', 'SCHEDULE', 'PRIVATE_UPDATE'], dvb_events)
							count_dvb_events_real = str(len(dvb_events_real))
							colorprint("Count %s from %s Events" % (str(count_dvb_events_real), str(count_dvb_events)))
							if len(dvb_events_real) > 0:
								postdata = []
								for event in dvb_events_real:
									(event_id, starttime, duration, title, subtitle, handlung, import_type) = event
									ev = {}
									ev['event_id'] = str(event_id)
									ev['addtime'] = str(int(time.time()))
									ev['channel_name'] = str(channel_name.replace('\xc2\x86', '').replace('\xc2\x87', ''))
									ev['channel_ref'] = str(channel_ref)
									ev['starttime'] = str(starttime)
									ev['duration'] = str(duration)
									ev['title'] = str(title)
									ev['subtitle'] = str(subtitle)
									ev['handlung'] = str(handlung)
									postdata.append(ev)
								requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
								post = {'events': json.dumps(postdata)}
								colorprint(str(requests.post('http://timeforplanb.linevast-hosting.in/import_epg.php', data=post, timeout=10).text))

					except Exception, ex:
						colorprint("Grab Channel EPG - Error: %s" % str(ex))
					if channel_ref:
						self.queuelist.remove(channel_ref)
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
		self.epgUp.stopme()
		self.epgUp = None

	def delaytimer(self):
		self.Timer.stop()
		if config.plugins.epgShare.sendTransponder.value:
			cur_ref = self.session.nav.getCurrentlyPlayingServiceReference()
			pos = service_types_tv.rfind(':')
			refstr = '%s (channelID == %08x%04x%04x) && %s ORDER BY name' % (service_types_tv[:pos+1],
								cur_ref.getUnsignedData(4),
								cur_ref.getUnsignedData(2),
								cur_ref.getUnsignedData(3),
								service_types_tv[pos+1:])
			for (serviceref, servicename) in getServiceList(refstr):
				self.epgUp.addChannel([servicename, serviceref])
		else:
			self.epgUp.addChannel(self.getChannelNameRef())


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
		self.isEpgDownload = False

	def callbacks(self, text):
		if text == "EPG Download beendet.":
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
		self.list = []
		self.isEpgDownload = True
		self.epgDown = epgShareDownload(self.session, True)
		self.epgDown.setCallback(self.callbacks)
		self.epgDown.start()

	def keyCancel(self):
		if self.isEpgDownload:
			self.isEpgDownload = False
			self.epgDown.stop()
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
		self["actions"]  = ActionMap(["OkCancelActions", "ShortcutActions", "WizardActions", "ColorActions", "SetupActions", "NumberActions", "MenuActions", "EPGSelectActions"], {
			"cancel":	self.keyCancel,
			"red"	:	self.keyCancel,
			"green"	:	self.keySave,
			"left"	:	self.keyLeft,
			"right"	:	self.keyRight
		}, -1)

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
		self.list.append(getConfigListEntry(_("Transponder EPG hochladen"), config.plugins.epgShare.sendTransponder))
		self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen"), config.plugins.epgShare.auto))
		if config.plugins.epgShare.auto.value:
			self.list.append(getConfigListEntry(_("Uhrzeit"), config.plugins.epgShare.autorefreshtime))
		self.list.append(getConfigListEntry(_("Beim Enigma2 start EPG automatisch vom Server holen"), config.plugins.epgShare.onstartup))
		if config.plugins.epgShare.onstartup.value:
			self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen nach x Minuten"), config.plugins.epgShare.onstartupdelay))
		self.list.append(getConfigListEntry(_("EPG mit Extradaten verbessern"), config.plugins.epgShare.useimprover))
		if config.plugins.epgShare.useimprover.value:
			self.list.append(getConfigListEntry(_("Season und Episode (S01E01) zum Sendungs-Titel hinzufügen"), config.plugins.epgShare.titleSeasonEpisode))
		self.list.append(getConfigListEntry(_("Debug Ausgabe aktivieren"), config.plugins.epgShare.debug))

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
		config.plugins.epgShare.auto.save()
		config.plugins.epgShare.autorefreshtime.save()
		config.plugins.epgShare.onstartup.save()
		config.plugins.epgShare.onstartupdelay.save()
		config.plugins.epgShare.titleSeasonEpisode.save()
		config.plugins.epgShare.useimprover.save()
		config.plugins.epgShare.sendTransponder.save()
		config.plugins.epgShare.debug.save()
		config.plugins.epgShare.save()
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
	global updateservice
	updateservice.close()
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
		# Hole EPG Daten vom Server beim e2 neustart mit delay
		if config.plugins.epgShare.onstartup.value:
			delayEpgDownload(session)
			delay_timer = delayEpgDownload.instance
			delay_timer.startTimer()

		# Auto EPG Update Timer
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
	list.append(PluginDescriptor(name = ("EPG Share"), description = ("EPG Service for your VU+"), where = PluginDescriptor.WHERE_PLUGINMENU, fnc = main))
	return list
