# -*- coding: utf-8 -*-
from config import config
import urllib
import re
from pyquery import PyQuery as pq
import time

from mysql import mysql
import translator
import utf8

class word(object):
	"""Encapsulates a word to get all the information about it"""
	
	def __init__(self, word):
		self.word = word
		self.verb = canoo(word)
		
		if (self.isVerb() and self.verb.exists()):
			self.translations = cache(self.verb.get(unknownHelper = True)[0]["full"])
		else:
			self.translations = cache(word)
	
	def exists(self):
		return self.translations.exists() or self.verb.exists()
	
	def get(self):
		return self.translations.get()
	
	def isAdjAdv(self):
		return self.__isA("adjadv")
	
	def isNoun(self):
		return self.__isA("noun")
	
	def isVerb(self):
		return self.verb.exists()
		
	def __isA(self, pos):
		words = self.translations.get()
		if (len(words) == 0):
			return False
		
		return bool(len([w for w in words if w["pos"] == pos]) > 0)

class internetInterface(object):
	"""
	Useful for things that hit the internet and store results from the queries in the local
	database.
	"""
	
	def __init__(self, word):
		self.word = word
		self.db = mysql.getInstance()
		self.hitInternet = False
		self.searchRan = False
		self.words = dict()

class cache(internetInterface):
	"""
	Caches the translation responses from the German-English dictionary; if the word is not found,
	it will attempt to look it up.
	"""
	
	def get(self, pos = "all"):
		self.__search()
		
		if (pos in ['adjadv', 'noun', 'verb']):
			return [t for t in self.words if t["pos"] == pos]
		
		return self.words
	
	def exists(self):
		self.__search()
		return len(self.words) > 0
	
	def __search(self):
		if (self.searchRan):
			return
		
		self.searchRan = True
		
		words = self.db.query("""
			SELECT * FROM `leoWords`
			WHERE
				`en`=%s
				OR
				`de`=%s
			;
		""", (self.word, self.word))
		
		if (type(words) != tuple):
			words = self.__scrapeLeo()
			self.__stashResults(words)
		
		if (len(words) > 0):
			self.words = words
	
	def __scrapeLeo(self):
		if (self.hitInternet):
			return
		
		self.hitInternet = True
		
		#before we do anything, make sure we haven't already searched for this and failed
		failed = self.db.query("""
			SELECT 1 FROM `failedSearches`
			WHERE
				`search`=%s
				AND
				`source`="leo"
		""", (self.word))
		
		if (failed):
			return []
		
		#now go and hit leo for the results
		d = pq(url='http://dict.leo.org/ende?lp=ende&lang=de&searchLoc=0&cmpType=relaxed&sectHdr=on&spellToler=on&search=%s&relink=on' % urllib.quote(self.word))
		rows = []
		for row in d.find("tr[valign=top]"):
			#extended translations
			enExt = pq(row[1]).text()
			deExt = pq(row[3]).text()
			
			#simplified translations
			en = self.__cleanWord(pq(row[1]))
			de = self.__cleanWord(pq(row[3]))
			
			if (self.__isWord(en, de)):
				rows.append(dict(
					en = en,
					de = de,
					enExt = enExt,
					deExt = deExt,
					pos = self.__pos(enExt, deExt)
				))

		return rows
	
	def __stashResults(self, words):
		if (len(words) == 0):
			#nothing was found, record a failed search so we don't do it again
			self.db.insert("""
				INSERT IGNORE INTO `failedSearches`
				SET
					`search`=%s,
					`source`="leo"
				;
			""", (self.word))
		else:
			for w in words:
				self.db.insert("""
					INSERT IGNORE INTO `leoWords`
					SET
						`en`=%s,
						`de`=%s,
						`enExt`=%s,
						`deExt`=%s,
						`pos`=%s
					;
				""", (
					w["en"],
					w["de"],
					w["enExt"],
					w["deExt"],
					w["pos"]
					)
				)
			
	def __isWord(self, en, de):
		"""Given a word, tests if it is actually the word we are looking for.
		
		Online, there will be some definitions like this (eg. for "test"):
			test - to pass a test, to carry out a test, and etc
		
		We are only concerned with the actual word, "test", so we ignore all the others."""
		
		word = self.word.lower()
		
		#i'm allowing three spaces before i throw a word as out invalid
		if (len(en.strip().split(" ")) > 2 or len(de.strip().split(" ")) > 2):
			return False
		
		if (en.lower() == word or de.lower() == word):
			return True
		
		return False
	
	def __pos(self, enExt, deExt):
		de = deExt
		en = enExt
		if (en.find("prep.") >= 0):
			pos = "prep"
		elif (en.find("to ") >= 0):
			pos = "verb"
		elif (de.find("der") >= 0 or de.find("die") >= 0 or de.find("das") >= 0):
			pos = "noun"
		else:
			pos = "adjadv"
		
		return pos
	
	#words that need a space after them in order to be removed
	spaceWords = ["der", "die", "das", "to", "zu", "zur", "zum"]
	
	#words to always remove
	unspacedWords = ["sth.", "etw.", "jmdm.", "jmdn.", "jmds.", "so.", "adj."]
	
	#words that can have a space before or after to remove
	#and stupid python 2.* requires unicode strings for anything fun...ugh
	egalSpace = ["bis", "durch", "entlang", u"für", "gegen", "ohne", "um", "aus", "ausser",
		u"außer", "bei", "beim", u"gegenüber", "mit", "nach", "seit", "von", "zu",
		"an", "auf", "hinter", "in", "neben", u"über", "unter", "vor", "zwischen",
		"statt", "anstatt", "ausserhalb", u"außerhalb", "trotz", u"während", "wegen"
	]
	
	def __cleanWord(self, word):
		"""Pulls the bloat out of the definitions of words so that we're just left with a word"""
		
		#clean up the word if we grabbed it from the web
		if (type(word) == pq):
			#remove the small stuff, we don't need it
			#be sure to clone the word so that we're not affecting other operations done on it in other functions
			word.clone().find("small").remove()
		
			#get to text for further string manipulations
			word = word.text()
		
		#remove the stuff that's in the brackets (usually just how the word is used / formality / time / etc)
		word = re.sub(r'(\[.*\])', "", word)
		
		#remove anything following a dash surrounded by spaces -- this does not remove things that END in dashes
		loc = word.find(" -")
		if (loc >= 0):
			word = word[:loc]
		
		#get rid of the extra words that aren't needed but that could possibly conflict with strings inside other words (so give them a trailing space)
		for w in self.spaceWords:
			word = word.replace(w + " ", "").strip()
		
		#and the words that aren't needed and can't conflict with other words
		for w in self.unspacedWords:
			word = word.replace(w, "").strip()
		
		#now, let's lose the hanging words that just get in the way
		for w in self.egalSpace:
			word = word.replace(w + " ", "").replace(" " + w, "").strip()
		
		#remove anything following a "|"
		loc = word.find("|")
		if (loc >= 0):
			word = word[:loc]
		
		return word.strip("/").strip("-").strip()
	
class canoo(internetInterface):
	"""
	Caches all the verb information from Canoo; if no information is found, then it goes to canoo
	to find it.
	"""
	
	#the last time a canoo page was loaded
	lastCanooLoad = -1
	
	#seems to load fine after a second
	canooWait = 1
	
	#external definitions for the helper verbs
	helper = "haben"
	helperHaben = "haben"
	helperSein = "sein"
	
	def exists(self):
		self.__search()
		return len(self.words) > 0
	
	def getStem(self, word = None):
		"""Gets the stem of the verb."""
		
		if (word == None):
			ret = self.word
		else:
			ret = word
		
		if (ret.find(" ") >= 0):
			ret = ret.split(" ")[0]
		
		#start by removing any endings we could have when conjugated
		for end in ("est", "et", "en", "e", "st", "t"): #order matters in this list
			if (ret[len(ret) - len(end):] == end): #remove the end, but only once (thus, rstrip doesn't work)
				ret = ret[:len(ret) - len(end)]
				break
		
		return ret
	
	def get(self, unknownHelper = False, returnAll = False):
		"""
		Gets the verb forms with their helpers.
		-unknownHelper = the helper is not known, just return the first matching with any helper
		-returnAll = give me everything you have
		"""
		
		self.__search()
		
		if (returnAll):
			return self.words
		
		if (self.helper not in self.words.keys()):
			if (unknownHelper and len(self.words.keys()) > 0): #if we don't know the helper, return whatever we have
				return self.words[self.words.keys()[0]]
			
			#the list was empty, just die
			return ()
		
		return self.words[self.helper]
	
	def __search(self):
		"""
		Attempts to get the information from the database.  If it fails, then it hits the internet as
		a last resort, unless it is stated in the database that the search failed, in which case there
		is no need to hit the internet.
		"""
		
		if (self.searchRan):
			return
			
		self.searchRan = True
		
		stem = self.getStem()
		
		if (config.getboolean("deutsch", "enable.cache")):
			rows = self.db.query("""
				SELECT * FROM `canooWords`
				WHERE
					`full`=%s
					OR
					`stem`=%s
					OR
					`preterite`=%s
					OR
					`perfect`=%s
					OR
					`third`=%s
					OR
					`subj2`=%s
				;
			""", (self.word, stem, stem, stem, stem, stem))
			
			if (type(rows) != tuple):
				rows = self.__scrapeCanoo()
				self.__stashResults(rows)
			
			if (len(rows) > 0):
				#run through all the returned rows
				for r in rows:
					tmp = dict()
					if (r.has_key("id")): #remove the id row, we don't need it
						del r['id'] 
					
					#build up our temp list of column names (k) associated with words (v)
					for k, v in r.iteritems():
						tmp[k] = v
					
					if (not r["hilfsverb"] in self.words.keys()):
						self.words[r["hilfsverb"]] = []
					
					#save the word to our helper verb table
					self.words[r["hilfsverb"]].append(tmp)
			else:
				self.words = []
	
	def __scrapeCanoo(self):
		"""Grabs the inflections of all verbs that match the query"""
		
		if (self.hitInternet):
			return []
		
		self.hitInternet = True
		
		#first, check to see if we've failed on this search before
		failed = self.db.query("""
			SELECT 1 FROM `failedSearches`
			WHERE
				`search`=%s
				AND
				`source`="canoo"
		""", (self.word))
		
		if (failed):
			return []
		
		#hit the page
		url = unicode(self.word)
		for c, r in zip([u'ä', u'ö', u'ü', u'ß'], ['ae', 'oe', 'ue', 'ss']): #sadiofhpaw8oenfasienfkajsdf! urls suck
			url = url.replace(c, r)
		
		p = self.__getCanooPage('http://www.canoo.net/services/Controller?dispatch=inflection&input=%s' % urllib.quote(url.encode("utf-8")))
		
		#setup our results
		ret = []

		#canoo does some different routing depending on the results for the word, so let's check what page
		#we recieved in order to verify we perform the right action on it
		if (p.find("h1.Headline").text() != u"Wörterbuch Wortformen"):
			if(p.find("h1.Headline").text().find(u"Keine Einträge gefunden") >= 0
				or
				p.find("div#Verb").text() == None
			):
				pass #nothing found
			else:
				ret.append(self.__processPage(p))
		else:
			#grab the links
			links = [l for l in p.find("td.contentWhite a[href^='/services/Controller?dispatch=inflection']") if pq(l).text().find("Verb") >= 0]
			
			#append all the information from all the pages we found in the search
			for a in links:
				ret.append(self.__scrapePage(a))
		
		return ret
			
	def __scrapePage(self, a):
		"""Scrapes a page on canoo.net to find the verb forms"""
		
		#scrape the page with information about the verb
		url = pq(a).attr.href
		page = self.__getCanooPage('http://www.canoo.net/' + url)
		
		return self.__processPage(page)
	
	def __processPage(self, page):
		#just use "q" for a basic "query" holder
		
		#find the table holding the present-forms of the verb
		q = page.find("div#Presens div table tr")
		stem = self.getStem(q.eq(3).find("td").eq(1).text())
		third = self.getStem(q.eq(5).find("td").eq(1).text())
		
		#find the preterite
		q = page.find("div#Praeteritum div table tr")
		preterite = self.getStem(q.eq(3).find("td").eq(1).text())
		subj2 = self.getStem(q.eq(3).find("td").eq(3).text())
		
		#find the perfekt
		q = page.find("div#Perfect table tr")
		perfect = self.getStem(q.eq(4).find("td").eq(2).text())
		
		#get the full form of the verb
		full = page.find("h1.Headline i").text()

		#attempt to get the helper verb
		helper = self.helperHaben if (page.find("div#Verb").prevAll("table").text().find("Hilfsverb: haben") != -1) else self.helperSein
		
		return dict(full = full, hilfsverb = helper, stem = stem, preterite = preterite, perfect = perfect, third = third, subj2 = subj2)
	
	def __getCanooPage(self, url):
		"""Canoo has mechanisms to stop scraping, so we have to pause before hit the links too much"""
		
		#make sure these are python-"static" (*canoo* instead of *self*)
		if (canoo.lastCanooLoad != -1 and ((time.clock() - self.lastCanooLoad) < canoo.canooWait)):
			time.sleep(canoo.canooWait - (time.clock() - self.lastCanooLoad))
			
		canoo.lastCanooLoad = time.clock()
		return pq(url)
	
	def __stashResults(self, res):
		if (len(res) == 0):
			#nothing was found, record a failed search so we don't do it again
			self.db.insert("""
				INSERT IGNORE INTO `failedSearches`
				SET
					`search`=%s,
					`source`="canoo"
				;
			""", (self.word))
		else:
			#we found some stuff, so save it to the db
			for inflect in res:
				self.db.insert("""
					INSERT IGNORE INTO `canooWords`
					SET
						`full`=%s,
						`stem`=%s,
						`preterite`=%s,
						`hilfsverb`=%s,
						`perfect`=%s,
						`third`=%s,
						`subj2`=%s
					;
				""", (
					inflect["full"],
					inflect["stem"],
					inflect["preterite"],
					inflect["hilfsverb"],
					inflect["perfect"],
					inflect["third"],
					inflect["subj2"]
					)
				)