from Components.Converter.Converter import Converter
from Components.Element import cached
import json
import HTMLParser
class ExtraEventData(Converter, object):
	def __init__(self, type):
		Converter.__init__(self, type)
		self.type = str(type).split()
	
	@cached
	def getText(self):
		h = HTMLParser.HTMLParser()
		if self.type != '':
			rets = []
			try:
				print "EXTRAEVENTDATA: %s" % str(self.source.text)
				values = json.loads(self.source.text)
				for field in self.type:
					if field == "TITLE":
						if str(values['title']) != '':
							rets.append(str(values['title']))
					elif field == "SUBTITLE":
						if str(values['subtitle']) != '':
							rets.append(str(values['subtitle']))
					elif field == "SERIESINFO":
						if str(values['season']) != "" and str(values['episode']) != "":
							rets.append("S%sE%s" % (str(values['season']).zfill(2), str(values['episode']).zfill(2)))
					elif field == "CATEGORY":
						if str(values['categoryName']) != '':
							rets.append(str(values['categoryName']))
					elif field == "GENRE":
						if str(values['genre']) != '':
							rets.append(str(values['genre']))
					elif field == "AGE":
						if str(values['ageRating']) != '':
							rets.append(str(values['ageRating']))
					elif field == "YEAR":
						if str(values['year']) != '':
							rets.append(str(values['year']))
					elif field == "COUNTRY":
						if str(values['country']) != '':
							rets.append(str(values['country']))
				sep = " %s " % str(h.unescape('&#xB7;'))
				ret = sep.join(rets)
			except Exception, ex:
				ret = ""
				print "EXRTADATACONVERTER ERROR: %s" % str(ex)
		return  ret
		
	text = property(getText)