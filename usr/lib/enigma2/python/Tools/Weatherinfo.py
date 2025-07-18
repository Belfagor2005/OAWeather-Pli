# -*- coding: utf-8 -*-

#########################################################################################################
#                                                                                                       #
#  Weatherinfo for openATV is a multiplatform tool (runs on Enigma2 & Windows and probably many others)  #
#  Coded by Mr.Servo @ openATV and jbleyel @ openATV (c) 2022                                           #
#  Learn more about the tool by running it in the shell: "python Weatherinfo.py -h"                     #
#  -----------------------------------------------------------------------------------------------------#
#  This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
#  This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
#  the license), but it may not be commercially distributed. Advertise with this tool is not allowed.   #
#  For other uses, permission from the authors is necessary.                                            #
#                                                                                                       #
#########################################################################################################

# from __future__ import unicode_literals

from datetime import datetime, timedelta
from json import dump
from time import gmtime, strftime
from xml.etree.ElementTree import Element, tostring
import argparse
import json
import re
import sys
import threading

PY3 = sys.version_info.major >= 3

if PY3:
	unicode = str
	from urllib.request import urlopen

else:
	from urllib2 import urlopen

MODULE_NAME = __name__.split(".")[-1]
SOURCES = ["msn", "omw", "owm"]  # supported sourcecodes (the order must not be changed)
DESTINATIONS = ["yahoo", "meteo"]  # supported iconcodes (the order must not be changed)


def parser_thread(obj):
	print("parser_thread")
	obj.parser()
	if obj.callback:
		if obj.error:
			obj.callback(None, obj.error)
		else:
			info = obj.parser()
			obj.callback(info, None)


def add_short_codes(original_dict):
	new_entries = {}
	for key, value in original_dict.items():
		if key.startswith(('d', 'n')) and len(key) == 4:  # Es: d000, n100
			short_key = key[:-1]  # Remove the last zero -> d00, n10
			new_entries[short_key] = value
	original_dict.update(new_entries)


def add_short_descs(original_descs):
	new_entries = {}
	for key, value in original_descs.items():
		if key.startswith(('d', 'n')) and len(key) == 4:  # d000, n100, etc.
			short_key = key[:-1]  # d00, n10
			if short_key not in original_descs:
				new_entries[short_key] = value
	original_descs.update(new_entries)


class Weatherinfo:
	def __init__(self, newmode="msn", apikey=None):
		print("weatherInfo")
		self.msnCodes = {
			"d000": ("32", "B"), "d100": ("34", "B"), "d200": ("30", "H"), "d210": ("12", "Q"),
			"d211": ("5", "W"), "d212": ("14", "V"), "d220": ("11", "Q"), "d221": ("42", "V"),
			"d222": ("16", "W"), "d240": ("4", "0"), "d300": ("28", "H"), "d310": ("11", "Q"),
			"d311": ("5", "W"), "d312": ("14", "V"), "d320": ("39", "R"), "d321": ("5", "W"),
			"d322": ("16", "W"), "d340": ("4", "0"), "d400": ("26", "Y"), "d410": ("9", "Q"),
			"d411": ("5", "W"), "d412": ("14", "V"), "d420": ("9", "Q"), "d421": ("5", "W"),
			"d422": ("16", "W"), "d430": ("12", "Q"), "d431": ("5", "W"), "d432": ("15", "W"),
			"d440": ("4", "0"), "d500": ("28", "H"), "d600": ("20", "E"), "d603": ("10", "U"),
			"d605": ("17", "X"), "d705": ("17", "X"), "d900": ("21", "M"), "d905": ("17", "X"),
			"d907": ("21", "M"), "n000": ("31", "C"), "n100": ("33", "C"), "n200": ("29", "I"),
			"n210": ("45", "Q"), "n211": ("5", "W"), "n212": ("46", "W"), "n220": ("45", "Q"),
			"n221": ("5", "W"), "n222": ("46", "W"), "n240": ("47", "Z"), "n300": ("27", "I"),
			"n310": ("45", "Q"), "n311": ("11", "Q"), "n312": ("46", "W"), "n320": ("45", "R"),
			"n321": ("5", "W"), "n322": ("46", "W"), "n340": ("47", "Z"), "n400": ("26", "Y"),
			"n410": ("9", "Q"), "n411": ("5", "W"), "n412": ("14", "V"), "n420": ("9", "Q"),
			"n421": ("5", "W"), "n422": ("14", "W"), "n430": ("12", "Q"), "n431": ("5", "W"),
			"n432": ("15", "W"), "n440": ("4", "0"), "n500": ("29", "I"), "n600": ("20", "E"),
			"n603": ("10", "U"), "n605": ("17", "X"), "n705": ("17", "X"), "n900": ("21", "M"),
			"n905": ("17", "X"), "n907": ("21", "M"),

			# lululla added
			"d00": ("32", "B"), "d10": ("34", "B"), "d20": ("30", "H"), "d21": ("12", "Q"),
			"d22": ("11", "Q"), "d30": ("28", "H"), "d31": ("11", "Q"), "d32": ("39", "R"),
			"d34": ("4", "0"), "d40": ("26", "Y"), "d41": ("9", "Q"), "d42": ("9", "Q"),
			"d43": ("12", "Q"), "d44": ("4", "0"), "d50": ("28", "H"), "d60": ("20", "E"),
			"n00": ("31", "C"), "n10": ("33", "C"), "n20": ("29", "I"), "n21": ("45", "Q"),
			"n22": ("45", "Q"), "n24": ("47", "Z"), "n30": ("27", "I"), "n31": ("45", "Q"),
			"n32": ("45", "R"), "n42": ("9", "Q"), "n43": ("12", "Q"), "n50": ("29", "I"),
			"n60": ("20", "E")
		}
		add_short_codes(self.msnCodes)

		self.omwCodes = {
			"0": ("32", "B"), "1": ("34", "B"), "2": ("30", "H"), "3": ("28", "N"), "45": ("20", "M"),
			"48": ("21", "J"), "51": ("9", "Q"), "53": ("9", "Q"), "55": ("9", "R"), "56": ("8", "V"),
			"57": ("10", "U"), "61": ("11", "Q"), "63": ("12", "R"), "65": ("12", "R"), "66": ("8", "R"),
			"67": ("7", "W"), "71": ("42", "V"), "73": ("14", "U"), "75": ("41", "W"), "77": ("35", "X"),
			"80": ("11", "Q"), "81": ("12", "R"), "82": ("12", "R"), "85": ("42", "V"), "86": ("43", "W"),
			"95": ("38", "P"), "96": ("4", "O"), "99": ("4", "Z")
		}  # mapping: omw -> (yahoo, meteo)
		self.owmCodes = {
			"200": ("37", "O"), "201": ("4", "O"), "202": ("3", "P"), "210": ("37", "O"), "211": ("4", "O"),
			"212": ("3", "P"), "221": ("3", "O"), "230": ("37", "O"), "231": ("38", "O"), "232": ("38", "O"),
			"300": ("9", "Q"), "301": ("9", "Q"), "302": ("9", "Q"), "310": ("9", "Q"), "311": ("9", "Q"),
			"312": ("9", "R"), "313": ("11", "R"), "314": ("12", "R"), "321": ("11", "R"), "500": ("9", "Q"),
			"501": ("11", "Q"), "502": ("11", "R"), "503": ("12", "R"), "504": ("12", "R"), "511": ("10", "W"),
			"520": ("11", "Q"), "521": ("11", "R"), "522": ("12", "R"), "531": ("40", "Q"), "600": ("42", "U"),
			"601": ("16", "V"), "602": ("15", "V"), "611": ("18", "X"), "612": ("10", "W"), "613": ("17", "X"),
			"615": ("6", "W"), "616": ("5", "W"), "620": ("14", "U"), "621": ("42", "U"), "622": ("13", "V"),
			"701": ("20", "M"), "711": ("22", "J"), "721": ("21", "E"), "731": ("19", "J"), "741": ("20", "E"),
			"751": ("19", "J"), "761": ("19", "J"), "762": ("22", "J"), "771": ("23", "F"), "781": ("0", "F"),
			"800": ("32", "B"), "801": ("34", "B"), "802": ("30", "H"), "803": ("26", "H"), "804": ("28", "N")
		}  # mapping: owm -> (yahoo, meteo)
		self.msnDescs = {
			"d000": "SunnyDayV3", "d100": "MostlySunnyDay", "d200": "D200PartlySunnyV2", "d210": "D210LightRainShowersV2",
			"d211": "D211LightRainSowShowersV2", "d212": "D212LightSnowShowersV2", "d220": "LightRainShowerDay",
			"d221": "D221RainSnowShowersV2", "d222": "SnowShowersDayV2", "d240": "D240TstormsV2",
			"d300": "MostlyCloudyDayV2", "d310": "D310LightRainShowersV2", "d311": "D311LightRainSnowShowersV2",
			"d312": "LightSnowShowersDay", "d320": "RainShowersDayV2", "d321": "D321RainSnowShowersV2",
			"d322": "SnowShowersDayV2", "d340": "D340TstormsV2", "d400": "CloudyV3", "d410": "LightRainV3",
			"d411": "RainSnowV2", "d412": "LightSnowV2", "d420": "HeavyDrizzle", "d421": "RainSnowV2", "d422": "Snow",
			"d430": "ModerateRainV2", "d431": "RainSnowV2", "d432": "HeavySnowV2", "d440": "ThunderstormsV2",
			"d500": "MostlyCloudyDayV2", "d600": "FogV2", "d603": "FreezingRainV2", "d605": "IcePelletsV2",
			"d705": "BlowingHailV2", "d900": "Haze", "d905": "BlowingHailV2", "d907": "Haze",
			"n000": "ClearNightV3", "n100": "MostlyClearNight", "n200": "PartlyCloudyNightV2",
			"n210": "N210LightRainShowersV2", "n211": "N211LightRainSnowShowersV2", "n212": "N212LightSnowShowersV2",
			"n220": "LightRainShowerNight", "n221": "N221RainSnowShowersV2", "n222": "N222SnowShowersV2",
			"n240": "N240TstormsV2", "n300": "MostlyCloudyNightV2", "n310": "N310LightRainShowersV2",
			"n311": "N311LightRainSnowShowersV2", "n312": "LightSnowShowersNight", "n320": "RainShowersNightV2",
			"n321": "N321RainSnowShowersV2", "n322": "N322SnowShowersV2", "n340": "N340TstormsV2", "n400": "CloudyV3",
			"n410": "LightRainV3", "n411": "RainSnowV2", "n412": "LightSnowV2", "n420": "HeavyDrizzle",
			"n421": "RainSnowShowersNightV2", "n422": "N422SnowV2", "n430": "ModerateRainV2",
			"n431": "RainSnowV2", "n432": "HeavySnowV2", "n440": "ThunderstormsV2", "n500": "PartlyCloudyNightV2",
			"n600": "FogV2", "n603": "FreezingRainV2", "n605": "BlowingHailV2", "n705": "BlowingHailV2",
			"n905": "BlowingHailV2", "n907": "Haze", "n900": "Haze",  # "xxxx1": "WindyV2"

			# add from lululla for map codes msn
			"d00": "SunnyDayV3",                 # same as d000
			"d10": "LightRainDay",               # added by you
			"d20": "FogDay",                     # same as d600
			"d21": "D210LightRainShowersV2",     # same as d210
			"d22": "LightRainShowerDay",         # same as d220
			"d30": "ThunderstormDay",            # same as d240/d340
			"d31": "D310LightRainShowersV2",     # same as d310
			"d32": "RainShowersDayV2",           # same as d320
			"d34": "D340TstormsV2",              # same as d340
			"d40": "CloudyV3",                   # same as d400
			"d41": "LightRainV3",                # same as d410
			"d42": "HeavyDrizzle",               # same as d420
			"d43": "ModerateRainV2",             # same as d430
			"d44": "ThunderstormsV2",            # same as d440
			"d50": "MostlyCloudyDayV2",          # same as d500
			"d60": "FogV2",                      # same as d600

			# Night entries (nXX)
			"n00": "ClearNightV3",               # same as n000
			"n10": "LightRainNight",             # added by you
			"n20": "FogNight",                   # same as n600
			"n21": "N210LightRainShowersV2",     # same as n210
			"n22": "LightRainShowerNight",       # same as n220
			"n24": "N240TstormsV2",              # same as n240
			"n30": "MostlyCloudyNightV2",        # same as n300
			"n31": "N310LightRainShowersV2",     # same as n310
			"n32": "RainShowersNightV2",         # same as n320
			"n34": "N340TstormsV2",              # same as n340
			"n40": "CloudyV3",                   # same as n400
			"n41": "LightRainV3",                # same as n410
			"n42": "HeavyDrizzle",               # same as n420
			"n43": "ModerateRainV2",             # same as n430
			"n44": "ThunderstormsV2",            # same as n440
			"n50": "PartlyCloudyNightV2",        # same as n500
			"n60": "FogV2",                      # same as n600
		}  # cleartext description of msn-weathercodes

		# modded from lululla add auto desc
		add_short_descs(self.msnDescs)

		self.omwDescs = {
			"0": "clear sky", "1": "mainly clear", "2": "partly cloudy", "3": "overcast", "45": "fog", "48": "depositing rime fog", "51": "light drizzle",
			"53": "moderate drizzle", "55": "dense intensity drizzle", "56": "light freezing drizzle", "57": "dense intensity freezing drizzle",
			"61": "slight rain", "63": "moderate rain", "65": "heavy intensity rain", "66": "light freezing rain", "67": "heavy intensity freezing rain",
			"71": "slight snow fall", "73": "moderate snow fall", "75": "heavy intensity snow fall", "77": "snow grains", "80": "slight rain showers",
			"81": "moderate rain showers", "82": "violent rain showers", "85": "slight snow showers", "86": "heavy snow showers",
			"95": "slight or moderate thunderstorm", "96": "thunderstorm with slight hail", "99": "thunderstorm with heavy hail"
		}  # cleartext description of omw-weathercodes
		self.owmDescs = {
			"200": "thunderstorm with light rain", "201": "thunderstorm with rain", "202": "thunderstorm with heavy rain",
			"210": "light thunderstorm", "211": "thunderstorm", "212": "heavy thunderstorm", "221": "ragged thunderstorm",
			"230": "thunderstorm with light drizzle", "231": "thunderstorm with drizzle", "232": "thunderstorm with heavy drizzle",
			"300": "light intensity drizzle", "301": "drizzle", "302": "heavy intensity drizzle", "310": "light intensity drizzle rain",
			"311": "drizzle rain", "312": "heavy intensity drizzle rain", "313": "shower rain and drizzle", "314": "heavy shower rain and drizzle",
			"321": "shower drizzle", "500": "light rain", "501": "moderate rain", "502": "heavy intensity rain", "503": "very heavy rain",
			"504": "extreme rain", "511": "freezing rain", "520": "light intensity shower rain", "521": "shower rain", "522": "heavy intensity shower rain",
			"531": "ragged shower rain", "600": "light snow", "601": "Snow", "602": "Heavy snow", "611": "Sleet", "612": "Light shower sleet",
			"613": "Shower sleet", "615": "Light rain and snow", "616": "Rain and snow", "620": "Light shower snow", "621": "Shower snow",
			"622": "Heavy shower snow", "701": "mist", "711": "Smoke", "721": "Haze", "731": "sand/ dust whirls", "741": "fog", "751": "sand",
			"761": "dust", "762": "volcanic ash", "771": "squalls", "781": "tornado", "800": "clear sky", "801": "few clouds: 11-25%",
			"802": "scattered clouds: 25-50%", "803": "broken clouds: 51-84%", "804": "overcast clouds: 85-100%"
		}  # cleartext description of owm-weathercodes
		self.yahooDescs = {
			"0": "tornado", "1": "tropical storm", "2": "hurricane", "3": "severe thunderstorms", "4": "thunderstorms", "5": "mixed rain and snow",
			"6": "mixed rain and sleet", "7": "mixed snow and sleet", "8": "freezing drizzle", "9": "drizzle", "10": "freezing rain",
			"11": "showers", "12": "showers", "13": "snow flurries", "14": "light snow showers", "15": "blowing snow", "16": "snow",
			"17": "hail", "18": "sleet", "19": "dust", "20": "foggy", "21": "haze", "22": "smoky", "23": "blustery", "24": "windy", "25": "cold",
			"26": "cloudy", "27": "mostly cloudy (night)", "28": "mostly cloudy (day)", "29": "partly cloudy (night)", "30": "partly cloudy (day)",
			"31": "clear (night)", "32": "sunny (day)", "33": "fair (night)", "34": "fair (day)", "35": "mixed rain and hail", "36": "hot",
			"37": "isolated thunderstorms", "38": "scattered thunderstorms", "39": "capricious weather", "40": "scattered showers",
			"41": "heavy snow", "42": "scattered snow showers", "43": "heavy snow", "44": "partly cloudy", "45": "rain showers (night)",
			"46": "snow showers (night)", "47": "thundershowers (night)", "NA": "not available"
		}  # cleartext description of modified yahoo-iconcodes
		self.meteoDescs = {
			"!": "windy_rain_inv", "\"": "snow_inv", "#": "snow_heavy_inv", "$": "hail_inv", "%": "clouds_inv", "&": "clouds_flash_inv", "'": "temperature",
			"(": "compass", ")": "na", "*": "celcius", "+": "fahrenheit", "0": "clouds_flash_alt", "1": "sun_inv", "2": "moon_inv", "3": "cloud_sun_inv",
			"4": "cloud_moon_inv", "5": "cloud_inv", "6": "cloud_flash_inv", "7": "drizzle_inv", "8": "rain_inv", "9": "windy_inv", "A": "sunrise",
			"B": "sun", "C": "moon", "D": "eclipse", "E": "mist", "F": "wind", "G": "snowflake", "H": "cloud_sun", "I": "cloud_moon", "J": "fog_sun",
			"K": "fog_moon", "L": "fog_cloud", "M": "fog", "N": "cloud", "O": "cloud_flash", "P": "cloud_flash_alt", "Q": "drizzle", "R": "rain",
			"S": "windy", "T": "windy_rain", "U": "snow", "V": "snow_alt", "W": "snow_heavy", "X": "hail", "Y": "clouds", "Z": "clouds_flash"
		}  # cleartext description of modified meteo-iconcodes

		self.error = None
		self.info = None
		print("221 ---------------------------------------------------")
		self.mode = None
		self.parser = None
		self.geodata = None
		self.units = None
		self.callback = None
		self.reduced = False
		self.setmode(newmode, apikey)

	def setmode(self, newmode="msn", apikey=None):
		self.error = None
		# self.parser = None  # sonst hat er nicht aktualiesiert beim wechseln vom wetter
		self.apikey = apikey
		newmode = newmode.lower()
		print(str(newmode))
		if newmode in SOURCES:
			# nur wenn nicht gleich
			if self.mode != newmode:
				self.mode = newmode
				print(str(self.mode))
				if newmode == "msn":
					self.parser = self.msnparser
				elif newmode == "omw":
					self.parser = self.omwparser
				elif newmode == "owm":
					if apikey:
						self.parser = self.owmparser
					else:
						self.error = "[%s] ERROR in module 'setmode': API-Key for mode '%s' is missing!" % (MODULE_NAME, newmode)
						return self.error

		else:
			print("setmode else error unbekannter modus")
			self.error = "[%s] ERROR in module 'setmode': unknown mode '%s'" % (MODULE_NAME, newmode)
			return self.error

	def directionsign(self, degree):
		print("directionsign")
		directions = [".", "N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
		index = int(round(degree % 360 / 45)) % 8
		return directions[index]

	def convert2icon(self, src, code):
		print("convert2icon")
		print(f"[DEBUG] Weatherinfo Raw Weather for {src}. Code Received: {code}")
		self.error = None
		src = src.lower()
		if code is None:
			self.error = "[%s] ERROR in module 'convert2icon': input code value is 'None'" % MODULE_NAME
			print(self.error)
			return
		print("convert2icon2")
		code = str(code).strip()
		selection = {"msn": self.msnCodes, "owm": self.owmCodes, "omw": self.omwCodes}
		if src is not None and src in selection:
			print("convert2icon3")
			common = selection[src]
		else:
			print("convert2icon4")
			print("WARNING in module 'convert2icon': convert source '%s' is unknown. Valid is: %s" % (src, SOURCES))
			return
		print("convert2icon5")
		result = dict()
		if src == "msn":
			print("convert2icon6")
			code = code[:-1]  # reduce MSN-code by 'windy'-flag
		if code in common:
			print("convert2icon7")
			result["yahooCode"] = common[code][0]
			result["meteoCode"] = common[code][1]
		else:
			print("convert2icon8")
			result["yahooCode"] = "NA"
			result["meteoCode"] = "NA"
			print("WARNING in module 'convert2icon': key '%s' not found in converting dicts." % code)
			return
		print("convert2icon9")
		return result

	def getCitylist(self, cityname=None, scheme="de-de"):
		print("getcitylist")
		self.error = None
		if not cityname:
			print("getcitylist for city not")
			self.error = "[%s] ERROR in module 'getCitylist': missing cityname." % MODULE_NAME
			print("getcitylist for city not error")
			return

		elif self.mode in ["msn", "omw"]:
			print("getcitylist msn own")
			cityname, country = self.separateCityCountry(cityname)
			jsonData = None
			for city in [cityname, cityname.split(" ")[0]]:
				print("getcitylist for city hier")
				link = "https://geocoding-api.open-meteo.com/v1/search?language=%s&count=10&name=%s%s" % (scheme[:2], city, "" if country is None else ",%s" % country)
				print(str(link))
				print("getcitylist for city hier 1")
				jsonData = self.apiserver(link)

				if jsonData is not None and "latitude" in jsonData.get("results", [""])[0]:
					print("getcitylist for city hier 3")
					break
			if jsonData is None or "results" not in jsonData:
				print("getcitylist json")
				self.error = "[%s] ERROR in module 'getCitylist.owm': no city '%s' found on the server. Try another wording." % (MODULE_NAME, cityname)
				return
			print("getcitylist for city hier 4")
			count = 0
			citylist = []
			print("getcitylist 2")
			try:
				print("getcitylist try for")
				for hit in jsonData["results"]:
					count += 1
					if count > 9:
						break
					cityname = hit["name"] if "name" in hit else ""
					country = ", %s" % hit["country"].upper() if "country" in hit else ""
					admin1 = ", %s" % hit["admin1"] if "admin1" in hit else ""
					admin2 = ", %s" % hit["admin2"] if "admin2" in hit else ""
					admin3 = ", %s" % hit["admin3"] if "admin3" in hit else ""
					citylist.append(("%s%s%s%s%s" % (cityname, admin1, admin2, admin3, country), hit["longitude"], hit["latitude"]))
			except Exception as err:
				print("getcitylist error")
				self.error = "[%s] ERROR in module 'getCitylist.owm': general error. %s" % (MODULE_NAME, str(err))
				return

		elif self.mode == "owm":
			special = {"br": "pt_br", "se": "sv, se", "es": "sp, es", "ua": "ua, uk", "cn": "zh_cn"}
			if scheme[:2] in special:
				scheme = special[scheme[:2]]
			cityname, country = self.separateCityCountry(cityname)
			jsonData = None
			for city in [cityname, cityname.split(" ")[0]]:
				link = "https://api.openweathermap.org/geo/1.0/direct?q=%s%s&lang=%s&limit=15&appid=%s" % (city, "" if country is None else ",%s" % country, scheme[:2], self.apikey)
				jsonData = self.apiserver(link)
				if jsonData:
					break
			if not jsonData:
				self.error = "[%s] ERROR in module 'getCitylist.owm': no city '%s' found on the server. Try another wording." % (MODULE_NAME, cityname)
				return
			count = 0
			citylist = []
			try:
				for hit in jsonData:
					count += 1
					if count > 9:
						break
					cityname = hit["local_names"][scheme[:2]] if "local_names" in hit and scheme[:2] in hit["local_names"] else hit["name"]
					state = ", %s" % hit["state"] if "state" in hit else ""
					country = ", %s" % hit["country"].upper() if "country" in hit else ""
					citylist.append(("%s%s%s" % (cityname, state, country), hit["lon"], hit["lat"]))
			except Exception as err:
				self.error = "[%s] ERROR in module 'getCitylist.owm': general error. %s" % (MODULE_NAME, str(err))
				return
		else:
			self.error = "[%s] ERROR in module 'getCitylist': unknown mode." % MODULE_NAME
			return
		print("return citylist")
		# citylist = jsonData.get("results", [])
		# print("return citylist: {}".format(citylist))
		return citylist

	def separateCityCountry(self, cityname):
		print("separateCityContry")
		country = None
		for special in [",", ";", "&", "|", "!"]:
			items = cityname.split(special)
			if len(items) > 1:
				cityname = "".join(items[:-1]).strip()
				country = "".join(items[-1:]).strip().upper()
				break
		print("name")
		print(str(cityname))
		print(str(country))
		return cityname, country

	def start(self, geodata=None, cityID=None, units="metric", scheme="de-de", reduced=False, callback=None):
		print("440 def start geodata")
		self.error = None
		self.geodata = ("", 0, 0) if geodata is None else geodata
		self.cityID = cityID
		self.units = units.lower()
		self.scheme = scheme.lower()
		self.callback = callback
		self.reduced = reduced
		if not self.geodata[0] and cityID is None:
			self.error = "[%s] ERROR in module 'start': missing cityname for mode '%s'." % (MODULE_NAME, self.mode)
		elif not self.geodata[1] or not self.geodata[2]:
			self.error = "[%s] ERROR in module 'start': missing geodata for mode '%s'." % (MODULE_NAME, self.mode)
		elif self.mode not in SOURCES:
			self.error = "[%s] ERROR in module 'start': unknown mode '%s'." % (MODULE_NAME, self.mode)
		if callback:
			if self.error:
				callback(None, self.error)
			elif self.parser:
				# callInThread(self.parser)
				thread = threading.Thread(target=parser_thread, args=(self,))
				thread.start()
				print("start 7")
		else:
			if self.error:
				return
			elif self.parser:
				info = self.parser()
				return None if self.error else info

	def stop(self):
		print("stop")
		self.error = None
		self.callback = None

	def apiserver(self, link):
		print("apiserver")
		self.error = None
		if link:
			try:
				response = urlopen(link, timeout=6)
				json_data = json.loads(response.read())  # Anpassung dieser Zeile
			except Exception as err:
				self.error = "[%s] ERROR in module 'apiserver': '%s" % (MODULE_NAME, str(err))
				return
			try:
				if json_data:
					return json_data
				self.error = "[%s] ERROR in module 'apiserver': server access failed." % MODULE_NAME
			except Exception as err:
				self.error = "[%s] ERROR in module 'apiserver': invalid json data from server. %s" % (
					MODULE_NAME, str(err))
		else:
			self.error = "[%s] ERROR in module 'apiserver': missing link." % MODULE_NAME

	def msnparser(self):
		print("msnparser")
		self.error = None
		self.info = None
		if self.geodata:
			tempunit = "F" if self.units == "imperial" else "C"
			# linkcode = "68747470733A2F2F6170692E6D736E2E636F6D2F7765617468657266616C636F6E2F776561746865722F6F766572766965773F266C6F6E3D2573266C61743D2573266C6F63616C653D257326756E6974733D25732661707049643D39653231333830632D666631392D346337382D623465612D313935353865393361356433266170694B65793D6A356934674471484C366E47597778357769356B5268586A74663263357167465839667A666B30544F6F266F6369643D73757065726170702D6D696E692D7765617468657226777261704F446174613D66616C736526696E636C7564656E6F7763617374696E673D7472756526666561747572653D6C696665646179266C696665446179733D363"
			# print("linkcode: {}".format(linkcode))
			# Log der anderen Variablen lat , lon , locale , units sein , , sollte so sein "NAME", "LAT", "LON"
			# link = "https://api.msn.com/weatherfalcon/weather/overview?&lon=9.99302&lat=53.55073&locale=de-de&units=C&appId=9e21380c-ff19-4c78-b4ea-19558e93a5d3&apiKey=j5i4gDqHL6nGYwx5wi5kRhXjtf2c5qgFX9fzfk0TOo&ocid=superapp-mini-weather&wrapOData=false&includenowcasting=true&feature=lifeday&lifeDays=6"
			lon = float(self.geodata[1])
			lat = float(self.geodata[2])
			locale = self.scheme
			unit = tempunit
			link = "https://api.msn.com/weatherfalcon/weather/overview?&lon={lon}&lat={lat}&locale={locale}&units={unit}&appId=9e21380c-ff19-4c78-b4ea-19558e93a5d3&apiKey=j5i4gDqHL6nGYwx5wi5kRhXjtf2c5qgFX9fzfk0TOo&ocid=superapp-mini-weather&wrapOData=false&includenowcasting=true&feature=lifeday&lifeDays=6".format(
				lon=lon, lat=lat, locale=locale, unit=unit)
			# link = urllib.unquote(linkcode) % (float(self.geodata[1]), float(self.geodata[2]), self.scheme, tempunit)
			# print("Generated link: {}".format(link))  # Ausgabe des generierten Links zur Analyse
		else:
			self.error = "[%s] ERROR in module 'msnparser': missing geodata." % MODULE_NAME
			if self.callback:
				self.callback(None, self.error)
			return
		if self.callback:
			print("msnparser 3")
			print("[%s] accessing MSN for weatherdata..." % MODULE_NAME)
		self.info = self.apiserver(link)
		if self.callback:
			if self.error:
				self.callback(None, self.error)
			else:
				print("[%s] MSN successfully accessed..." % MODULE_NAME)
				self.callback(self.getreducedinfo() if self.reduced else self.info, None)
		if self.info and self.error is None:
			return self.getreducedinfo() if self.reduced else self.info

	def omwparser(self):
		print("omwparser ")
		self.error = None
		self.info = None
		windunit = "mph" if self.units == "imperial" else "kmh"
		tempunit = "fahrenheit" if self.units == "imperial" else "celsius"
		timezones = {"-06": "America/Anchorage", "-05": "America/Los_Angeles", "-04": "America/Denver", "-03": "America/Chicago", "-02": "America/New_York",
					 "-01": "America/Sao_Paulo", "+00": "Europe/London", "+01": "Europe/Berlin", "+02": "Europe/Moscow", "+03": "Africa/Cairo",
					 "+04": "Asia/Bangkok", "+05": "Asia/Singapore", "+06": "Asia/Tokyo", "+07": "Australia/Sydney", "+08": "Pacific/Auckland"}
		currzone = timezones.get(strftime("%z", gmtime())[:3], "Europe/Berlin")
		if self.geodata:
			# lon = float(self.geodata[1])
			# lat = float(self.geodata[2])
			# locale = currzone
			# unitw = windunit
			# unitt = tempunit
			link = "https://api.open-meteo.com/v1/forecast?longitude=%s&latitude=%s&hourly=temperature_2m,relativehumidity_2m,apparent_temperature,weathercode,windspeed_10m,winddirection_10m,precipitation_probability&daily=sunrise,sunset,weathercode,precipitation_probability_max,temperature_2m_max,temperature_2m_min&timezone=%s&windspeed_unit=%s&temperature_unit=%s" % (float(self.geodata[1]), float(self.geodata[2]), currzone, windunit, tempunit)
		else:
			self.error = "[%s] ERROR in module 'omwparser': missing geodata." % MODULE_NAME
			if self.callback:
				self.callback(None, self.error)
			return
		if self.callback:
			print("[%s] accessing OMW for weatherdata..." % MODULE_NAME)
		self.info = self.apiserver(link)
		if self.callback:
			if self.error:
				self.callback(None, self.error)
			else:
				print("[%s] OMW successfully accessed." % MODULE_NAME)
				self.callback(self.getreducedinfo() if self.reduced else self.info, self.error)
		if self.info and self.error is None:
			return self.getreducedinfo() if self.reduced else self.info

# --------------------------------------- OWM mit api ---------------------------------------------------
	def owmparser(self):
		print("owmparser ")
		self.error = None
		self.info = None
		if not self.apikey:
			self.error = "[%s] ERROR in module' owmparser': API-key is missing!" % MODULE_NAME
			if self.callback:
				self.callback(None, self.error)
			return

		# lon = float(self.geodata[2])
		# lat = float(self.geodata[1])
		if self.cityID:
			link = "http://api.openweathermap.org/data/2.5/forecast?id=%s&units=%s&lang=%s&appid=%s" % (self.cityID, self.units, self.scheme[: 2], self.apikey)
		elif self.geodata:
			link = "https://api.openweathermap.org/data/2.5/forecast?&lon=%s&lat=%s&units=%s&lang=%s&appid=%s" % (self.geodata[1], self.geodata[2], self.units, self.scheme[: 2], self.apikey)
		else:
			self.error = "[%s] ERROR in module 'owmparser': missing geodata or cityID." % MODULE_NAME
			if self.callback:
				self.callback(None, self.error)
			return
		if self.callback:
			print("[%s] accessing OWM for weatherdata..." % MODULE_NAME)
		self.info = self.apiserver(link)
		if self.callback:
			if self.error:
				self.callback(None, self.error)
			else:
				print("[%s] OWM successfully accessed..." % MODULE_NAME)
				self.callback(self.getreducedinfo() if self.reduced else self.info, self.error)
		if self.info and self.error is None:
			return self.getreducedinfo() if self.reduced else self.info

	def getCitybyID(self, cityID=None):  # owm's cityID is DEPRECATED
		print("getcityID")
		self.error = None
		if self.mode != "owm":
			self.error = "[%s] ERROR in module 'getCitybyID': unsupported mode '%s', only mode 'owm' is supported" % (MODULE_NAME, self.mode)
			return
		if not cityID:
			self.error = "[%s] ERROR in module 'getCitybyID': missing cityID" % MODULE_NAME
			return
		link = "http://api.openweathermap.org/data/2.5/forecast?id=%s&cnt=1&appid=%s" % (cityID, self.apikey)
		if self.callback:
			print("[%s] accessing OWM for cityID..." % MODULE_NAME)
		cityname = "N/A"
		jsonData = self.apiserver(link)
		if jsonData:
			if self.callback:
				print("[%s] accessing OWM successful." % MODULE_NAME)
			try:
				citydata = jsonData.get("city", {})
				cityname = citydata.get("name", "N/A")
				lon = citydata.get("coord", {}).get("lon", "N/A")
				lat = citydata.get("coord", {}).get("lat", "N/A")
				return (cityname, lon, lat)
			except Exception as err:
				self.error = "[%s] ERROR in module 'getCitybyID': general error. %s" % (MODULE_NAME, str(err))
				return
		else:
			self.error = "[%s] ERROR in module 'getCitybyID': no city '%s' found on the server. Try another wording." % (MODULE_NAME, cityname)

	def getCitylistbyGeocode(self, geocode=None, scheme="de-de"):
		print("getCityListbyGeocode")
		self.error = None
		if geocode:
			lon = geocode.split(",")[0].strip()
			lat = geocode.split(",")[1].strip()
		else:
			lon = None
			lat = None
		if self.mode and not self.mode.startswith("owm"):
			self.error = "[%s] ERROR in module 'getCitylistbyGeocode': unsupported mode '%s', only mode 'owm' is supported" % (MODULE_NAME, self.mode)
			return
		if not lon or not lat:
			self.error = "[%s] ERROR in module 'getCitylistbyGeocode': incomplete or missing coordinates" % MODULE_NAME
			return
		link = "http://api.openweathermap.org/geo/1.0/reverse?lon=%s&lat=%s&limit=15&appid=%s" % (lon, lat, self.apikey)
		if self.callback:
			print("[%s] accessing OWM for coordinates..." % MODULE_NAME)
		jsonData = self.apiserver(link)
		if jsonData:
			if self.callback:
				print("[%s] accessing OWM successful." % MODULE_NAME)
			try:
				citylist = []
				for hit in jsonData:
					cityname = hit["local_names"][scheme[:2]] if "local_names" in hit and scheme[:2] in hit["local_names"] else hit["name"]
					state = ", %s" % hit["state"] if "state" in hit else ""
					country = ", %s" % hit["country"].upper() if "country" in hit else ""
					citylist.append(("%s%s%s" % (cityname, state, country), hit.get("lon", "N/A"), hit.get("lat", "N/A")))
				return citylist
			except Exception as err:
				self.error = "[%s] ERROR in module 'getCitylistbyGeocode': general error. %s" % (MODULE_NAME, str(err))
				return
		else:
			self.error = "[%s] ERROR in module 'getCitylistbyGeocode': no data." % MODULE_NAME

	def getreducedinfo(self):
		print("getreducedinfo")
		self.error = None
		namefmt = "%s, %s"
		daytextfmt = "%a, %d."
		datefmt = "%Y-%m-%d"
		reduced = dict()
		print(str(self.parser))
		if self.info:
			print("getreducedinfo 1")
			if self.parser is not None and self.mode == "msn":
				print("getreducedinfo 2")
				if self.geodata:
					print("getreducedinfo 3")
					try:
						source = self.info["responses"][0]["source"]
						current = self.info["responses"][0]["weather"][0]["current"]
						forecast = self.info["responses"][0]["weather"][0]["forecast"]["days"]
						reduced["source"] = "MSN Weather"
						location = self.geodata[0].split(",")
						reduced["name"] = namefmt % (location[0].strip(), location[1].strip()) if len(location) > 1 else location[0].strip()
						reduced["longitude"] = str(source["coordinates"]["lon"])
						reduced["latitude"] = str(source["coordinates"]["lat"])
						# tempunit = self.info["units"]["temperature"]
						tempunit = self.info["units"]["temperature"].strip("\u200e")
						reduced["tempunit"] = tempunit
						reduced["windunit"] = self.info["units"]["speed"]
						reduced["precunit"] = "%"
						reduced["current"] = dict()
						reduced["current"]["observationPoint"] = source["location"]["Name"]

						currdate = current["created"]

						# Log-Ausgabe des ungeparsen Datums
						parts = currdate.split('+')

						# Den Stunden-Offset extrahieren
						if len(parts) == 2:
							offset = parts[1]
							hours_offset = int(offset.split(':')[0])
						else:
							hours_offset = 0  # Fallback-Wert, falls der Offset nicht gefunden wird
							print('hours_offset:', hours_offset)
						# Versuche das Datum ohne Offset zu parsen
						try:
							currdate_str_without_offset = currdate[:19]  # Entferne die letzten 5 Zeichen mit dem Offset
							parsed_currdate = datetime.strptime(currdate_str_without_offset, "%Y-%m-%dT%H:%M:%S")
							currdate = parsed_currdate
						except ValueError:
							# Wenn das Parsen fehlschlaegt, behalte das urspruengliche Datum in `currdate`
							print("Parsen des Datums fehlgeschlagen.")
							print(str(currdate))

						reduced["current"]["observationTime"] = currdate
						reduced["current"]["sunrise"] = forecast[0]["almanac"]["sunrise"]
						reduced["current"]["sunset"] = forecast[0]["almanac"]["sunset"]
						# now = datetime.now().astimezone()
						timezone_offset_hours = 2
						timezone_offset = timedelta(hours=timezone_offset_hours)
						now = datetime.now() + timezone_offset
						sunrise_str = forecast[0]["almanac"]["sunrise"]
						sunrise = None  # Initialisiere sunrise mit None
						# Extrahiere den Offset aus dem String
						offset_match = re.search(r"([+-])(\d{2}):(\d{2})", sunrise_str)
						if offset_match:
							offset_sign = offset_match.group(1)
							offset_hours = int(offset_match.group(2))
							offset_minutes = int(offset_match.group(3))
							offset = timedelta(hours=offset_hours, minutes=offset_minutes)

							# Entferne den Offset aus dem String und parsiere das Datum
							sunrise_str = re.sub(r"[+-]\d{2}:\d{2}$", "", sunrise_str)
							sunrise = datetime.strptime(sunrise_str, "%Y-%m-%dT%H:%M:%S")

							# Wende den Offset auf das Datum an
							if offset_sign == "-":
								sunrise -= offset
							else:
								sunrise += offset
						else:
							# Wenn kein Offset gefunden wurde, handle den Fall entsprechend
							print("ERROR: Kein Offset gefunden in %s" % sunrise_str)
						if sunrise is not None:
							# Weitere Verarbeitung mit dem sunrise-Datetime-Objekt...
							print("getreducedinfo 3-3a")
						else:
							# Handle den Fall, wenn sunrise nicht zugewiesen wurde
							print("ERROR: sunrise wurde nicht zugewiesen.")
						# ueberpruefe, ob sunrise zugewiesen wurde, bevor du es weiterverwendest

						print("getreducedinfo 3-3")
						sunset_str = forecast[0]["almanac"]["sunset"]
						sunset = None  # Initialisiere sunset mit None
						# Extrahiere den Offset aus dem String
						offset_match = re.search(r"([+-])(\d{2}):(\d{2})", sunset_str)
						if offset_match:
							offset_sign = offset_match.group(1)
							offset_hours = int(offset_match.group(2))
							offset_minutes = int(offset_match.group(3))
							offset = timedelta(hours=offset_hours, minutes=offset_minutes)

							# Entferne den Offset aus dem String und parsiere das Datum
							sunset_str = re.sub(r"[+-]\d{2}:\d{2}$", "", sunset_str)
							sunset = datetime.strptime(sunset_str, "%Y-%m-%dT%H:%M:%S")

							# Wende den Offset auf das Datum an
							if offset_sign == "-":
								sunset -= offset
							else:
								sunset += offset

						else:
							# Wenn kein Offset gefunden wurde, handle den Fall entsprechend
							print("ERROR: Kein Offset gefunden in %s" % sunset_str)

						# ueberpruefe, ob sunset zugewiesen wurde, bevor du es weiterverwendest
						if sunset is not None:
							print("getreducedinfo 3-4a")
							# Weitere Verarbeitung mit dem sunset-Datetime-Objekt...
						else:
							# Handle den Fall, wenn sunset nicht zugewiesen wurde
							print("ERROR: sunset wurde nicht zugewiesen.")
						print("getreducedinfo 3-4")
						reduced["current"]["isNight"] = now < sunrise or now > sunset
						pvdrCode = forecast[0]["hourly"][0]["symbol"] if forecast[0]["hourly"] else current["symbol"]
						reduced["current"]["ProviderCode"] = pvdrCode
						print("getreducedinfo 3-4a")
						iconCode = self.convert2icon("MSN", pvdrCode)
						reduced["current"]["yahooCode"] = iconCode.get("yahooCode", "NA") if iconCode else "NA"
						reduced["current"]["meteoCode"] = iconCode.get("meteoCode", ")") if iconCode else ")"
						reduced["current"]["temp"] = "%.0f" % current["temp"]
						reduced["current"]["feelsLike"] = "%.0f" % current["feels"]
						reduced["current"]["humidity"] = "%.0f" % current["rh"]
						reduced["current"]["windSpeed"] = "%.0f" % current["windSpd"]
						windDir = current["windDir"]
						reduced["current"]["windDir"] = str(windDir)
						reduced["current"]["windDirSign"] = self.directionsign(windDir)
						reduced["current"]["minTemp"] = "%.0f" % forecast[0]["daily"]["tempLo"]
						reduced["current"]["maxTemp"] = "%.0f" % forecast[0]["daily"]["tempHi"]
						reduced["current"]["precipitation"] = "%.0f" % forecast[0]["daily"]["day"]["precip"]
						try:
							print("getreducedinfo 3-5b")
							# currdate_str_without_offset = currdate[:19]  # Entferne die letzten 5 Zeichen mit dem Offset
							# print(str(currdate_str_without_offset))
							# parsed_currdate = datetime.strptime(currdate, "%Y-%m-%d %H:%M:%S")
							# print("currdate2")
							# print(str(parsed_currdate))
							# currdate = parsed_currdate
						except ValueError:
							# Wenn das Parsen fehlschlaegt, behalte das urspruengliche Datum in `currdate`
							print("Parsen des Datums fehlgeschlagen.")
							print(str(currdate))

						print("getreducedinfo 3-6")
						reduced["current"]["dayText"] = currdate.strftime(daytextfmt)
						reduced["current"]["day"] = currdate.strftime("%A")
						reduced["current"]["shortDay"] = currdate.strftime("%a")
						reduced["current"]["date"] = currdate.strftime(datefmt)
						reduced["current"]["text"] = forecast[0]["hourly"][0]["pvdrCap"] if forecast[0]["hourly"] else current["capAbbr"]
						reduced["current"]["raintext"] = self.info["responses"][0]["weather"][0]["nowcasting"]["summary"]
						reduced["forecast"] = dict()
						for idx in range(6):  # collect forecast of today and next 5 days
							reduced["forecast"][idx] = dict()
							pvdrCode = forecast[idx]["daily"]["symbol"]
							reduced["forecast"][idx]["ProviderCode"] = pvdrCode
							iconCodes = self.convert2icon("MSN", pvdrCode)
							reduced["forecast"][idx]["yahooCode"] = iconCodes.get("yahooCode", "NA") if iconCodes else "NA"
							reduced["forecast"][idx]["meteoCode"] = iconCodes.get("meteoCode", ")") if iconCodes else ")"
							reduced["forecast"][idx]["minTemp"] = "%.0f" % forecast[idx]["daily"]["tempLo"]
							reduced["forecast"][idx]["maxTemp"] = "%.0f" % forecast[idx]["daily"]["tempHi"]
							reduced["forecast"][idx]["precipitation"] = "%.0f" % forecast[idx]["daily"]["day"]["precip"]
							reduced["forecast"][idx]["dayText"] = currdate.strftime(daytextfmt)
							reduced["forecast"][idx]["day"] = currdate.strftime("%A")
							reduced["forecast"][idx]["shortDay"] = currdate.strftime("%a")
							reduced["forecast"][idx]["date"] = currdate.strftime(datefmt)
							reduced["forecast"][idx]["text"] = forecast[idx]["daily"]["pvdrCap"]
							reduced["forecast"][idx]["daySummary0"] = forecast[idx]["daily"]["day"]["summaries"][0]
							reduced["forecast"][idx]["daySummary1"] = forecast[idx]["daily"]["day"]["summaries"][1].replace(".", " %s." % tempunit)
							reduced["forecast"][idx]["nightSummary0"] = forecast[idx]["daily"]["night"]["summaries"][0]
							reduced["forecast"][idx]["nightSummary1"] = forecast[idx]["daily"]["night"]["summaries"][1].replace(".", " %s." % tempunit)
							umbrellaIndex = self.info["responses"][0]["weather"][0]["lifeDaily"]["days"][0]["umbrellaIndex"]
							reduced["forecast"][idx]["umbrellaIndex"] = umbrellaIndex["longSummary2"] if "longSummary2" in umbrellaIndex else umbrellaIndex["summary"]
							currdate = currdate + timedelta(1)
							print("getreducedinfo currdate")
					except Exception as err:
						print("getreducedinfo 4")
						self.error = "[%s] ERROR in module 'getreducedinfo#msn': general error. %s" % (MODULE_NAME, str(err))
						return

			elif self.parser is not None and self.mode == "omw":
				print("getreducedinfo omw")
				if self.geodata:
					print("getreducedinfo omw1")
					try:
						current = self.info["hourly"]
						forecast = self.info["daily"]
						reduced["source"] = "Open-Meteo Weather"
						location = self.geodata[0].split(",")
						reduced["name"] = namefmt % (location[0].strip(), location[1].strip()) if len(location) > 1 else location[0].strip()
						reduced["longitude"] = str(self.info["longitude"])
						reduced["latitude"] = str(self.info["latitude"])
						reduced["tempunit"] = self.info["hourly_units"]["temperature_2m"]
						reduced["windunit"] = self.info["hourly_units"]["windspeed_10m"]
						reduced["precunit"] = self.info["hourly_units"]["precipitation_probability"]
						# isotime = "%s%s" % (datetime.now(timezone.utc).astimezone().isoformat()[: 14], "00")
						# Holen Sie sich die aktuelle Zeit im UTC-Format
						current_time = datetime.utcnow()
						# Konvertieren Sie die UTC-Zeit in die gewünschte Zeitzone (oder UTC-offset)
						# Hier verwenden wir eine feste Verschiebung von 0 Stunden und 0 Minuten (00:00).
						offset = timedelta(hours=2, minutes=0)
						localized_time = current_time + offset
						# Setzen Sie die Minuten auf 0, um immer volle Stunden zu haben
						localized_time = localized_time.replace(minute=0)
						# Formatieren Sie das Datum und die Uhrzeit in der gewünschten Zeichenfolge
						isotime = localized_time.strftime("%Y-%m-%dT%H:%M")
						reduced["current"] = dict()

						for idx, time in enumerate(current["time"]):  # collect current
							if isotime in time:
								print("getreducedinfo omw5")
								# isotime = datetime.now(timezone.utc).astimezone().isoformat()
								# Holen Sie sich die aktuelle Zeit im UTC-Format
								current_time1 = datetime.utcnow()
								offset = timedelta(hours=2, minutes=0)
								current_time = current_time1 + offset
								# Formatieren Sie die Zeit im ISO-Format
								isotime = current_time.isoformat()
								reduced["current"]["observationPoint"] = self.geodata[0]
								isotime = isotime[:14] + "00"
								reduced["current"]["observationTime"] = "%s%s" % (isotime[: 19], isotime[26:])
								sunrise_str = forecast["sunrise"][0]
								# Überprüfe die Länge der Zeichenfolge
								if len(sunrise_str) < 16:
									# Die Zeichenfolge ist zu kurz, um das erwartete Format zu haben
									print("Ungültige sunrise-Zeichenfolge: ")
									print(str(sunrise_str))
								else:
									print("getreducedinfo omw5b 2 else")
									# Die Zeichenfolge hat die erwartete Länge, versuche sie zu konvertieren
									# sunrise_str = remove_timezone_info(sunrise_str)  # Entferne die Zeitzoneninformation
									try:
										print("getreducedinfo omw5b 2 try")
										# Konvertiere die Zeichenfolge in ein datetime-Objekt
										sunrise = datetime.strptime(sunrise_str, "%Y-%m-%dT%H:%M")
										# Setze die Minutenkomponente von sunrise auf 0
										# sunrise = sunrise.replace(minute=0)
										extracted_sunrise = sunrise_str[:16]
										reduced["current"]["sunrise"] = extracted_sunrise
										# reduced["current"]["sunrise"] = sunrise
									except ValueError as err:
										error_message = "Fehler beim Konvertieren von sunrise: {0}. Zeichenfolge: {1}".format(err, forecast["sunrise"][0])
										print(str(error_message))

								print("getreducedinfo omw5c sunset")
								sunset_str = forecast["sunset"][0]
								sunset = datetime.strptime(sunset_str, "%Y-%m-%dT%H:%M")
								# sunset = sunset.replace(minute=0)
								# reduced["current"]["sunset"] = sunset
								extracted_sunset = sunset_str[:16]
								reduced["current"]["sunset"] = extracted_sunset

								now = datetime.now()
								# sunrise = datetime.fromisoformat(forecast["sunrise"][0])
								# sunrise = datetime.strptime(forecast["sunrise"][0], "%Y-%m-%dT%H:%M:%S%z")
								sunrise_str = forecast["sunrise"][0]
								sunrise = datetime.strptime(sunrise_str, "%Y-%m-%dT%H:%M")
								# sunset = datetime.fromisoformat(forecast["sunset"][0])
								# sunset = datetime.strptime(forecast["sunset"][0], "%Y-%m-%dT%H:%M:%S%z")
								sunset_str = forecast["sunset"][0]
								sunset = datetime.strptime(sunset_str, "%Y-%m-%dT%H:%M")
								reduced["current"]["isNight"] = now < sunrise or now > sunset
								pvdrCode = current["weathercode"][idx]
								reduced["current"]["ProviderCode"] = str(pvdrCode)
								iconCode = self.convert2icon("OMW", pvdrCode)

								if iconCode:
									print("getreducedinfo omw6")
									reduced["current"]["yahooCode"] = iconCode.get("yahooCode", "NA")
									reduced["current"]["meteoCode"] = iconCode.get("meteoCode", ")")
								reduced["current"]["temp"] = "%.0f" % current["temperature_2m"][0]
								reduced["current"]["feelsLike"] = "%.0f" % current["apparent_temperature"][idx]
								reduced["current"]["humidity"] = "%.0f" % current["relativehumidity_2m"][idx]
								reduced["current"]["windSpeed"] = "%.0f" % current["windspeed_10m"][idx]
								windDir = current["winddirection_10m"][idx]
								reduced["current"]["windDir"] = str(windDir)
								reduced["current"]["windDirSign"] = self.directionsign(windDir)

								# currdate = datetime.fromisoformat(time)
								# currdate = datetime.strptime(time, "%Y-%m-%dT%H:%M:%S%z")
								# currdate_str = forecast["currdate"][0]
								# print(str(currdate_str))
								currdate = datetime.strptime(time, "%Y-%m-%dT%H:%M")
								reduced["current"]["dayText"] = currdate.strftime(daytextfmt)
								reduced["current"]["day"] = currdate.strftime("%A")
								reduced["current"]["shortDay"] = currdate.strftime("%a")
								reduced["current"]["date"] = currdate.strftime(datefmt)
								reduced["current"]["minTemp"] = "%.0f" % forecast["temperature_2m_min"][0]
								reduced["current"]["maxTemp"] = "%.0f" % forecast["temperature_2m_max"][0]
								reduced["current"]["precipitation"] = "%.0f" % current["precipitation_probability"][idx]
								break
						reduced["forecast"] = dict()
						print("getreducedinfo omw7")
						for idx in range(6):  # collect forecast of today and next 5 days
							print("getreducedinfo omw8")
							reduced["forecast"][idx] = dict()
							pvdrCode = forecast["weathercode"][idx]
							reduced["forecast"][idx]["ProviderCode"] = str(pvdrCode)
							iconCode = self.convert2icon("OMW", pvdrCode)
							print("getreducedinfo omw9")
							if iconCode:
								print("getreducedinfo omw10")
								reduced["forecast"][idx]["yahooCode"] = iconCode.get("yahooCode", "NA")
								reduced["forecast"][idx]["meteoCode"] = iconCode.get("meteoCode", ")")
							print("getreducedinfo omw11")
							reduced["forecast"][idx]["minTemp"] = "%.0f" % forecast["temperature_2m_min"][idx]
							reduced["forecast"][idx]["maxTemp"] = "%.0f" % forecast["temperature_2m_max"][idx]
							reduced["forecast"][idx]["precipitation"] = "%.0f" % forecast["precipitation_probability_max"][idx]
							# currdate = datetime.fromisoformat(forecast["time"][idx])
							date_str = forecast["time"][idx]
							datetime_str = date_str + " 00:00:00"
							currdate = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
							# currdate=datetime_str
							reduced["forecast"][idx]["dayText"] = currdate.strftime(daytextfmt)
							reduced["forecast"][idx]["day"] = currdate.strftime("%A")
							reduced["forecast"][idx]["shortDay"] = currdate.strftime("%a")
							reduced["forecast"][idx]["date"] = currdate.strftime(datefmt)
							print("getreducedinfo omw11 ")
					except Exception as err:
						print("getreducedinfo omw12")
						self.error = "[%s] ERROR in module 'getreducedinfo#omw': general error. %s" % (MODULE_NAME, str(err))
						return
				else:
					print("getreducedinfo omw13")
					self.error = "[%s] ERROR in module 'getreducedinfo#omw': missing geodata." % MODULE_NAME
# ************************************************ OWM mit Api Key*************************************************************************
			elif self.parser is not None and self.mode == "owm":
				print("getreducedinfo owm api")
				if self.geodata:
					print("getreducedinfo owm api 1")
					try:
						reduced["forecast"] = dict()
						current = self.info["list"][0]  # collect current weather data
						reduced["source"] = "OpenWeatherMap"
						location = self.geodata[0].split(",")
						reduced["name"] = namefmt % (location[0].strip(), location[1].strip()) if len(location) > 1 else location[0].strip()
						reduced["longitude"] = str(self.info["city"]["coord"]["lon"])
						reduced["latitude"] = str(self.info["city"]["coord"]["lat"])
						reduced["tempunit"] = " F" if self.units == "imperial" else " C"
						reduced["windunit"] = "mph" if self.units == "imperial" else "km/h"
						reduced["precunit"] = "%"
						reduced["current"] = dict()
						now = datetime.now()
						# isotime = datetime.now(timezone.utc).astimezone().isoformat()
						# Holen Sie sich die aktuelle Zeit im UTC-Format
						current_time = datetime.utcnow()

						# Konvertieren Sie die UTC-Zeit in die gewünschte Zeitzone (oder UTC-offset)
						# Hier verwenden wir eine feste Verschiebung von 0 Stunden und 0 Minuten (00:00).
						offset = timedelta(hours=2, minutes=0)
						localized_time = current_time + offset
						# Setzen Sie die Minuten auf 0, um immer volle Stunden zu haben
						localized_time = localized_time.replace(minute=0)
						# Formatieren Sie das Datum und die Uhrzeit in der gewünschten Zeichenfolge
						isotime = localized_time.strftime("%Y-%m-%dT%H:%M")
						reduced["current"]["observationPoint"] = self.geodata[0]
						reduced["current"]["observationTime"] = "%s%s" % (isotime[: 19], isotime[26:])

						# alten befehle
						# reduced["current"]["sunrise"] = datetime.fromtimestamp(self.info["city"]["sunrise"]).astimezone().isoformat()
						# Zeitverschiebung in Stunden (zum Beispiel: UTC+2)
						timezone_offset = timedelta(hours=2)

						# Sonnenaufgangszeit in Sekunden seit dem Unix-Epoch-Zeitstempel
						sunrise_timestamp = self.info["city"]["sunrise"]
						# Konvertiere den Zeitstempel in ein Datumsobjekt
						sunrise_datetime = datetime.fromtimestamp(sunrise_timestamp)
						# Füge die Zeitverschiebung hinzu, um die Zeitzone zuzuweisen
						# sunrise_datetime = sunrise_datetime + timezone_offset
						# Konvertiere das Datumsobjekt in das ISO-Format
						reduced["current"]["sunrise"] = sunrise_datetime.isoformat()

						# Sonnenuntergangszeit in Sekunden seit dem Unix-Epoch-Zeitstempel
						sunset_timestamp = self.info["city"]["sunset"]
						# Konvertiere den Zeitstempel in ein Datumsobjekt
						sunset_datetime = datetime.fromtimestamp(sunset_timestamp)
						# Füge die Zeitverschiebung hinzu, um die Zeitzone zuzuweisen
						# sunset_datetime = sunset_datetime + timezone_offset
						# Konvertiere das Datumsobjekt in das ISO-Format
						reduced["current"]["sunset"] = sunset_datetime.isoformat()
						sunrise = datetime.fromtimestamp(self.info["city"]["sunrise"])
						sunset = datetime.fromtimestamp(self.info["city"]["sunset"])
						# Setzen Sie reduced["current"]["isNight"] basierend auf der aktuellen Zeit
						reduced["current"]["isNight"] = now < sunrise or now > sunset

						pvdrCode = current["weather"][0]["id"]
						reduced["current"]["ProviderCode"] = str(pvdrCode)
						iconCode = self.convert2icon("OWM", pvdrCode)
						if iconCode:
							reduced["current"]["yahooCode"] = iconCode.get("yahooCode", "NA")
							reduced["current"]["meteoCode"] = iconCode.get("meteoCode", ")")
						reduced["current"]["temp"] = "%.0f" % current["main"]["temp"]
						reduced["current"]["feelsLike"] = "%.0f" % current["main"]["feels_like"]
						reduced["current"]["humidity"] = "%.0f" % current["main"]["humidity"]
						reduced["current"]["windSpeed"] = "%.0f" % (current["wind"]["speed"] * 3.6)
						windDir = current["wind"]["deg"]
						reduced["current"]["windDir"] = str(windDir)
						reduced["current"]["windDirSign"] = self.directionsign(int(windDir))
						currdate = datetime.fromtimestamp(current["dt"])
						reduced["current"]["dayText"] = currdate.strftime(daytextfmt)
						reduced["current"]["day"] = currdate.strftime("%A")
						reduced["current"]["shortDay"] = currdate.strftime("%a")
						reduced["current"]["date"] = currdate.strftime(datefmt)
						reduced["current"]["text"] = current["weather"][0]["description"]
						tmin = 88  # inits for today
						tmax = -88
						yahoocode = None
						meteocode = None
						text = None
						idx = 0
						prec = []
						# reduced["forecast"] = dict()
						for forecast in self.info["list"]:  # collect forecast of today and next 5 days
							tmin = min(tmin, forecast["main"]["temp_min"])
							tmax = max(tmax, forecast["main"]["temp_max"])
							prec.append(forecast["pop"])
							if "15:00:00" in forecast["dt_txt"]:  # get weather icon as a representative icon for current day
								pvdrCode = forecast["weather"][0]["id"]
								iconCode = self.convert2icon("OWM", pvdrCode)
								if iconCode:
									yahoocode = iconCode.get("yahooCode", "NA")
									meteocode = iconCode.get("meteoCode", ")")
								text = forecast["weather"][0]["description"]
							if "18:00:00" in forecast["dt_txt"]:  # in case we call the forecast late today: get current weather icon
								pvdrCode = forecast["weather"][0]["id"]
								iconCode = self.convert2icon("OWM", pvdrCode)
								if iconCode:
									yahoocode = iconCode.get("yahooCode", "NA")
									meteocode = iconCode.get("meteoCode", ")")
								text = text if text else forecast["weather"][0]["description"]
							if "21:00:00" in forecast["dt_txt"]:  # last available data before daychange
								reduced["forecast"][idx] = dict()
								pvdrCode = forecast["weather"][0]["id"]
								reduced["forecast"][idx]["ProviderCode"] = str(pvdrCode)
								iconCode = self.convert2icon("OWM", pvdrCode)
								if iconCode:
									yahoocode = iconCode.get("yahooCode", "NA")
									meteocode = iconCode.get("meteoCode", ")")
								reduced["forecast"][idx]["yahooCode"] = yahoocode
								reduced["forecast"][idx]["meteoCode"] = meteocode
								reduced["forecast"][idx]["minTemp"] = "%.0f" % tmin
								reduced["forecast"][idx]["maxTemp"] = "%.0f" % tmax
								reduced["forecast"][idx]["precipitation"] = "%.0f" % (sum(prec) / len(prec) * 100) if len(prec) > 0 else ""
								currdate = datetime.fromtimestamp(forecast["dt"])
								reduced["forecast"][idx]["dayText"] = currdate.strftime(daytextfmt)
								reduced["forecast"][idx]["day"] = currdate.strftime("%A")
								reduced["forecast"][idx]["shortDay"] = currdate.strftime("%a")
								reduced["forecast"][idx]["date"] = currdate.strftime(datefmt)
								reduced["forecast"][idx]["text"] = text
								tmin = 88  # inits for next day
								tmax = -88
								prec = []
								yahoocode = None
								meteocode = None
								text = None
								idx += 1
							if idx == 5 and "21:00:00" in forecast["dt_txt"]:  # in case day #5 is missing: create a copy of day 4 (=fake)
								reduced["forecast"][idx] = dict()
								reduced["forecast"][idx]["yahooCode"] = yahoocode if yahoocode else reduced["forecast"][idx - 1]["yahooCode"]
								reduced["forecast"][idx]["meteoCode"] = meteocode if meteocode else reduced["forecast"][idx - 1]["meteoCode"]
								reduced["forecast"][idx]["minTemp"] = "%.0f" % tmin if tmin != 88 else reduced["forecast"][idx - 1]["minTemp"]
								reduced["forecast"][idx]["maxTemp"] = "%.0f" % tmax if tmax != - 88 else reduced["forecast"][idx - 1]["maxTemp"]
								reduced["forecast"][idx]["precipitation"] = "%.0f" % (sum(prec) / len(prec) * 100) if len(prec) > 0 else ""
								nextdate = datetime.strptime(reduced["forecast"][idx - 1]["date"], datefmt) + timedelta(1)
								reduced["forecast"][idx]["day"] = nextdate.strftime("%A")
								reduced["forecast"][idx]["shortDay"] = nextdate.strftime("%a")
								reduced["forecast"][idx]["date"] = nextdate.strftime(datefmt)
								reduced["forecast"][idx]["text"] = text if text else reduced["forecast"][idx - 1]["text"]
							elif idx == 5:  # in case day #5 is incomplete: use what we have
								reduced["forecast"][idx] = dict()
								if yahoocode:
									reduced["forecast"][idx]["yahooCode"] = yahoocode
								if meteocode:
									reduced["forecast"][idx]["meteoCode"] = meteocode
								reduced["forecast"][idx]["minTemp"] = "%.0f" % tmin if tmin != 88 else reduced["forecast"][idx - 1]["minTemp"]
								reduced["forecast"][idx]["maxTemp"] = "%.0f" % tmax if tmax != - 88 else reduced["forecast"][idx - 1]["maxTemp"]
								reduced["forecast"][idx]["precipitation"] = "%.0f" % (sum(prec) / len(prec) * 100) if len(prec) > 0 else ""
								nextdate = datetime.strptime(reduced["forecast"][idx - 1]["date"], datefmt) + timedelta(1)
								reduced["forecast"][idx]["day"] = nextdate.strftime("%A")
								reduced["forecast"][idx]["shortDay"] = nextdate.strftime("%a")
								reduced["forecast"][idx]["date"] = nextdate.strftime(datefmt)
								reduced["forecast"][idx]["text"] = text if text else reduced["forecast"][idx - 1]["text"]
						reduced["current"]["minTemp"] = reduced["forecast"][0]["minTemp"]  # add missing data for today
						reduced["current"]["maxTemp"] = reduced["forecast"][0]["maxTemp"]
						reduced["current"]["precipitation"] = reduced["forecast"][0]["precipitation"]
					except Exception as err:
						self.error = "[%s] 1083 ERROR in module 'getreducedinfo#owm': general error. %s" % (MODULE_NAME, str(err))
						return
				else:
					self.error = "[%s] 1086 ERROR in module 'getreducedinfo#owm': missing geodata." % MODULE_NAME

			else:
				self.error = "[%s] 1089 ERROR in module 'getreducedinfo': unknown source." % MODULE_NAME
				return
		print("getreducedinfo return")
		return reduced

	def writereducedjson(self, filename):
		print("writereducedjson")
		self.error = None
		reduced = self.getreducedinfo()
		if self.error is not None:
			return
		if reduced is None:
			self.error = "[%s] ERROR in module 'writereducedjson': no data found." % MODULE_NAME
			return
		with open(filename, "w") as f:
			dump(reduced, f)
		return filename

	def writejson(self, filename):
		print("writejson")
		self.error = None
		if self.info:
			try:
				with open(filename, "w") as f:
					dump(self.info, f)
			except Exception as err:
				self.error = "[%s] ERROR in module 'writejson': %s" % (MODULE_NAME, str(err))
		else:
			self.error = "[%s] ERROR in module 'writejson': no data found." % MODULE_NAME

	def getmsnxml(self):  # only MSN supported
		print("getmsnxml")
		self.error = None
		if self.geodata and self.info:
			try:
				datefmt = "%Y-%m-%d"
				source = self.info["responses"][0]["source"]
				current = self.info["responses"][0]["weather"][0]["current"]
				forecast = self.info["responses"][0]["weather"][0]["forecast"]["days"]
				root = Element("weatherdata")
				root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
				root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
				w = Element("weather")
				location = self.geodata[0].split(",")
				locationname = "%s, %s" % (location[0], location[1]) if len(location) > 1 else location[0]
				w.set("weatherlocationname", locationname)
				w.set("degreetype", self.info["units"]["temperature"])
				w.set("long", "%.3f" % source["coordinates"]["lon"])
				w.set("lat", "%.3f" % source["coordinates"]["lat"])
				w.set("timezone", str(int(source["location"]["TimezoneOffset"][: 2])))
				w.set("alert", ", ".join(self.info["responses"][0]["weather"][0]["alerts"]))
				w.set("encodedlocationname", locationname.encode("ascii", "xmlcharrefreplace").decode().replace(" ", "%20").replace("\n", "").strip())
				root.append(w)
				c = Element("current")
				c.set("temperature", "%.0f" % current["temp"])
				iconCode = self.convert2icon("MSN", current["symbol"])
				c.set("yahoocode", iconCode.get("yahooCode", "NA") if iconCode else "NA")
				c.set("meteocode", iconCode.get("meteoCode", ")") if iconCode else ")")
				c.set("skytext", forecast[0]["hourly"][0]["pvdrCap"] if forecast[0]["hourly"] else current["capAbbr"])
				print("getmsnxml 1")
				currdate = datetime.fromisoformat(current["created"])
				print("getmsnxml 2")
				c.set("date", currdate.strftime(datefmt))
				c.set("observationtime", currdate.strftime("%X"))
				c.set("observationpoint", source["location"]["Name"])
				c.set("feelslike", "%.0f" % current["feels"])
				c.set("humidity", "%.0f" % current["rh"])
				c.set("winddisplay", "%s %s %s" % ("%.0f" % current["windSpd"], self.info["units"]["speed"], self.directionsign(current["windDir"])[2:]))
				c.set("day", currdate.strftime("%A"))
				c.set("shortday", currdate.strftime("%a"))
				c.set("windspeed", "%s %s" % ("%.0f" % current["windSpd"], self.info["units"]["speed"]))
				c.set("precip", "%.0f" % forecast[0]["daily"]["day"]["precip"])
				w.append(c)
				for idx in range(6):  # collect forecast of today and next 5 days
					f = Element("forecast")
					f.set("low", "%.0f" % forecast[idx]["daily"]["tempLo"])
					f.set("high", "%.0f" % forecast[idx]["daily"]["tempHi"])
					iconCodes = self.convert2icon("MSN", forecast[idx]["daily"]["symbol"])
					f.set("yahoocodeday", iconCodes.get("yahooCode", "NA") if iconCodes else "NA")
					f.set("meteocodeday", iconCodes.get("meteoCode", ")") if iconCodes else ")")
					f.set("skytextday", forecast[idx]["daily"]["pvdrCap"])
					f.set("date", currdate.strftime(datefmt))
					f.set("day", currdate.strftime("%A"))
					f.set("shortday", currdate.strftime("%a"))
					f.set("precip", "%.0f" % forecast[idx]["daily"]["day"]["precip"])
					w.append(f)
				return root
			except Exception as err:
				self.error = "[%s] ERROR in module 'getmsnxml': general error. %s" % (MODULE_NAME, str(err))
		else:
			self.error = "[%s] ERROR in module 'getmsnxml': missing weather or geodata." % MODULE_NAME

	def writemsnxml(self, filename):  # only MSN supported
		print("writemsnxml")
		self.error = None
		xmlData = self.getmsnxml()
		if xmlData:
			xmlString = tostring(xmlData, encoding="utf-8", method="html")
			try:
				with open(filename, "wb") as f:
					f.write(xmlString)
			except OSError as err:
				self.error = "[%s] ERROR in module 'writemsnxml': %s" % (MODULE_NAME, str(err))

	def getinfo(self):
		print("getinfo")
		self.error = None
		if self.info is None:
			self.error = "[%s] ERROR in module 'getinfo': Parser not ready" % MODULE_NAME
			return
		return self.info

	def showDescription(self, src):
		print("showdescription")
		self.error = None
		src = src.lower()
		selection = {"msn": self.msnDescs, "owm": self.owmDescs, "omw": self.omwDescs, "yahoo": self.yahooDescs, "meteo": self.meteoDescs}
		if src is not None and src in selection:
			descs = selection[src]
		else:
			self.error = "[%s] ERROR in module 'showDescription': convert source '%s' is unknown. Valid is: %s" % (MODULE_NAME, src, SOURCES)
			return self.error
		# print("\n+%s+" % ("-" * 39))
		# print("| {0:<5}{1:<32} |".format("CODE", "DESCRIPTION_%s (COMPLETE)" % src.upper()))
		# print("+%s+" % ("-" * 39))
		for desc in descs:
			print("| {0:<5}{1:<32} |".format(desc, descs[desc]))
		print("+%s+" % ("-" * 39))

	def showConvertrules(self, src, dest):
		print("showConvertrules")
		self.error = None
		src = src.lower()
		dest = dest.lower()
		if not src:
			self.error = "[%s] ERROR in module 'showConvertrules': convert source '%s' is unknown. Valid is: %s" % (MODULE_NAME, src, SOURCES)
			return self.error
		selection = {"meteo": self.meteoDescs, "yahoo": self.yahooDescs}
		if dest in selection:
			ddescs = selection[dest]
			destidx = DESTINATIONS.index(dest)
		else:
			self.error = "[%s] ERROR in module 'showConvertrules': convert destination '%s' is unknown. Valid is: %s" % (MODULE_NAME, src, DESTINATIONS)
			return self.error
		print("\n+%s+%s+" % ("-" * 39, "-" * 32))
		selection = {"msn": self.msnCodes, "omw": self.omwCodes, "owm": self.owmCodes}
		if src in selection:
			sCodes = selection[src]
			row = "| {0:<5}{1:<32} | {2:<5}{3:<25} |"
			# print(row.format("CODE", "DESCRIPTION_%s (CONVERTER)" % src.upper(), "CODE", "DESCRIPTION_%s" % dest.upper()))
			# print("+%s+%s+" % ("-" * 39, "-" * 32))
			if src == "msn":
				for scode in sCodes:
					dcode = sCodes[scode][destidx]
					print(row.format(scode, self.msnDescs[scode], dcode, ddescs[dcode]))
			elif src == "omw":
				for scode in self.omwCodes:
					dcode = self.omwCodes[scode][destidx]
					print(row.format(scode, self.omwDescs[scode], dcode, ddescs[dcode]))
			elif src == "owm":
				for scode in self.owmCodes:
					dcode = self.owmCodes[scode][destidx]
					print(row.format(scode, self.owmDescs[scode], dcode, ddescs[dcode]))
			print("+%s+%s+" % ("-" * 39, "-" * 32))
		else:
			self.error = "[%s] ERROR in module 'showConvertrules': convert source '%s' is unknown. Valid is: %s" % (MODULE_NAME, src, SOURCES)
			return self.error


def main(argv):
	print("main")
	mainfmt = "[__main__]"
	cityname = ""
	units = "metric"
	scheme = "de-de"
	mode = "msn"
	apikey = None
	quiet = False
	json = None
	reduced = False
	xml = None
	specialopt = None
	control = False
	cityID = None
	geodata = None
	info = None
	geodata = ("", 0, 0)
	helpstring = "Weatherinfo v2.0: try 'python Weatherinfo.py -h' for more information"
	args = None

	parser = argparse.ArgumentParser(description=helpstring)
	parser.add_argument("cityname", nargs='?', help="Name der Stadt")
	parser.add_argument("--units", choices=["metric", "imperial"], default="metric", help="Einheitensystem (metric oder imperial)")
	parser.add_argument("--scheme", choices=["de-de", "en-us"], default="de-de", help="Sprachschema (de-de oder en-us)")
	parser.add_argument("--mode", choices=["msn", "other_mode"], default="msn", help="Wetterdienst-Modus (msn oder other_mode)")
	parser.add_argument("--apikey", help="API-Schluessel fuer den Wetterdienst")
	parser.add_argument("--quiet", action="store_true", help="Deaktiviere alle Konsolenausgaben, ausser Fehlermeldungen")
	parser.add_argument("--json", help="JSON-Ausgabedatei fuer die Wetterdaten")
	parser.add_argument("--reduced", action="store_true", help="Reduziere die Wetterdaten auf eine kompakte Form")
	parser.add_argument("--xml", help="XML-Ausgabedatei fuer die Wetterdaten")
	parser.add_argument("--specialopt", help="Spezielle Option fuer den Wetterdienst")
	parser.add_argument("--control", action="store_true", help="Wetterdienst-Steuerungsfunktion aktivieren")
	parser.add_argument("--cityID", help="Stadt-ID fuer den Wetterdienst")
	parser.add_argument("--geodata", nargs=3, metavar=("NAME", "LAT", "LON"), help="Geodaten (Name, Breitengrad, Laengengrad) der Stadt")
	args = parser.parse_args(argv)

	cityname = args.cityname
	units = args.units
	scheme = args.scheme
	mode = args.mode
	apikey = args.apikey
	quiet = args.quiet
	reduced = args.reduced
	specialopt = args.specialopt
	control = args.control
	cityID = args.cityID
	geodata = args.geodata
	print("geodata")
	print(str(geodata))

	for part in args:
		print("main 2")
		cityname += "%s " % part
	cityname = cityname.strip()
	print("main 2a")
	if len(cityname) < 3 and not specialopt:
		print("ERROR: Cityname is missing or too short, please use at least 3 letters!")
		exit()
	if len(args) == 0 and not specialopt:
		print(helpstring)
		exit()
	WI = Weatherinfo(mode, apikey)
	print("main 3")
	if control:
		for src in SOURCES + DESTINATIONS:
			if WI.showDescription(src):
				print(WI.error.replace(mainfmt, "").strip())
		for src in SOURCES:
			for dest in DESTINATIONS:
				WI.showConvertrules(src, dest)
	print("main 4")
	if WI.error:
		print(WI.error.replace(mainfmt, "").strip())
		exit()
	if cityname:
		citylist = WI.getCitylist(cityname, scheme)
		if WI.error:
			print(WI.error.replace(mainfmt, "").strip())
			exit()
		if len(citylist) == 0:
			print("No city '%s' found on the server. Try another wording." % cityname)
			exit()
		geodata = citylist[0]
		if citylist and len(citylist) > 1 and not quiet:
			print("Found the following cities/areas:")
			for idx, item in enumerate(citylist):
				lon = " [lon=%s" % item[1] if item[1] != 0.0 else ""
				lat = ", lat=%s]" % item[2] if item[2] != 0.0 else ""
				print("%s = %s%s%s" % (idx + 1, item[0], lon, lat))
			choice = input("Select (1-%s)? : " % len(citylist))[: 1]
			index = ord(choice) - 48 if len(choice) > 0 else -1
			if index > 0 and index < len(citylist) + 1:
				geodata = citylist[index - 1]
			else:
				print("Choice '%s' is not allowable (only numbers 1 to %s are valid).\nPlease try again." % (choice, len(citylist)))
				exit()
	if not specialopt:
		if geodata:
			info = WI.start(geodata=geodata, units=units, scheme=scheme)  # INTERACTIVE CALL (unthreaded)
		elif cityID:
			info = WI.start(cityID=cityID, units=units, scheme=scheme)  # INTERACTIVE CALL (unthreaded)
		else:
			print("ERROR: missing cityname or geodata or cityid.")
			exit()
	if WI.error:
		print(WI.error.replace(mainfmt, "").strip())
		exit()

	if info is not None and not control:
		if not quiet:
			print("Using city/area: %s [lon=%s, lat=%s]" % (geodata[0], geodata[1], geodata[2]))
		successtext = "File '%s' was successfully created."
		if json:
			WI.writejson(json)
			if not quiet and not WI.error:
				print(successtext % json)
		if reduced:
			WI.writereducedjson(reduced)
			if not quiet:
				print(successtext % reduced)
		if xml:
			if mode == "msn":
				WI.writemsnxml(xml)
				if not quiet and not WI.error:
					print(successtext % xml)
			else:
				print("ERROR: XML is only supported in mode 'msn'.\nFile '%s' was not created..." % xml)
	if WI.error:
		print(WI.error.replace(mainfmt, "").strip())


if __name__ == "__main__":
	main(sys.argv[1:])
