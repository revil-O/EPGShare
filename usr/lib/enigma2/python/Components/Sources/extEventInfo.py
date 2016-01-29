from Components.PerServiceDisplay import PerServiceBase
from Components.Element import cached
from enigma import iPlayableService, iServiceInformation, eServiceReference, eEPGCache
from Source import Source

class extEventInfo(PerServiceBase, Source, object):
	NOW = 0
	NEXT = 1
	
	def __init__(self, navcore, now_or_next):
		Source.__init__(self)
		PerServiceBase.__init__(self, navcore, 
			{ 
				iPlayableService.evStart: self.gotEvent,
				iPlayableService.evUpdatedEventInfo: self.gotEvent,
				iPlayableService.evEnd: self.gotEvent
			}, with_event=True)
		self.now_or_next = now_or_next
		self.epgQuery = eEPGCache.getInstance().lookupEventTime

	@cached
	def getEvent(self):
		service = self.navcore.getCurrentService()
		info = service and service.info()
		ret = info and info.getEvent(self.now_or_next)
		if not ret and info:
			refstr = info.getInfoString(iServiceInformation.sServiceref)
			ret = self.epgQuery(eServiceReference(refstr), -1, self.now_or_next and 1 or 0)
		if ret:
			print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>EVENTINFO GOT NOW NEXT EVENT<<<<<<<<<<<<<<<<<<<<<<<<<<<<<"
			event_id = ret.getEventId()
			print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>EVENTINFO NOW NEXT EVENT ID: %s<<<<<<<<<<<<<<<<<<<<<<<<<<" % str(event_id)
			print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>EVENTINFO LOOK UP IN PRIVATE_UPDATE CACHE<<<<<<<<<<<<<<<<<<<<<<<<<<<<<"
			retext = eEPGCache.getInstance().lookupEventId(eServiceReference(info.getInfoString(iServiceInformation.sServiceref)), event_id)
			if not retext is None:
				print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>EVENTINFO RESULT IN PRIVATE_UPDATE CACHE<<<<<<<<<<<<<<<<<<<<<<<<<<<<<"
				if str(retext.getExtraEventData()) != "":
					print "FOUND EXTRADATA IN PRIVATE_UPDATE EVENT"
					print str(retext.getExtraEventData())
					return retext
		return ret

	event = property(getEvent)

	def gotEvent(self, what):
		if what == iPlayableService.evEnd:
			self.changed((self.CHANGED_CLEAR,))
		else:
			self.changed((self.CHANGED_ALL,))

	def destroy(self):
		PerServiceBase.destroy(self)
		Source.destroy(self)

