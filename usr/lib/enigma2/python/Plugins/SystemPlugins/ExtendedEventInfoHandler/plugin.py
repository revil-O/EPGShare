# -*- coding: utf-8 -*-
from Plugins.Plugin import PluginDescriptor

def sessionstart(session, **kwargs):
	from Components.Sources.extEventInfo import extEventInfo
	session.screen["extEvent_Now"] = extEventInfo(session.nav, extEventInfo.NOW)
	session.screen["extEvent_Next"] = extEventInfo(session.nav, extEventInfo.NEXT)

def Plugins(**kwargs):
	return [PluginDescriptor(where=[PluginDescriptor.WHERE_SESSIONSTART], fnc=sessionstart)]
