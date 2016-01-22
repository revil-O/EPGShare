# -*- coding: utf-8 -*-
from Screens.Screen import Screen
from Screens.Setup import SetupSummary
from Screens.MessageBox import MessageBox
from Components.ConfigList import ConfigList, ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSelection, ConfigSubsection, ConfigYesNo, ConfigSubDict, ConfigNothing, ConfigInteger, configfile
from Components.ServiceEventTracker import ServiceEventTracker
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Sources.StaticText import StaticText
from Components.MenuList import MenuList
from enigma import iPlayableService, iServiceInformation, eTimer, eConsoleAppContainer, gFont, addFont, loadPNG, eListboxPythonMultiContent, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER, RT_VALIGN_CENTER, eLabel, eWidget, eSlider, fontRenderClass, ePoint, eSize, eDBoxLCD, ePicLoad, gPixmapPtr, eEPGCache
from Plugins.Plugin import PluginDescriptor
from Queue import Queue, PriorityQueue

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

from requests.packages.urllib3.exceptions import InsecureRequestWarning

config.plugins.epgShare = ConfigSubsection()
config.plugins.epgShare.auto = ConfigYesNo(default = True)
config.plugins.epgShare.hours = ConfigInteger(12, (1,24))
config.plugins.epgShare.onstartup = ConfigYesNo(default = False)
config.plugins.epgShare.onstartupdelay = ConfigInteger(2, (1,60))

def getServiceList(ref):
	root = eServiceReference(str(ref))
	serviceHandler = eServiceCenter.getInstance()
	return serviceHandler.list(root).getContent("SN", True)

def getTVBouquets():
	return getServiceList(service_types_tv + ' FROM BOUQUET "bouquets.tv" ORDER BY bouquet')

def getRefList():
	list = []
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		for (serviceref, servicename) in bouquetlist:
			list.append(serviceref)
	return list

def getRefListJson():
	ret = {}
	list = []
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		for (serviceref, servicename) in bouquetlist:
			try:
				#lastevent = eEPGCache.getInstance().lookupEvent([ 'IBDTSEv', (str(serviceref), 0, time.time(), -1)])[-1]
				lastevent = eEPGCache.getInstance().lookupEvent(["IB",(str(serviceref), 3)])
				(event_id, starttime) = lastevent[0]
				lasteventtime = starttime
			except Exception, ex:
				lasteventtime = 0
			ref = {}
			ref['ref'] = str(serviceref)
			ref['time'] = lasteventtime
			list.append(ref)
	return list

def colorprint(stringvalue):
	color_print = "\033[92m"
	color_end = "\33[0m"
	print color_print + "[EPG Share] " + str(stringvalue) + color_end

class autoGetEpg():

	def __init__(self, session):
		assert not autoGetEpg.instance, "only one autoGetEp instance is allowed!"
		autoGetEpg.instance = self
		self.session = session
		self.timerRunning = False

	def startTimer(self):
		if config.plugins.epgShare.auto.value:
			self.Timer = eTimer()
			self.Timer.callback.append(self.getepg)
			self.Timer.start(3600000 * int(config.plugins.epgShare.hours.value))
			self.timerRunning = True
			colorprint("Auto EPG Update startet in %s std." % str(config.plugins.epgShare.hours.value))
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
		refs['refs'] = getRefListJson()
		data = requests.post("http://achansel.lima-city.de/download_epg.php", data=json.dumps(refs), timeout=60).text
		if re.search('EPG ist aktuell', data, re.S|re.I):
			events = None
			if self.callback:
				self.msgCallback("EPG ist aktuell.")
				self.msgCallback("EPG Download beendet.")
		else:
			try:
				#colorprint("Antwort vom Server: %s" % str(data))
				events = json.loads(data)['events']
				colorprint("Antwort vom Server")
				colorprint("Events: %d" % len(events))
			except:
				events = None
				colorprint("Fehler beim EPG Download !!!")
				if self.callback:
					self.msgCallback("Fehler beim EPG Download !!!")

		if events is not None:
			reflist = getRefList()
			if len(reflist) > 0:
				last_channel_name = ''
				last_channel_ref = ''
				channels = []
				events_list = []
				count_refs = len(events)
				# eventlist.append((long(start), long(dur), event_name, subtitle+" "+countryOfProduction+" "+productionYear, handlung+"\n"+extraData, 0, long(event_id)),)
				for event in events:
					if not self.isRunning:
						break
					if str(event['channel_ref']) in reflist:
						if str(event['channel_ref']) not in channels:
							channels.append(str(event['channel_ref']))
						if last_channel_ref in [str(event['channel_ref']), '']:
							events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), str(event['handlung']), 0, long(event['event_id'])),)
						else:
							colorprint("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
							if self.callback:
								self.msgCallback("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
							#self.epgcache.clearServiceEPG(eServiceReference(last_channel_ref))
							#self.epgcache.importEvents(last_channel_ref, events_list)
							self.epgcache.importEventswithID(last_channel_ref, events_list)
							events_list = []
							events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), str(event['handlung']), 0, long(event['event_id'])),)
						last_channel_ref = str(event['channel_ref'])
						last_channel_name = str(event['channel_name'])
						count_refs += 1
					
				if int(count_refs) == int(count_refs):
					self.epgcache.importEventswithID(last_channel_ref, events_list)
					colorprint("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
					colorprint("EPG Download beendet.")				
					if self.callback:
						self.msgCallback("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
						self.msgCallback("EPG Download beendet.")
					#self.epgcache.clearServiceEPG(eServiceReference(last_channel_ref))
					#self.epgcache.importEvents(last_channel_ref, events_list)
					
			else:
				colorprint("Keine reflist vorhanden.")
		self.isRunning = False

class epgShareUploader(threading.Thread):

	def __init__(self, session):
		self.session = session
		self.epgcache = eEPGCache.getInstance()
		threading.Thread.__init__(self)

	def run(self):
		colorprint("Grab Channel EPG")
		try:
			info = self.getChannelNameRef()
			if info is not None:
				(channel_name, channel_ref) = info
				colorprint("%s %s" % (channel_name, channel_ref))
				test = [ 'IBDTSEv', (channel_ref, 0, time.time(), -1) ]
				dvb_events = []
				count_dvb_events = 0
				dvb_events_real = []
				count_dvb_events_real = 0
				dvb_events = self.epgcache.lookupEvent(test)
				count_dvb_events = str(len(dvb_events))
				dvb_events_real = filter(lambda x: str(x[6]) in ['NOWNEXT', 'SCHEDULE'], dvb_events)
				count_dvb_events_real = str(len(dvb_events_real))
				colorprint("Count %s from %s Events" % (count_dvb_events_real, count_dvb_events))
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
					print requests.post('http://achansel.lima-city.de/import_epg.php', data=post, timeout=10).text
		except:
			colorprint("Grab Channel EPG - Error")

	def getChannelNameRef(self):
		service = self.session.nav.getCurrentService()
		service_ref = self.session.nav.getCurrentlyPlayingServiceReference().toString()
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

	def delaytimer(self):
		self.Timer.stop()
		epgUp = epgShareUploader(self.session)
		epgUp.start()

class epgSahreSetup(Screen, ConfigListScreen):
	skin = """
		<screen name="EPG Share Setup" title="EPG Share Setup" position="center,center" size="1280,720">
			<widget name="info" position="10,10" size="600,50" zPosition="5" transparent="0" halign="left" valign="top" font="Regular; 30" />
			<widget name="config" position="10,60" size="1270,120" font="Regular;22" textOffset="20,2" itemHeight="30" scrollbarMode="showOnDemand" scrollbarSliderBorderWidth="0" scrollbarWidth="5" scrollbarBackgroundPicture="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/scrollbarbg.png" />
			<widget name="list2" position="10,190" size="1270,480" font="Regular;22" textOffset="20,7" itemHeight="30" scrollbarMode="showOnDemand" scrollbarSliderBorderWidth="0" scrollbarWidth="5" scrollbarBackgroundPicture="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/scrollbarbg.png" />
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
			"yellow":	self.keyRun,
			"left"	:	self.keyLeft,
			"right"	:	self.keyRight,
			"nextBouquet" : self.listUP,
			"prevBouquet" : self.listDown,
		}, -1)

		self.chooseMenuList = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
		self.chooseMenuList.l.setFont(0, gFont('Regular', 22))
		self.chooseMenuList.l.setItemHeight(30)
		
		self['info'] = Label("EPG Share Einstellung")
		self['list2'] = self.chooseMenuList
		self['key_red'] = Label("Exit")
		self['key_green'] = Label("Save and Exit")
		self['key_yellow'] = Label("Hole EPG vom Server")
		self['key_blue'] = Label("")
		self.list = []
		self.list2 = []
		self.isEpgDownload = False
		self.createConfigList()
		ConfigListScreen.__init__(self, self.list)

	def createConfigList(self):
		self.list = []
		self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen:"), config.plugins.epgShare.auto))
		if config.plugins.epgShare.auto.value:
			self.list.append(getConfigListEntry(_("Alle x Stunden:"), config.plugins.epgShare.hours))
		self.list.append(getConfigListEntry(_("Beim Enigma2 start EPG automatisch vom Server holen:"), config.plugins.epgShare.onstartup))
		if config.plugins.epgShare.onstartup.value:
			self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen nach x Minuten:"), config.plugins.epgShare.onstartupdelay))

	def changedEntry(self):
		self.createConfigList()
		self["config"].setList(self.list)

	def callbacks(self, text):
		if text == "EPG Download beendet.":
			self.isEpgDownload = False
			print "setze download FALSE"
		self.showInfo(text)

	def showInfo(self, text):
		#self.list2.append((text))
		self.list2.insert(0, text)
		self.chooseMenuList.setList(map(self.showList, self.list2))

	def showList(self, entry):
		return [entry,
			(eListboxPythonMultiContent.TYPE_TEXT, 0, 0, 1270, 30, 0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, entry)
			]

	def keyRun(self):
		self.list2 = []
		self.isEpgDownload = True
		self.epgDown = epgShareDownload(self.session, True)
		self.epgDown.setCallback(self.callbacks)
		self.epgDown.start()

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.changedEntry()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.changedEntry()

	def listUP(self):
		self['list2'].up()
		
	def listDown(self):
		self['list2'].down()

	def keySave(self):
		global bg_timer
		config.plugins.epgShare.auto.save()
		config.plugins.epgShare.hours.save()
		config.plugins.epgShare.onstartup.save()
		config.plugins.epgShare.onstartupdelay.save()
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
		if self.isEpgDownload:
			self.epgDown.stop()
		self.close()

def autostart(reason, **kwargs):
	if "session" in kwargs:
		session = kwargs["session"]

		# Starte Upload Service
		epgShare(session)

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
	session.open(epgSahreSetup)

def Plugins(path, **kwargs):
	list = []
	list.append(PluginDescriptor(where=[PluginDescriptor.WHERE_SESSIONSTART, PluginDescriptor.WHERE_AUTOSTART], fnc=autostart))
	list.append(PluginDescriptor(name = ("EPG Share Setup"), description = ("EPG Service for your VU+"), where = PluginDescriptor.WHERE_PLUGINMENU, fnc = main))
	return list
