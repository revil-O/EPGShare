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
			l.append(serviceref)
	return l


def getRefListJson(getextradata=False):
	l = []
	tvbouquets = getTVBouquets()
	for bouquet in tvbouquets:
		bouquetlist = getServiceList(bouquet[0])
		for (serviceref, servicename) in bouquetlist:
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


def getWebChannels():
	channeldb = {}
	url = str(base64.b64decode('aHR0cDovL2NhcGkudHZtb3ZpZS5kZS92MS9jaGFubmVscy9ib3VxdWV0LzQxMDc0NTE/ZmllbGRzPWNoYW5uZWxJZCxjaGFubmVsTG9uZ05hbWUsY2hhbm5lbFNob3J0TmFtZQ=='))
	headers = json.loads(str(base64.b64decode('eyJVc2VyLUFnZW50IjogIlRWIE1vdmllLzEyMiAoaVBob25lOyBpT1MgOS4xOyBTY2FsZS8yLjAwKSIsICJBY2NlcHQtTGFuZ3VhZ2UiOiAiZGUtREU7cT0xIiwgIkhvc3QiOiAiY2FwaS50dm1vdmllLmRlIiwgIlgtTmV3UmVsaWMtSUQiOiAiWEFZQlVWQmFHd1FHVVZoUkFBUT0ifQ==')))
	program = json.loads(requests.get(url, headers=headers).text)
	for channels in program:
		for each in channels['channels']:
			channelShortName = str(each['channelShortName']).lower().replace(' HD','').replace(' hd','').replace(' +','+')
			channelLongName = str(each['channelLongName']).lower().replace(' HD','').replace(' hd','').replace(' +','+')
			channel_id = str(each['channelId'])
			if channelLongName != "":
				if channelShortName != channelLongName:
					channeldb[channelLongName] = channel_id
			if channelShortName == "rtl ii":
				channeldb["rtlii"] = channel_id
				channeldb["rtl2"] = channel_id
			elif channelShortName == "unichan":
				channeldb["universal"] = channel_id
			elif channelShortName == "prosieben fun":
				channeldb["pro7 fun"] = channel_id
			elif channelShortName == "sat.1gold":
				channeldb["sat.1 gold"] = channel_id
			elif channelShortName == "rtl nitro":
				channeldb["rtlnitro"] = channel_id
				channeldb["rtl nitro"] = channel_id
			elif channelShortName == "b 3":
				channeldb["br nord"] = channel_id
				channeldb["br süd"] = channel_id
				channeldb["bayerisches fs nord"] = channel_id
				channeldb["bayerisches fs süd"] = channel_id
			elif channelShortName == "h 3":
				channeldb["hr-fernsehen"] = channel_id
			elif channelShortName == "rbb":
				channeldb["rbb brandenburg"] = channel_id
				channeldb["rbb berlin"] = channel_id
			elif channelShortName == "swr fernsehen":
				channeldb["swr rp"] = channel_id
				channeldb["swr bw"] = channel_id
				channeldb["swr fernsehen bw"] = channel_id
				channeldb["swr fernsehen rp"] = channel_id
			elif channelShortName == "ndr":
				channeldb["ndr fs sh"] = channel_id
				channeldb["ndr fs hh"] = channel_id
				channeldb["ndr fs mv"] = channel_id
				channeldb["ndr fs nds"] = channel_id
			elif channelShortName == "mdr":
				channeldb["mdr s-anhalt"] = channel_id
				channeldb["mdr sachsen"] = channel_id
				channeldb["mdr thüringen"] = channel_id
			elif channelShortName == "wdr":
				channeldb["wdr aachen"] = channel_id
				channeldb["wdr köln"] = channel_id
				channeldb["wdr dortmund"] = channel_id
				channeldb["wdr bielefeld"] = channel_id
				channeldb["wdr bonn"] = channel_id
				channeldb["wdr duisburg"] = channel_id
				channeldb["wdr essen"] = channel_id
				channeldb["wdr münster"] = channel_id
				channeldb["wdr siegen"] = channel_id
				channeldb["wdr wuppertal"] = channel_id
				channeldb["wdr düsseldorf"] = channel_id
			elif channelShortName == "zdf neo":
				channeldb["zdf_neo"] = channel_id
			elif channelShortName == "sonnenklar.tv":
				channeldb["sonnenklar tv"] = channel_id
			elif channelShortName == "national geographic":
				channeldb["natgeo"] = channel_id
				channeldb["national geographic"] = channel_id
			elif channelShortName == "eurosport":
				channeldb["eurosport 1"] = channel_id
				channeldb["eurosport deutschland"] = channel_id
			elif channelShortName == "sf 1":
				channeldb["srf eins"] = channel_id
			elif channelShortName == "sf 2":
				channeldb["srf zwei"] = channel_id
			elif channelShortName == "servustvd":
				channeldb["servustv deutschland"] = channel_id
				channeldb["servustv oesterreich"] = channel_id
			elif channelShortName == "ki.ka":
				channeldb["kika"] = channel_id
			elif channelShortName == "orf 1":
				channeldb["orf1"] = channel_id
			elif channelShortName == "fox":
				channeldb["fox serie"] = channel_id
				channeldb["fox"] = channel_id
			elif channelShortName == "orf 2":
				channeldb["orf2"] = channel_id
			elif channelShortName == "e! entertainment television":
				channeldb["e! entertainm."] = channel_id
			elif channelShortName == "nat geo wild":
				channeldb["nat geo wild"] = channel_id
				channeldb["natgeo wild"] = channel_id
			elif channelShortName == "puls 4":
				channeldb["puls 4 austria"] = channel_id
			elif channelShortName == "nat geo wild":
				channeldb["nat geo wild"] = channel_id
			elif channelShortName == "tnt film":
				channeldb["tnt film (tcm)"] = channel_id
				channeldb["tnt film"] = channel_id
			elif channelShortName == "axn":
				channeldb["axn"] = channel_id
				channeldb["axn action"] = channel_id
			elif channelShortName == "ard alpha":
				channeldb["ard-alpha"] = channel_id
			elif channelShortName == "discovery channel":
				channeldb["discovery"] = channel_id
				channeldb["discovery channel"] = channel_id
			elif channelShortName == "anixe":
				channeldb["anixe"] = channel_id
				channeldb["anixe sd"] = channel_id
			else:
				channeldb[channelShortName] = channel_id
	return channeldb


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
			now = str(datetime.now().strftime('%d.%m.%Y %H:%M:%S'))
			return
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
		if config.plugins.epgShare.useimprover.value:
			refs['refs'] = getRefListJson(getextradata=True)
			data = requests.post("http://timeforplanb.linevast-hosting.in/download_epg_ext.php", data=json.dumps(refs), timeout=60).text
		else:
			refs['refs'] = getRefListJson(getextradata=False)
			data = requests.post("http://timeforplanb.linevast-hosting.in/download_epg.php", data=json.dumps(refs), timeout=60).text
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
								events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), "%s \n<x>%s</x>" % (str(event['handlung']), str(event['extradata'])), 0, long(event['event_id'])),)
						else:
							colorprint("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
							if self.callback:
								self.msgCallback("Import %s Events for Channel: %s" % (len(events_list), last_channel_name))
							self.epgcache.importEventswithID(last_channel_ref, events_list)
							events_list = []
							if event['extradata'] is None:
								events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), str(event['handlung']), 0, long(event['event_id'])),)
							else:
								events_list.append((long(event['starttime']), int(event['duration']), str(event['title']), str(event['subtitle']), "%s <x>%s</x>" % (str(event['handlung']), str(event['extradata'])), 0, long(event['event_id'])),)
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
					print requests.post('http://timeforplanb.linevast-hosting.in/import_epg.php', data=post, timeout=10).text
		except:
			colorprint("Grab Channel EPG - Error")

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


class epgShareSetup(Screen, ConfigListScreen):
	skin = """
		<screen name="EPG Share Setup" title="EPG Share Setup" position="center,center" size="1280,720">
			<widget name="info" position="10,10" size="600,50" zPosition="5" transparent="0" halign="left" valign="top" font="Regular; 30" />
			<widget name="config" position="10,60" size="1260,120" font="Regular;22" textOffset="20,2" itemHeight="50" scrollbarMode="showOnDemand" scrollbarSliderBorderWidth="0" scrollbarWidth="5" scrollbarBackgroundPicture="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/scrollbarbg.png" />
			<widget name="list2" position="10,190" size="1260,480" scrollbarMode="showOnDemand" scrollbarSliderBorderWidth="0" scrollbarWidth="5" scrollbarBackgroundPicture="/usr/lib/enigma2/python/Plugins/Extensions/EpgShare/pic/scrollbarbg.png" />
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
		font, size = skin.parameters.get("EPGShareListFont", ('Regular', 20))
		self.itemheight = int(skin.parameters.get("EPGShareListItemHeight", (38,))[0])
		self.listwidth = int(skin.parameters.get("EPGShareListWidth", (1260,))[0])
		self.chooseMenuList.l.setFont(0, gFont(font, int(size)))
		self.chooseMenuList.l.setItemHeight(self.itemheight)
		self.chooseMenuList.selectionEnabled(False)
		self['info'] = Label(_("EPG Share Einstellung"))
		self['list2'] = self.chooseMenuList
		self['key_red'] = Label("Exit")
		self['key_green'] = Label(_("Speichern und verlassen"))
		self['key_yellow'] = Label(_("EPG vom Server laden"))
		self['key_blue'] = Label("")
		self.list = []
		self.list2 = []
		self.isEpgDownload = False
		self.createConfigList()
		ConfigListScreen.__init__(self, self.list)

	def createConfigList(self):
		self.list = []
		self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen"), config.plugins.epgShare.auto))
		if config.plugins.epgShare.auto.value:
			self.list.append(getConfigListEntry(_("Uhrzeit"), config.plugins.epgShare.autorefreshtime))
		self.list.append(getConfigListEntry(_("Beim Enigma2 start EPG automatisch vom Server holen"), config.plugins.epgShare.onstartup))
		if config.plugins.epgShare.onstartup.value:
			self.list.append(getConfigListEntry(_("EPG automatisch vom Server holen nach x Minuten"), config.plugins.epgShare.onstartupdelay))
		self.list.append(getConfigListEntry(_("EPG mit Extradaten verbessern"), config.plugins.epgShare.useimprover))
		self.list.append(getConfigListEntry(_("Debug Ausgabe aktivieren"), config.plugins.epgShare.debug))

	def changedEntry(self):
		self.createConfigList()
		self["config"].setList(self.list)

	def callbacks(self, text):
		if text == "EPG Download beendet.":
			self.isEpgDownload = False
		self.showInfo(text)

	def showInfo(self, text):
		try:
			self.list2.insert(0, text)
			self.chooseMenuList.setList(map(self.showList, self.list2))
		except:
			pass

	def showList(self, entry):
		return [entry,
			(eListboxPythonMultiContent.TYPE_TEXT, 10, 0, self.listwidth - 20, self.itemheight, 0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, entry)
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
		if self.isEpgDownload:
			self.epgDown.stop()
		self.close()


def epgshare_init_shutdown():
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
	session.open(epgShareSetup)

def Plugins(path, **kwargs):
	list = []
	list.append(PluginDescriptor(where=[PluginDescriptor.WHERE_SESSIONSTART, PluginDescriptor.WHERE_AUTOSTART], fnc=autostart, wakeupfnc=epgshare_init_shutdown))
	list.append(PluginDescriptor(name = ("EPG Share Setup"), description = ("EPG Service for your VU+"), where = PluginDescriptor.WHERE_PLUGINMENU, fnc = main))
	return list
