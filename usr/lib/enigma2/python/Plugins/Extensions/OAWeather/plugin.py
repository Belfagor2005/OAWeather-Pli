# -*- coding: utf-8 -*-

from __future__ import print_function

# Copyright (C) 2023 jbleyel, Mr.Servo, Stein17
#
# OAWeather is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# dogtag is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OAWeather.  If not, see <https://www.gnu.org/licenses/>.

# Some parts are taken from MetrixHD skin and MSNWeather Plugin.
# mod by lululla 20250629
# fix asiatic language and icons 20250706

import json
import logging
import pickle
import sys
from datetime import datetime, timedelta
from time import time
from xml.etree.ElementTree import parse, tostring

from os import fsync, listdir, remove  # , stat
from os.path import exists, getmtime, isfile, join, dirname, isdir, islink

import tempfile

from twisted.internet.reactor import callInThread

from keymapparser import readKeymap

from enigma import eTimer, getDesktop

from Components.ActionMap import ActionMap, HelpableActionMap
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.config import (
	config,
	getConfigListEntry,
	ConfigSubsection,
	ConfigYesNo,
	ConfigSelection,
	ConfigSelectionNumber,
	ConfigText
)

from Plugins.Plugin import PluginDescriptor

from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.VirtualKeyBoard import VirtualKeyBoard

from Tools.Directories import SCOPE_CONFIG, SCOPE_HDD, SCOPE_PLUGINS, resolveFilename
from Tools.LoadPixmap import LoadPixmap
from Tools.Weatherinfo import Weatherinfo


if sys.version_info[0] >= 3:
	from Tools.Directories import SCOPE_SKINS
else:
	from Tools.Directories import SCOPE_SKIN

from . import __version__, _

screenwidth = getDesktop(0).size()

MODULE_NAME = "OAWeather"
CACHEFILE = resolveFilename(SCOPE_CONFIG, "OAWeather.dat")
PLUGINPATH = join(resolveFilename(SCOPE_PLUGINS), 'Extensions/OAWeather')
logger = logging.getLogger(MODULE_NAME)

config.plugins.OAWeather = ConfigSubsection()
config.plugins.OAWeather.enabled = ConfigYesNo(default=False)
ICONSETS = [("", _("Default"))]

if sys.version_info[0] >= 3:
	ICONSETROOT = join(resolveFilename(SCOPE_SKINS), "WeatherIconSets")
else:
	ICONSETROOT = join(resolveFilename(SCOPE_SKIN), "WeatherIconSets")

if exists(ICONSETROOT):
	for iconset in listdir(ICONSETROOT):
		if isfile(join(ICONSETROOT, iconset, "0.png")):
			ICONSETS.append((iconset, iconset))

config.plugins.OAWeather.iconset = ConfigSelection(default="", choices=ICONSETS)
config.plugins.OAWeather.nighticons = ConfigYesNo(default=True)
config.plugins.OAWeather.cachedata = ConfigSelection(default=0, choices=[(0, _("Disabled"))] + [(x, _("%d Minutes") % x) for x in (30, 60, 120)])
config.plugins.OAWeather.refreshInterval = ConfigSelectionNumber(0, 1440, 30, default=120, wraparound=True)
config.plugins.OAWeather.apikey = ConfigText(default="", fixed_size=False)

GEODATA = ("Frankfurt am Main, DE", "8.68417,50.11552")
config.plugins.OAWeather.weathercity = ConfigText(default=GEODATA[0], visible_width=250, fixed_size=False)
config.plugins.OAWeather.owm_geocode = ConfigText(default=GEODATA[1])

config.plugins.OAWeather.detailLevel = ConfigSelection(default="default", choices=[("default", _("More Details / Smaller font")), ("reduced", _("Less details / Larger font"))])
config.plugins.OAWeather.tempUnit = ConfigSelection(default="Celsius", choices=[("Celsius", _("Celsius")), ("Fahrenheit", _("Fahrenheit"))])
config.plugins.OAWeather.windspeedMetricUnit = ConfigSelection(default="km/h", choices=[("km/h", _("km/h")), ("m/s", _("m/s"))])
config.plugins.OAWeather.trendarrows = ConfigYesNo(default=True)
config.plugins.OAWeather.weatherservice = ConfigSelection(default="MSN", choices=[("MSN", _("MSN weather")), ("OpenMeteo", _("Open-Meteo Wetter")), ("openweather", _("OpenWeatherMap"))])
config.plugins.OAWeather.debug = ConfigYesNo(default=False)


def setup_logging():
	# log_file = "/tmp/OAWeather.log"
	log_file = "/home/root/.oaweather/OAWeather.txt"
	log_level = logging.DEBUG if config.plugins.OAWeather.debug.value else logging.INFO

	logger.setLevel(log_level)
	handler = logging.FileHandler(log_file)
	formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	logger.addHandler(handler)

	console_handler = logging.StreamHandler()
	console_handler.setFormatter(formatter)
	logger.addHandler(console_handler)

	logger.info("OAWeather logging initialized")


setup_logging()


def get_safe_tmp_file(filename):
	tmp_dir = tempfile.gettempdir()
	path = join(tmp_dir, filename)

	if exists(path) and islink(path):
		raise RuntimeError("Unsafe fallback file: symlink detected")

	return path


class WeatherHelper():
	def __init__(self):
		self.version = __version__
		self.favoritefile = self.get_writable_path("oaweather_fav.json")
		logger.info(f"Using favorite file: {self.favoritefile}")
		self.locationDefault = ("Frankfurt am Main, DE", 8.68417, 50.11552)
		self.favoriteList = []
		self.readFavoriteList()
		self.syncWithConfig()

	def syncWithConfig(self):
		current_city = config.plugins.OAWeather.weathercity.value
		if current_city and current_city != self.locationDefault[0]:
			found = False
			for fav in self.favoriteList:
				if fav[0] == current_city:
					found = True
					break

			if not found:
				try:
					lon, lat = config.plugins.OAWeather.owm_geocode.value.split(",")
					self.addFavorite((current_city, float(lon), float(lat)))
				except:
					logger.warning("Could not sync existing city configuration")

	def get_writable_path(self, filename):
		paths_to_try = [
			resolveFilename(SCOPE_CONFIG, filename),
			resolveFilename(SCOPE_HDD, filename),
			join(tempfile.gettempdir(), filename),
		]

		for path in paths_to_try:
			try:
				dir_path = dirname(path)
				if not isdir(dir_path):
					continue

				if exists(path) and islink(path):
					continue

				import os
				fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
				os.close(fd)
				return path
			except Exception:
				continue

		return None

	def setFavoriteList(self, favoriteList):
		self.favoriteList = favoriteList
		self.saveFavorites()

	def saveFavorites(self):
		try:
			logger.info("Saving {} favorites to {}".format(len(self.favoriteList), self.favoritefile))
			with open(self.favoritefile, "w") as fd:
				json.dump(self.favoriteList, fd, indent=2, ensure_ascii=False)
				fd.flush()
				fsync(fd.fileno())

			logger.info("Favorites saved successfully")
			self.updateConfigChoices()

		except Exception as e:
			logger.error("Error saving favorites: {}".format(str(e)))

			try:
				fallback = get_safe_tmp_file("oaweather_fav.json")
				with open(fallback, "w") as fd:
					json.dump(self.favoriteList, fd, indent=2, ensure_ascii=False)
					fd.flush()
					fsync(fd.fileno())
				logger.info("Saved to fallback location: {}".format(fallback))
			except Exception as e2:
				logger.error("Fallback save failed: {}".format(str(e2)))

	def updateConfigChoices(self):
		try:
			if hasattr(config.plugins, 'OAWeather'):
				choices = []
				for item in self.favoriteList:
					city_name = item[0].split(",")[0].strip()
					choices.append((item, city_name))

				config.plugins.OAWeather.weatherlocation.setChoices(choices)

				current_val = config.plugins.OAWeather.weatherlocation.value
				if not current_val or current_val not in [c[0] for c in choices]:
					if choices:
						config.plugins.OAWeather.weatherlocation.value = choices[0][0]

				logger.info("Updated config choices")
		except Exception as e:
			logger.error(f"Error updating config choices: {str(e)}")

	def readFavoriteList(self):
		if exists(self.favoritefile):
			try:
				with open(self.favoritefile, "r") as file:
					self.favoriteList = json.load(file)

				if not self.favoriteList or not isinstance(self.favoriteList, list):
					raise ValueError("Invalid favorite list format")

				logger.info(f"Loaded {len(self.favoriteList)} favorites from JSON")
			except json.JSONDecodeError:
				try:
					with open(self.favoritefile, "rb") as file:
						self.favoriteList = pickle.load(file)
					logger.info(f"Loaded {len(self.favoriteList)} favorites from pickle")

					self.saveFavorites()
				except Exception as e:
					logger.error(f"Error loading favorites: {e}")
					self.favoriteList = [self.locationDefault]
					self.saveFavorites()
			except Exception as e:
				logger.error(f"Error loading favorites: {e}")

				self.favoriteList = [self.locationDefault]
				self.saveFavorites()
		else:
			logger.info("Favorite file not found, creating default")
			self.favoriteList = [self.locationDefault]
			self.saveFavorites()

		self.updateConfigChoices()

	def addFavorite(self, location):
		name, lon, lat = location
		normalized = (str(name).strip(), float(lon), float(lat))
		for i, fav in enumerate(self.favoriteList):
			if not self.isDifferentLocation(normalized, fav):
				if len(normalized[0]) > len(fav[0]):
					self.favoriteList[i] = normalized
					logger.info(f"Updated favorite: {name}")
					self.saveFavorites()
				return False

		logger.info(f"Adding new favorite: {name}")
		self.favoriteList.append(normalized)

		# Update config if this is the current location
		if config.plugins.OAWeather.weatherlocation.value == normalized:
			config.plugins.OAWeather.weathercity.value = name
			config.plugins.OAWeather.owm_geocode.value = f"{lon},{lat}"
			config.plugins.OAWeather.weathercity.save()
			config.plugins.OAWeather.owm_geocode.save()

		self.saveFavorites()
		return True

	def returnFavoriteChoice(self, favorite):
		if favorite is not None:
			selected_location = favorite[1]
			logger.info(f"Selected location: {selected_location[0]}")

			# Add to favorites if not already present
			weatherhelper.addFavorite(selected_location)

			# Update the current location in config
			config.plugins.OAWeather.weatherlocation.value = selected_location
			config.plugins.OAWeather.weatherlocation.save()

			# Update the city name and geocode in config
			config.plugins.OAWeather.weathercity.value = selected_location[0]
			config.plugins.OAWeather.owm_geocode.value = f"{selected_location[1]},{selected_location[2]}"
			config.plugins.OAWeather.weathercity.save()
			config.plugins.OAWeather.owm_geocode.save()

			logger.info(f"Current location set to: {selected_location[0]}")
			callInThread(weatherhandler.reset, selected_location, self.configFinished)

	def reduceCityname(self, weathercity):
		components = list(dict.fromkeys(weathercity.split(', ')))
		len_components = len(components)
		if len_components > 2:
			return (f"{components[0]}, {components[1]}, {components[-1]}")
		return (f"{components[0]}, {components[1]}") if len_components == 2 else (f"{components[0]}")

	def isolateCityname(self, weathercity):
		return weathercity.split(",")[0]

	def isDifferentLocation(self, geodata1, geodata2):
		try:
			x, lon1, lat1 = geodata1
			x, lon2, lat2 = geodata2

			distance = ((lon1 - lon2)**2 + (lat1 - lat2)**2)**0.5
			return distance > 0.02
		except:
			return True

	def convertOldLocation(self):  # deprecated: will be removed at end of 2025
		if config.plugins.OAWeather.owm_geocode.value and config.plugins.OAWeather.weathercity.value:
			if config.plugins.OAWeather.weatherlocation.value == config.plugins.OAWeather.weatherlocation.default:
				weathercity = config.plugins.OAWeather.weathercity.value
				lon, lat = eval(str(config.plugins.OAWeather.owm_geocode.value))
				config.plugins.OAWeather.weatherlocation.value = (weathercity, lon, lat)
				config.plugins.OAWeather.weatherlocation.save()
			# remove old entries from '/etc/enigma2/settings'
			config.plugins.OAWeather.owm_geocode.value = config.plugins.OAWeather.owm_geocode.default
			config.plugins.OAWeather.owm_geocode.save()
			config.plugins.OAWeather.weathercity.value = config.plugins.OAWeather.weathercity.default
			config.plugins.OAWeather.weathercity.save()

	def loadSkin(self, skinName=""):
		params = {"picpath": join(PLUGINPATH, "Images")}
		skintext = ""
		xml = parse(join(PLUGINPATH, "skin.xml")).getroot()
		for screen in xml.findall('screen'):
			if screen.get("name") == skinName:
				skintext = tostring(screen).decode()
				for key in params.keys():
					try:
						skintext = skintext.replace('{%s}' % key, params[key])
					except Exception as e:
						print("%s@key=%s" % (str(e), key))
				break
		return skintext


weatherhelper = WeatherHelper()
weatherhelper.readFavoriteList()
choiceList = [(item, item[0]) for item in weatherhelper.favoriteList]
config.plugins.OAWeather.weatherlocation = ConfigSelection(default=weatherhelper.locationDefault, choices=[])
weatherhelper.updateConfigChoices()


class WeatherSettingsViewNew(ConfigListScreen, Screen):

	def __init__(self, session):
		self.session = session
		skintext = ""
		xml = parse(join(PLUGINPATH, "skinconfig.xml")).getroot()
		for screen in xml.findall('screen'):
			if screen.get("name") == "WeatherSettingsViewNew":
				skintext = tostring(screen).decode()
		self.skin = skintext
		Screen.__init__(self, session)
		self.setTitle(_('Setup'))
		self.status = ""
		self["status"] = Label()
		Neue_keymap = '/usr/lib/enigma2/python/Plugins/Extensions/OAWeather/keymap.xml'
		readKeymap(Neue_keymap)

		self.onChangedEntry = []
		self.list = []
		ConfigListScreen.__init__(self, self.list, session=self.session, on_change=self.changedEntry)

		self["key_green"] = StaticText(_("Save"))
		self["key_blue"] = StaticText()
		self["key_yellow"] = StaticText(_("Defaults"))
		self["key_red"] = StaticText(_("Location Selection"))
		self["blueActions"] = HelpableActionMap(
			self,
			["ColorActions", "OkCancelActions", "OAWeatherActions"],
			{
				"ok": self.keyOK,
				"left": self.keyLeft,
				"right": self.keyRight,
				"cancel": self.close,
				"green": self.keySave,
				"red": self.keycheckCity,
				"yellow": self.defaults
			},
			-1
		)
		self.createSetup()

		self.old_weatherservice = config.plugins.OAWeather.weatherservice.value
		self.citylist = []
		self.checkcity = False
		self.closeonsave = False

	def createSetup(self):
		self.editListEntry = None
		self.list = []
		self.list.append(getConfigListEntry(_("Enabled :"), config.plugins.OAWeather.enabled))
		if config.plugins.OAWeather.enabled.value:
			self.list.append(getConfigListEntry(_("Weather service :"), config.plugins.OAWeather.weatherservice))
			self.list.append(getConfigListEntry(_("Weather city name :"), config.plugins.OAWeather.weathercity))
			self.list.append(getConfigListEntry(_("Weather API key :"), config.plugins.OAWeather.apikey))
			self.list.append(getConfigListEntry(_("Temperature unit :"), config.plugins.OAWeather.tempUnit))
			self.list.append(getConfigListEntry(_("Wind speed metric unit:"), config.plugins.OAWeather.windspeedMetricUnit))
			self.list.append(getConfigListEntry(_("Weather icon set :"), config.plugins.OAWeather.iconset))
			self.list.append(getConfigListEntry(_("Weather icon night switch :"), config.plugins.OAWeather.nighticons))
			self.list.append(getConfigListEntry(_("Refresh interval :"), config.plugins.OAWeather.refreshInterval))
			self.list.append(getConfigListEntry(_("Cache data :"), config.plugins.OAWeather.cachedata))
			self.list.append(getConfigListEntry(_("Enable Debug :"), config.plugins.OAWeather.debug))
		self['config'].list = self.list
		self['config'].l.setList(self.list)

	def keyOK(self):
		current_item = self['config'].getCurrent()
		if current_item:
			item_text = current_item[0]
			if item_text == _("Weather city name :"):
				# Code für Weather city name Einstellung
				title = _('Please enter a valid city name.')
				self.session.openWithCallback(self.VirtualKeyBoardCallBack, VirtualKeyBoard, title=title)

			elif item_text == _("Weather API key :"):
				text = current_item[1].value

				if text == config.plugins.OAWeather.apikey.value:
					title = _('Please enter a valid city name.')
					self.session.openWithCallback(self.VirtualKeyBoardCallBack, VirtualKeyBoard, title=title)

	def VirtualKeyBoardCallBack(self, callback):
		try:
			if callback:
				self['config'].getCurrent()[1].value = callback
		except:
			pass

	def keycheckCity(self, closesave=False):
		weathercity = config.plugins.OAWeather.weathercity.value.split(",")[0]
		# self.["footnote"].setText(_("Search for City ID please wait..."))
		self.closeonsave = closesave
		callInThread(self.searchCity, weathercity)

	def searchCity(self, weathercity):
		services = {"MSN": "msn", "OpenMeteo": "omw", "openweather": "owm"}
		service = services.get(config.plugins.OAWeather.weatherservice.value, "msn")
		apikey = config.plugins.OAWeather.apikey.value
		if service == "owm" and len(apikey) < 32:
			self.session.open(MessageBox, text=_("The API key for OpenWeatherMap is not defined or invalid.\nPlease verify your input data.\nOtherwise your settings won't be saved."), type=MessageBox.TYPE_WARNING)
		else:
			WI = Weatherinfo(service, config.plugins.OAWeather.apikey.value)
			if WI.error:
				print("[WeatherSettingsViewNew] Error in module 'searchCity': %s" % WI.error)
				# self["footnote"].setText(_("Error in Weatherinfo"))
				self.session.open(MessageBox, text=WI.error, type=MessageBox.TYPE_ERROR)
			else:
				# Den Wert von config.osd.language.value in eine separate Variable setzen
				language_value = config.osd.language.value
				weathercity = str(weathercity)
				language_value = config.osd.language.value.replace('_', '-').lower()
				geodatalist = WI.getCitylist(weathercity, language_value)
				# geodatalist = WI.getCitylist(weathercity, config.osd.language.value.replace('_', '-').lower())
				if WI.error or geodatalist is None or len(geodatalist) == 0:
					print("[WeatherSettingsViewNew] Error in module 'searchCity': %s" % WI.error)
					# self["footnote"].setText(_("Error getting City ID"))
					self.session.open(MessageBox, text=_("City '%s' not found! Please try another wording." % weathercity), type=MessageBox.TYPE_WARNING)
				# elif len(geodatalist) == 1:
					# self["footnote"].setText(_("Getting City ID Success"))
					# self.saveGeoCode(geodatalist[0])
				else:
					self.citylist = []
					for item in geodatalist:
						lon = " [lon=%s" % item[1] if float(item[1]) != 0.0 else ""
						lat = ", lat=%s]" % item[2] if float(item[2]) != 0.0 else ""
						try:
							# self.citylist.append(("%s%s%s" % (item[0], lon, lat), item[0], item[1], item[2]))
							self.citylist.append((str(item[0]) + lon + lat, str(item[0]), str(item[1]), str(item[2])))
						except Exception:
							print("[WeatherSettingsViewNew] Error in module 'showMenu': faulty entry in resultlist.")

					# --------------------- hier ist der alte aufruf der choicebox
					# self.session.openWithCallback(self.returnCityChoice, ChoiceBox, title=_("Select your location"), list=tuple(answer[1]))
					self.citylisttest = self.citylist
					self.testScreen = self.session.open(TestScreen, citylisttest=self.citylisttest, okCallback=self.testScreenOkCallback)
					# selected_city_str = self.selected_city
					# self.choiceIdxCallback(self.test_screen.selectCity())

	def testScreenOkCallback(self, selected_city_str):
		self.choiceIdxCallback(selected_city_str)

	def choiceIdxCallback(self, selected_city):
		self.selected_city = selected_city

		if len(self.selected_city) >= 4:
			parts = self.selected_city.split(',')
			city = parts[0]
			longitude = ""
			latitude = ""
			for part in parts:
				if 'lon=' in part:
					longitude = part.split('=')[1].strip()
				elif 'lat=' in part:
					latitude = part.split('=')[1].strip((']'))

			if city and longitude and latitude:
				self.saveGeoCode(city, longitude, latitude)
		else:
			logger.info("Die ausgewählte Stadt hat nicht genügend Informationen.")

	def saveGeoCode(self, city, longitude, latitude):
		config.plugins.OAWeather.weathercity.value = city
		config.plugins.OAWeather.owm_geocode.value = "%s,%s" % (longitude, latitude)

		self.old_weatherservice = config.plugins.OAWeather.weatherservice.value
		self.checkcity = False
		if self.closeonsave:
			config.plugins.OAWeather.owm_geocode.save()
			weatherhandler.reset()
			# Setup.keySave(self)
			self.keySave()

	def changedEntry(self):
		for x in self.onChangedEntry:
			x()

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.createSetup()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.createSetup()

	def keySelect(self):
		if self.getCurrentItem() == config.plugins.OAWeather.weathercity:
			self.checkcity = True
		Setup.keySelect(self)

	def keySave(self):
		weathercity = config.plugins.OAWeather.weathercity.value.split(",")[0]
		if len(weathercity) < 3:
			return

		config.plugins.OAWeather.save()
		config.save()

		weatherhandler.reset()
		super(WeatherSettingsViewNew, self).keySave()

	def defaults(self, SAVE=False):
		for x in self["config"].list:
			if len(x) > 1:
				self.setInputToDefault(x[1], SAVE)
		self.setInputToDefault(config.plugins.OAWeather.owm_geocode, SAVE)
		if self.session:
			self.list = []
			self.list.append(getConfigListEntry(_("Enabled :"), config.plugins.OAWeather.enabled))
			if config.plugins.OAWeather.enabled.value:
				self.list.append(getConfigListEntry(_("Weather service :"), config.plugins.OAWeather.weatherservice))
				self.list.append(getConfigListEntry(_("Weather city name :"), config.plugins.OAWeather.weathercity))
				self.list.append(getConfigListEntry(_("Weather API key :"), config.plugins.OAWeather.apikey))
				self.list.append(getConfigListEntry(_("Temperature unit :"), config.plugins.OAWeather.tempUnit))
				self.list.append(getConfigListEntry(_("Weather icon set :"), config.plugins.OAWeather.iconset))
				self.list.append(getConfigListEntry(_("Weather icon night switch :"), config.plugins.OAWeather.nighticons))
				self.list.append(getConfigListEntry(_("Refresh interval :"), config.plugins.OAWeather.refreshInterval))
				self.list.append(getConfigListEntry(_("Cache data :"), config.plugins.OAWeather.cachedata))
				self.list.append(getConfigListEntry(_("Enable Debug :"), config.plugins.OAWeather.debug))
			self['config'].setList(self.list)
			self['status'].setText(_("Standard fertig"))

	def setInputToDefault(self, configItem, SAVE):
		configItem.setValue(configItem.default)
		if SAVE:
			configItem.save()


class TestScreen(Screen):
	skin = """
			<screen name="TestScreen"   position="center,center" size="1200,650" backgroundColor="#00000000"  transparent="0"  >
				<eLabel position="0,0" size="1200,650" backgroundColor="#00000000"    transparent="0" zPosition="0" />
				<ePixmap position="10,590" zPosition="3" size="240,50" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/OAWeather/Images/red.png" transparent="1" alphatest="blend" />
				<widget name="meinelist" position="100,20" size="1000,430" font="Regular;30" itemHeight="45"  backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="0" zPosition="3" scrollbarMode="showOnDemand" />
				<widget name="status" font="Regular; 25"  position="100,470" size="1000,40" foregroundColor ="#0000ff00" backgroundColor="#00000000" transparent="0"  zPosition="3" halign="center" valign="center" />
				<widget source="key_red" render="Label" position="10,570" zPosition="5" size="240,50" font="Regular;30" halign="center" valign="center" backgroundColor="#00313040" foregroundColor="#00ffffff" transparent="1" />
			</screen>
			"""

	def __init__(self, session, citylisttest, okCallback=None):
		self.session = session
		Screen.__init__(self, session)
		self.citylisttest = citylisttest
		self.okCallback = okCallback
		self['meinelist'] = MenuList(citylisttest)
		self.status = ""
		self["status"] = Label()
		self["actions"] = ActionMap(
			["OkCancelActions", "ColorActions"],
			{
				"ok": self.selectCity,
				"cancel": self.close,
				"red": self.close,
				"green": self.close,
				"yellow": self.close
			},
			-1
		)
		self['key_red'] = Label(_('exit'))
		self['status'].setText(_("Select the City and Press Ok"))

	def selectCity(self):
		selected_city_tuple = self['meinelist'].l.getCurrentSelection()
		if selected_city_tuple:
			selected_city = selected_city_tuple[0]
			self.selected_city = selected_city
			if self.okCallback is not None:
				self.okCallback(selected_city)
			self.close()


class WeatherHandler():
	logger.info("Using WeatherHandler")

	def __init__(self):
		self.session = None
		modes = {"MSN": "msn", "openweather": "owm", "OpenMeteo": "omw"}
		mode = modes.get(config.plugins.OAWeather.weatherservice.value, "msn")
		self.WI = Weatherinfo(mode, config.plugins.OAWeather.apikey.value)
		# apy_key = config.plugins.OAWeather.apikey.value
		# self.geocode = config.plugins.OAWeather.owm_geocode.value.split(",")
		self.geocode = self.getValidGeocode()
		self.currLocation = config.plugins.OAWeather.weatherlocation.value
		self.weathercity = None
		self.trialcounter = 0
		self.currentWeatherDataValid = 3  # 0= green (data available), 1= yellow (still working), 2= red (no data available, wait on next refresh) 3=startup
		self.refreshTimer = eTimer()
		self.refreshTimer.callback.append(self.refreshWeatherData)
		self.weatherDict = {}
		self.fullWeatherDict = {}
		self.onUpdate = []
		self.refreshCallback = None
		self.skydirs = {"N": _("North"), "NE": _("Northeast"), "E": _("East"), "SE": _("Southeast"), "S": _("South"), "SW": _("Southwest"), "W": _("West"), "NW": _("Northwest")}

	def getValidGeocode(self):
		"""Get valid coordinates or use default ones"""
		try:
			parts = config.plugins.OAWeather.owm_geocode.value.split(",")
			if len(parts) == 2:
				return [float(parts[0]), float(parts[1])]
		except:
			pass
		return [8.68417, 50.11552]

	def sessionStart(self, session):
		self.session = session
		weatherhelper.updateConfigChoices()
		self.getCacheData()

	def writeData(self, data):
		self.currentWeatherDataValid = 0
		self.weatherDict = data
		for callback in self.onUpdate:
			callback(data)
		seconds = int(config.plugins.OAWeather.refreshInterval.value) * 60
		self.refreshTimer.start(seconds * 1000, True)

	def getData(self):
		return self.weatherDict

	def getFulldata(self):
		return self.fullWeatherDict

	if sys.version_info[0] >= 3:
		logger.info("Python 3 getValid")

		def getValid(self):
			return self.currentWeatherDataValid
	else:

		def getValid(self):
			return self.currentWeatherDataValid

	if sys.version_info[0] >= 3:
		logger.info("Python 3 getSkydirs")

		def getSkydirs(self):
			return self.skydirs
	else:
		logger.info("Python 2 get skydirs")

		def getSkydirs(self):
			return self.skydirs

	def getCacheData(self):
		cacheminutes = int(config.plugins.OAWeather.cachedata.value)
		if cacheminutes and isfile(CACHEFILE):
			timedelta = (time() - getmtime(CACHEFILE)) / 60
			if cacheminutes > timedelta:
				with open(CACHEFILE, "rb") as fd:
					cache_data = pickle.load(fd)
				self.writeData(cache_data)
				return
		self.refreshTimer.start(3000, True)

	def getCurrLocation(self):
		return self.currLocation

	def setCurrLocation(self, currLocation):
		self.currLocation = currLocation

	def refreshWeatherData(self, entry=None):
		self.refreshTimer.stop()
		if config.misc.firstrun.value:  # don't refresh on firstrun try again after 10 seconds
			self.refreshTimer.start(600000, True)
			return
		if config.plugins.OAWeather.enabled.value:
			# Get the geocode from the configuration
			location = config.plugins.OAWeather.weatherlocation.value
			if location and len(location) == 3:
				weathercity, lon, lat = location
				geodata = (weathercity, lon, lat)
			else:
				# Fallback to default if location is invalid
				logger.error("Invalid location configuration, using default")
				geodata = weatherhelper.locationDefault

			# Use the geodata directly
			language = config.osd.language.value.lower().replace('_', '-')
			unit = "imperial" if config.plugins.OAWeather.tempUnit.value == "Fahrenheit" else "metric"

			# Start the weather info retrieval
			self.WI.start(
				geodata=geodata,
				cityID=None,
				units=unit,
				scheme=language,
				reduced=True,
				callback=self.refreshWeatherDataCallback
			)

	def refreshWeatherDataCallback(self, data, error):
		if error or data is None:
			self.trialcounter += 1
			if self.trialcounter < 2:
				print("[%s] lookup for city '%s' paused, try again in 10 secs..." % (MODULE_NAME, self.weathercity))
				self.currentWeatherDataValid = 1
				self.refreshTimer.start(10000, True)
			elif self.trialcounter > 5:
				print("[%s] lookup for city '%s' paused 1 h, to many errors..." % (MODULE_NAME, self.weathercity))
				self.currentWeatherDataValid = 2
				self.refreshTimer.start(3600000, True)
			else:
				print("[%s] lookup for city '%s' paused 5 mins, to many errors..." % (MODULE_NAME, self.weathercity))
				self.currentWeatherDataValid = 2
				self.refreshTimer.start(300000, True)
			return
		self.writeData(data)
		self.fullWeatherDict = self.WI.info

		# TODO write cache only on close
		if config.plugins.OAWeather.cachedata.value and self.currLocation == config.plugins.OAWeather.weatherlocation.value:
			with open(CACHEFILE, "wb") as fd:
				pickle.dump(data, fd, -1)
		if self.refreshCallback:
			self.refreshCallback()
			self.refreshCallback = None

	def reset(self, newLocation=None, callback=None):
		self.refreshCallback = callback
		if newLocation:
			self.currLocation = newLocation
			config.plugins.OAWeather.weatherlocation.value = newLocation
			config.plugins.OAWeather.weatherlocation.save()

		self.refreshTimer.stop()
		if isfile(CACHEFILE):
			remove(CACHEFILE)

		modes = {"MSN": "msn", "openweather": "owm", "OpenMeteo": "omw"}
		mode = modes.get(config.plugins.OAWeather.weatherservice.value, "msn")
		self.WI.setmode(mode, config.plugins.OAWeather.apikey.value)

		self.refreshWeatherData()

		if self.session:
			iconpath = config.plugins.OAWeather.iconset.value
			iconpath = join(ICONSETROOT, iconpath) if iconpath else join(PLUGINPATH, "Icons")
			self.session.screen["OAWeather"].iconpath = iconpath


def main(session, **kwargs):
	session.open(OAWeatherPlugin)


def setup(session, **kwargs):
	session.open(WeatherSettingsViewNew)


def sessionstart(session, **kwargs):
	from Components.Sources.OAWeather import OAWeather
	session.screen["OAWeather"] = OAWeather()
	session.screen["OAWeather"].precipitationtext = _("Precipitation")
	session.screen["OAWeather"].humiditytext = _("Humidity")
	session.screen["OAWeather"].feelsliketext = _("Feels like")
	session.screen["OAWeather"].pluginpath = PLUGINPATH
	iconpath = config.plugins.OAWeather.iconset.value
	if iconpath:
		iconpath = join(ICONSETROOT, iconpath)
	else:
		iconpath = join(PLUGINPATH, "Icons")
	session.screen["OAWeather"].iconpath = iconpath
	weatherhandler.sessionStart(session)


def Plugins(**kwargs):
	pluginList = []
	pluginList.append(PluginDescriptor(name="OAWeather", where=[PluginDescriptor.WHERE_SESSIONSTART], fnc=sessionstart, needsRestart=False))
	pluginList.append(PluginDescriptor(name=_("Weather Plugin"), description=_("Show Weather Forecast"), icon="plugin.png", where=[PluginDescriptor.WHERE_PLUGINMENU], fnc=main))
	return pluginList


class OAWeatherPlugin(Screen):

	def __init__(self, session):
		logger.info("OAWeatherPlugin initialized")
		params = {
			"picpath": join(PLUGINPATH, "Images")
		}
		skintext = ""

		if screenwidth.width() >= 1920:
			xml = parse(join(PLUGINPATH, "skinfhd.xml")).getroot()
		elif screenwidth.width() <= 1280:
			xml = parse(join(PLUGINPATH, "skin.xml")).getroot()

		for screen in xml.findall('screen'):
			if screen.get("name") == "OAWeatherPlugin":
				skintext = tostring(screen).decode()
				for key in params.keys():
					try:
						skintext = skintext.replace('{%s}' % key, params[key])
					except Exception as e:
						print("%s@key=%s" % (str(e), key))
				break
		self.skin = skintext

		Screen.__init__(self, session)

		try:
			weatherLocation = config.plugins.OAWeather.weatherlocation.value
			self.currFavIdx = weatherhelper.favoriteList.index(weatherLocation) if weatherLocation in weatherhelper.favoriteList else 0
		except:
			weatherLocation = weatherhelper.locationDefault
			self.currFavIdx = 0

		Neue_keymap = '/usr/lib/enigma2/python/Plugins/Extensions/OAWeather/keymap.xml'
		readKeymap(Neue_keymap)
		self.data = {}
		self.na = _("n/a")
		self.title = _("Weather Plugin")
		self["key_blue"] = StaticText(_("Menu"))
		self["statustext"] = StaticText()
		self["description"] = StaticText(_('Press Key Green or Menu for Setup'))
		self["update"] = Label(_("Update"))
		self["current"] = Label(_("Current Weather"))
		self["today"] = StaticText(_("Today"))
		self["key_red"] = StaticText(_("Exit"))
		self["key_green"] = StaticText(_("Chose favorite"))
		self["key_yellow"] = StaticText(_("Previous favorite"))
		self["key_blue"] = StaticText(_("Next favorite"))
		self["key_ok"] = StaticText(_("View details"))
		self["key_menu"] = StaticText(_("Settings"))
		self["actions"] = ActionMap(
			["OAWeatherActions", "ColorActions"],
			{
				"ok": self.keyOk,
				"cancel": self.close,
				"red": self.close,
				"yellow": self.favoriteUp,
				"blue": self.favoriteDown,
				"green": self.favoriteChoice,
				"menu": self.config,
				"info": self.keyOk
			},
			-1
		)
		for i in range(1, 6):
			self["weekday%s_temp" % i] = StaticText()

		self.onLayoutFinish.append(self.startRun)

	def startRun(self):
		if not weatherhandler.getData() or weatherhandler.getValid() != 0:
			self["statustext"].text = _("Loading weather data...")
		else:
			self.data = weatherhandler.getData() or {}
			self.getWeatherDataCallback()

		self.checkDataTimer = eTimer()
		self.checkDataTimer.callback.append(self.checkDataUpdate)
		self.checkDataTimer.start(1000)

	def checkDataUpdate(self):
		if weatherhandler.getValid() == 0:
			self.data = weatherhandler.getData()
			self.getWeatherDataCallback()
			self.checkDataTimer.stop()
		elif weatherhandler.getValid() == 2:
			self.error(_("Weather data unavailable"))
			self.checkDataTimer.stop()

	def clearFields(self):
		for i in range(1, 6):
			self["weekday%s_temp" % i].text = ""

	def getVal(self, key: str):
		return self.data.get(key, self.na) if self.data else self.na

	def getCurrentVal(self, key: str, default: str = _("n/a")):
		value = default
		if self.data and "current" in self.data:
			current = self.data.get("current", {})
			if key in current:
				value = current.get(key, default)
		return value

	def getWeatherDataCallback(self):
		self["statustext"].text = ""
		forecast = self.data.get("forecast", {})
		tempunit = self.data.get("tempunit", self.na)
		for day in range(1, 6):
			item = forecast.get(day, {})
			lowTemp = item.get("minTemp", "")
			highTemp = item.get("maxTemp", "")
			text = item.get("text", "")
			self[f"weekday{day}_temp"].text = "%s %s|%s %s\n%s" % (highTemp, tempunit, lowTemp, tempunit, text)

	def keyOk(self):
		if weatherhelper.favoriteList and weatherhandler.getValid() == 0:
			self.session.open(OAWeatherDetailview, weatherhelper.favoriteList[self.currFavIdx])

	def favoriteUp(self):
		if weatherhelper.favoriteList:
			self.currFavIdx = (self.currFavIdx - 1) % len(weatherhelper.favoriteList)
			callInThread(weatherhandler.reset, weatherhelper.favoriteList[self.currFavIdx], self.configFinished)

	def favoriteDown(self):
		if weatherhelper.favoriteList:
			self.currFavIdx = (self.currFavIdx + 1) % len(weatherhelper.favoriteList)
			callInThread(weatherhandler.reset, weatherhelper.favoriteList[self.currFavIdx], self.configFinished)

	def favoriteChoice(self):
		choiceList = [(item[0], item) for item in weatherhelper.favoriteList]
		self.session.openWithCallback(self.returnFavoriteChoice, ChoiceBox, title=_("Select desired location"), list=choiceList)

	def returnFavoriteChoice(self, favorite):
		if favorite is not None:
			selected_location = favorite[1]
			logger.info(f"Selected location: {selected_location[0]}")

			if weatherhelper.addFavorite(selected_location):
				logger.info("Favorite added successfully")
			else:
				logger.info("Favorite already exists")

			config.plugins.OAWeather.weatherlocation.value = selected_location
			config.plugins.OAWeather.weatherlocation.save()
			logger.info(f"Current location set to: {selected_location[0]}")

			callInThread(weatherhandler.reset, selected_location, self.configFinished)

	def saveConfig(self):
		config.plugins.OAWeather.save()
		config.save()

	def config(self):
		self.session.openWithCallback(self.configFinished, WeatherSettingsViewNew)

	def configFinished(self, result=None):
		self.clearFields()
		weatherhandler.reset()
		self.startRun()

	def error(self, errortext):
		self.clearFields()
		self["statustext"].text = errortext


class OAWeatherDetailFrame(Screen):
	def __init__(self, session):
		self.skin = weatherhelper.loadSkin("OAWeatherDetailFrame")
		Screen.__init__(self, session)
		self.widgets = (
			"time", "pressure", "temp", "feels", "humid", "precip", "windspeed",
			"winddir", "windgusts", "uvindex", "visibility", "shortdesc", "longdesc"
		)
		for widget in self.widgets:
			self[widget] = StaticText()
		self["icon"] = Pixmap()

	def showFrame(self):
		self.show()

	def updateFrame(self, dataList):
		try:
			widgets = (
				"time", "pressure", "temp", "feels", "humid", "precip", "windspeed",
				"winddir", "windgusts", "uvindex", "visibility", "shortdesc", "longdesc"
			)

			# Ensure we have at least 14 elements
			if not dataList or len(dataList) < 14:
				dataList = [_("N/A")] * 14

			for index, widget in enumerate(widgets):
				value = dataList[index] if index < len(dataList) else _("N/A")
				self[widget].setText(str(value))

			icon = dataList[13] if len(dataList) > 13 else None
			self["icon"].instance.setPixmap(icon)
			self.showFrame()
		except Exception as e:
			logger.error(f"Error updating detail frame: {str(e)}")

	def hideFrame(self):
		self.hide()


class OAWeatherDetailview(Screen):
	YAHOOnightswitch = {
		"3": "47", "4": "47", "11": "45", "12": "45", "13": "46", "14": "46", "15": "46", "16": "46", "28": "27",
		"30": "29", "32": "31", "34": "33", "37": "47", "38": "47", "40": "45", "41": "46", "42": "46", "43": "46"
	}
	YAHOOdayswitch = {"27": "28", "29": "30", "31": "32", "33": "34", "45": "39", "46": "16", "47": "4"}

	def __init__(self, session, currlocation):
		self.skin = weatherhelper.loadSkin("OAWeatherDetailview")
		Screen.__init__(self, session)
		self.detailFrame = self.session.instantiateDialog(OAWeatherDetailFrame)
		self.detailFrameActive = False
		self.currFavIdx = weatherhelper.favoriteList.index(currlocation) if currlocation in weatherhelper.favoriteList else 0
		self.old_weatherservice = config.plugins.OAWeather.weatherservice.value

		self.detailLevels = config.plugins.OAWeather.detailLevel.choices
		self.detailLevelIdx = config.plugins.OAWeather.detailLevel.choices.index(
			config.plugins.OAWeather.detailLevel.value
		)

		self.currdatehour = datetime.today().replace(minute=0, second=0, microsecond=0)
		self.currdaydelta = 0
		self.skinList = []
		self.dayList = []
		self.sunList = []
		self.moonList = []
		self.na = _("n/a")
		self.title = _("Weather Plugin Detailview")
		self["version"] = StaticText(f"OA-Weather {weatherhelper.version}")
		self["detailList"] = List()
		self["update"] = Label(_("Update"))
		self["currdatetime"] = Label(self.currdatehour.strftime("%a %d %b"))
		self["sunrise"] = StaticText(self.na)
		self["sunset"] = StaticText(self.na)
		self["moonrise"] = StaticText("")
		self["moonset"] = StaticText("")
		self["moonrisepix"] = Pixmap()
		self["moonsetpix"] = Pixmap()
		self["cityarea"] = Label()
		self["key_red"] = StaticText(_("Exit"))
		self["key_green"] = StaticText(_("Chose favorite"))
		self["key_yellow"] = StaticText(_("Previous favorite"))
		self["key_blue"] = StaticText(_("Next favorite"))
		self["key_channel"] = StaticText(_("Day +/-"))
		self["key_info"] = StaticText(_("Details +/-"))
		self["key_ok"] = StaticText(_("Glass"))
		self["actions"] = ActionMap(
			["OAWeatherActions", "ColorActions", "NavigationActions"],
			{
				"ok": self.toggleDetailframe,
				"cancel": self.exit,
				"up": self.prevEntry,
				"down": self.nextEntry,
				"right": self.pageDown,
				"left": self.pageUp,
				"red": self.exit,
				"yellow": self.favoriteUp,
				"blue": self.favoriteDown,
				"green": self.favoriteChoice,
				"channeldown": self.prevDay,
				"channelup": self.nextDay,
				"info": self.toggleDetailLevel,
				"menu": self.config
			},
			-1
		)
		self["statustext"] = StaticText()
		self.pressPix = self.getPixmap("barometer.png")
		self.tempPix = self.getPixmap("temp.png")
		self.feelPix = self.getPixmap("feels.png")
		self.humidPix = self.getPixmap("hygrometer.png")
		self.precipPix = self.getPixmap("umbrella.png")
		self.WindSpdPpix = self.getPixmap("wind.png")
		self.WindDirPix = self.getPixmap("compass.png")
		self.WindGustPix = self.getPixmap("windgust.png")
		self.uvIndexPix = self.getPixmap("uv_index.png")
		self.visiblePix = self.getPixmap("binoculars.png")
		self.onLayoutFinish.append(self.firstRun)

	def firstRun(self):
		moonrisepix = join(PLUGINPATH, "Images/moonrise.png")
		moonsetpix = join(PLUGINPATH, "Images/moonset.png")

		if not exists(moonrisepix):
			self["moonrisepix"].hide()

		if not exists(moonsetpix):
			self["moonsetpix"].hide()

		if exists(moonrisepix):
			self["moonrisepix"].instance.setPixmapFromFile(moonrisepix)
		self["moonrisepix"].hide()

		if exists(moonsetpix):
			self["moonsetpix"].instance.setPixmapFromFile(moonsetpix)
		self["detailList"].style = self.detailLevels[self.detailLevelIdx]
		self.startRun()

	def startRun(self):
		callInThread(self.parseData)

	def updateSkinList(self):
		try:
			weekday = _('Today') if self.currdatehour.weekday() == datetime.today().weekday() else self.currdatehour.strftime("%a")
			self["currdatetime"].setText(f"{weekday} {self.currdatehour.strftime('%d %b')}")

			iconpix = [
				self.pressPix, self.tempPix, self.feelPix,
				self.humidPix, self.precipPix, self.WindSpdPpix,
				self.WindDirPix, self.WindGustPix,
				self.uvIndexPix if config.plugins.OAWeather.weatherservice.value != "openweather" else None,
				self.visiblePix
			]

			if self.dayList:
				hourData = self.dayList[self.currdaydelta]
				skinList = []
				for hour in hourData:
					skinList.append(tuple(hour + iconpix))
			else:
				# Create default "No data" entry
				no_data = [
					_("No data"), _("--"), _("--"), _("--"), _("--"), _("--"),
					_("--"), _("--"), _("--"), _("--"), _("--"),
					_("Weather data unavailable"),
					_("Try refreshing or check settings"),
					None
				]
				skinList = [tuple(no_data + iconpix)]

			self["detailList"].setList(skinList)
			self.skinList = skinList
			self.updateDetailFrame()
		except Exception as e:
			logger.error(f"Error updating skin list: {str(e)}")

	def updateDetailFrame(self):
		if self.detailFrameActive:
			current = self["detailList"].getCurrent()
			if current is not None:
				# Extract only the data fields (first 14 elements)
				data_fields = list(current)[:14]
				self.detailFrame.updateFrame(data_fields)

	def toggleDetailframe(self):
		try:
			if self.detailFrameActive:
				self.detailFrame.hideFrame()
			else:
				self.detailFrame.showFrame()  # Show the frame
			self.detailFrameActive = not self.detailFrameActive
			self.updateDetailFrame()
		except Exception as e:
			logger.error(f"Error toggling detail frame: {str(e)}")
			self.detailFrameActive = False

	def toggleDetailLevel(self):
		self.detailLevelIdx ^= 1
		self["detailList"].style = self.detailLevels[self.detailLevelIdx]
		self["detailList"].updateList(self.skinList)

	def updateMoonData(self):
		if self.moonList:
			self["moonrise"].setText(datetime.fromisoformat(self.moonList[self.currdaydelta][0]).strftime("%H:%M"))
			self["moonset"].setText(datetime.fromisoformat(self.moonList[self.currdaydelta][1]).strftime("%H:%M"))
			self["moonrisepix"].show()
			self["moonsetpix"].show()
		else:
			self["moonrise"].setText("")
			self["moonset"].setText("")
			self["moonrisepix"].hide()
			self["moonsetpix"].hide()
		if self.sunList:
			self["sunrise"].setText(datetime.fromisoformat(self.sunList[self.currdaydelta][0]).strftime("%H:%M"))
			self["sunset"].setText(datetime.fromisoformat(self.sunList[self.currdaydelta][1]).strftime("%H:%M"))
		else:
			self["sunrise"].setText("")
			self["sunset"].setText("")

	def getPixmap(self, filename):
		iconfile = join(PLUGINPATH, f"Images/{filename}")
		return LoadPixmap(cached=True, path=iconfile) if exists(iconfile) else None

	def parseData(self):
		try:
			weatherservice = config.plugins.OAWeather.weatherservice.value
			if weatherservice in ["MSN", "OpenMeteo", "openweather"]:
				parser = {
					"MSN": self.msnparser,
					"OpenMeteo": self.omwparser,
					"openweather": self.owmparser
				}
				parser[weatherservice]()
			else:
				logger.warning(f"Unsupported weather service: {weatherservice}")
				self.dayList = []
		except Exception as e:
			logger.error(f"Weather data parsing error: {str(e)}")
			self.dayList = []
		finally:
			# Always update UI even if parsing fails
			self.updateSkinList()
			self.updateMoonData()

	def msnparser(self):
		iconpath = config.plugins.OAWeather.iconset.value
		iconpath = join(ICONSETROOT, iconpath) if iconpath else join(PLUGINPATH, "Icons")
		dayList = []
		responses = weatherhandler.getFulldata().get("responses")

		# add lululla for debug
		log_path = join(tempfile.gettempdir(), "oaweater_msn_log.txt")
		with open(log_path, "w") as f:
			json.dump(responses, f, indent=4)

		if responses:  # collect latest available data
			weather = responses[0]["weather"][0]
			current = weather["current"]
			nowcasting = weather["nowcasting"]
			today = weather["forecast"]["days"][0]
			sunrisestr = today["almanac"].get("sunrise", "")
			sunrisestr = datetime.fromisoformat(sunrisestr).replace(tzinfo=None).isoformat() if sunrisestr else ""
			sunsetstr = today["almanac"].get("sunset", "")
			sunsetstr = datetime.fromisoformat(sunsetstr).replace(tzinfo=None).isoformat() if sunsetstr else ""
			created = current.get("created")
			currtime = datetime.fromisoformat(created).replace(tzinfo=None) if created else ""
			timestr = currtime.strftime("%H:%M h") if currtime else ""
			tempunit = "°C" if config.plugins.OAWeather.tempUnit.value == "Celsius" else "°F"
			press = f"{round(current.get('baro', 0))} mbar"
			temp = f"{round(current.get('temp', 0))} {tempunit}"
			feels = f"{round(current.get('feels', 0))} {tempunit}"
			humid = f"{round(current.get('rh', 0))} %"
			hourly = today["hourly"]
			precip = f"{round(hourly[0]['precip'])} %" if len(hourly) else self.na  # workaround: use value from next hour if available
			windSpd = f"{round(current.get('windSpd', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
			windDir = f"{_(weatherhandler.WI.directionsign(round(current.get('windDir', 0))))}"
			windGusts = f"{round(current.get('windGust', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
			uvIndex = f"{round(current.get('uv', 0))}"
			visibility = f"{round(current.get('vis', 0))} km"
			shortDesc = current.get("pvdrCap", "")  # e.g. 'bewölkt'
			longDesc = nowcasting.get("summary", "")  # e.g. "Der Himmel wird bewölkt."
			yahoocode = weatherhandler.WI.convert2icon("MSN", current.get("symbol", "")).get("yahooCode")
			yahoocode = self.nightSwitch(yahoocode, self.getIsNight(currtime, sunrisestr, sunsetstr))
			iconfile = join(iconpath, f"{yahoocode}.png")
			iconpix = LoadPixmap(cached=True, path=iconfile) if iconfile and exists(iconfile) else None
			hourData = []
			hourData.append([timestr, press, temp, feels, humid, precip, windSpd, windDir, windGusts, uvIndex, visibility, shortDesc, longDesc, iconpix])
			days = weather["forecast"]["days"]
			if days:
				self.sunList = []
				self.moonList = []
				for index, day in enumerate(days):  # collect data on future hours of current day
					if index:
						hourData = []
					almanac = day.get("almanac", {})
					sunrisestr = almanac.get("sunrise", "")
					sunrisestr = datetime.fromisoformat(sunrisestr).replace(tzinfo=None).isoformat() if sunrisestr else ""
					sunsetstr = almanac.get("sunset", "")
					sunsetstr = datetime.fromisoformat(sunsetstr).replace(tzinfo=None).isoformat() if sunsetstr else ""
					moonrisestr = almanac.get("moonrise", "")
					moonrisestr = datetime.fromisoformat(moonrisestr).replace(tzinfo=None).isoformat() if moonrisestr else ""
					moonsetstr = almanac.get("moonset", "")
					moonsetstr = datetime.fromisoformat(moonsetstr).replace(tzinfo=None).isoformat() if moonsetstr else ""
					for hour in day.get("hourly", []):
						valid = hour.get("valid")
						currtime = datetime.fromisoformat(valid).replace(tzinfo=None) if valid else ""
						timestr = currtime.strftime("%H:%M h") if currtime else ""
						press = f"{round(hour.get('baro', 0))} mbar"
						tempunit = "°C" if config.plugins.OAWeather.tempUnit.value == "Celsius" else "°F"
						temp = f"{round(hour.get('temp', 0))} {tempunit}"
						feels = f"{round(hour.get('feels', 0))} {tempunit}"
						humid = f"{round(hour.get('rh', 0))} %"
						precip = f"{round(hour.get('precip', 0))} %"
						windSpd = f"{round(hour.get('windSpd', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
						windDir = f"{_(weatherhandler.WI.directionsign(round(hour.get('windDir', 0))))}"
						windGusts = f"{round(hour.get('windGust', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
						uvIndex = f"{round(hour.get('uv', 0))}"
						visibility = f"{round(hour.get('vis', 0))} km"
						shortDesc = hour.get("pvdrCap", "")  # e.g. 'bewölkt'
						longDesc = hour.get("summary", "")  # e.g. "Der Himmel wird bewölkt."
						yahoocode = weatherhandler.WI.convert2icon("MSN", hour.get("symbol", "")).get("yahooCode")  # e.g. 'n4000' -> {'yahooCode': '26', 'meteoCode': 'Y'}
						yahoocode = self.nightSwitch(yahoocode, self.getIsNight(currtime, sunrisestr, sunsetstr))
						iconfile = join(iconpath, f"{yahoocode}.png")
						iconpix = LoadPixmap(cached=True, path=iconfile) if iconfile and exists(iconfile) else None
						hourData.append([timestr, press, temp, feels, humid, precip, windSpd, windDir, windGusts, uvIndex, visibility, shortDesc, longDesc, iconpix])
					dayList.append(hourData)
					self.sunList.append((sunrisestr, sunsetstr))
					self.moonList.append((moonrisestr, moonsetstr))
		self.dayList = dayList

	def omwparser(self):
		iconpath = config.plugins.OAWeather.iconset.value
		iconpath = join(ICONSETROOT, iconpath) if iconpath else join(PLUGINPATH, "Icons")
		fulldata = weatherhandler.getFulldata()
		if fulldata:
			daily = fulldata.get("daily", {})
			sunriseList = daily.get("sunrise", [])
			sunsetList = daily.get("sunset", [])
			self.sunList = []
			for index, sunrisestr in enumerate(sunriseList):
				sunsetstr = sunsetList[index]
				self.sunList.append((sunrisestr if sunrisestr else self.na, sunsetstr if sunsetstr else self.na))
			self.moonList = []  # OMW does not support moonrise / moonset at all
			hourly = fulldata.get("hourly", {})
			dayList = []
			if hourly:
				timeList = hourly.get("time", [])
				pressList = hourly.get("pressure_msl")
				tempList = hourly.get("temperature_2m", [])
				feelsList = hourly.get("apparent_temperature", [])
				humidList = hourly.get("relativehumidity_2m", [])
				precipList = hourly.get("precipitation_probability", [])
				wSpeedList = hourly.get("windspeed_10m", [])
				wGustList = hourly.get("wind_gusts_10m", [])
				wDirList = hourly.get("winddirection_10m", [])
				uvList = hourly.get("uv_index", [])
				visList = hourly.get("visibility", [])
				wCodeList = hourly.get("weathercode", [])
				currday = datetime.fromisoformat(timeList[0]).replace(hour=0, minute=0, second=0, microsecond=0)
				daycount = 0
				hourData = []
				for idx, isotime in enumerate(timeList):
					currtime = datetime.fromisoformat(isotime)
					timestr = currtime.strftime("%H:%M h")
					press = f"{round(pressList[idx])} mbar"
					tempunit = "°C" if config.plugins.OAWeather.tempUnit.value == "Celsius" else "°F"
					temp = f"{round(tempList[idx])} {tempunit}"
					feels = f"{round(feelsList[idx])} {tempunit}"
					humid = f"{round(humidList[idx])} %"
					precip = f"{round(precipList[idx])} %"
					windSpd = f"{round(wSpeedList[idx])} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
					windDir = f"{_(weatherhandler.WI.directionsign(round(round(wDirList[idx]))))}"
					windGusts = f"{round(wGustList[idx])} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
					uvIndex = f"{round(uvList[idx])}"
					visibility = f"{round(visList[idx] / 1000)} km"
					shortDesc, longDesc = "", ""  # OMW does not support description texts at all
					isNight = self.getIsNight(currtime, sunriseList[daycount], sunsetList[daycount])
					yahoocode = self.nightSwitch(weatherhandler.WI.convert2icon("OMW", wCodeList[idx]).get("yahooCode"), isNight)  # e.g. '1' -> {'yahooCode': '34', 'meteoCode': 'B'}
					iconfile = join(iconpath, f"{yahoocode}.png")
					iconpix = LoadPixmap(cached=True, path=iconfile) if iconfile and exists(iconfile) else None
					hourData.append([timestr, press, temp, feels, humid, precip, windSpd, windDir, windGusts, uvIndex, visibility, shortDesc, longDesc, iconpix])
					timeday = currtime.replace(hour=0, minute=0, second=0, microsecond=0)
					if timeday > currday:  # is a new day?
						currday = timeday
						daycount += 1
						dayList.append(hourData)
						hourData = []
			self.dayList = dayList

	def owmparser(self):
		iconpath = config.plugins.OAWeather.iconset.value
		iconpath = join(ICONSETROOT, iconpath) if iconpath else join(PLUGINPATH, "Icons")
		fulldata = weatherhandler.getFulldata()
		if fulldata:
			city = fulldata.get("city", {})
			sunriseTs, sunsetTs = city.get("sunrise", 0), city.get("sunset", 0)  # OM only supports sunris/sunset of today
			sunrisestr = datetime.fromtimestamp(sunriseTs).isoformat() if sunriseTs else ""
			sunsetstr = datetime.fromtimestamp(sunsetTs).isoformat() if sunsetTs else ""
			self.sunList, self.moonList = [], []  # OMW does not support moonrise / moonset at all
			hourData = []
			tempunit = "°C" if config.plugins.OAWeather.tempUnit.value == "Celsius" else "°F"
			timeTs = fulldata.get("dt", 0)  # collect latest available data
			timestr = datetime.fromtimestamp(timeTs).strftime("%H:%M") if timeTs else ""
			main = fulldata.get("main", {})
			hourly = fulldata.get("list", {})
			press = f"{round(main.get('pressure', 0))} mbar"
			temp = f"{round(main.get('temp', 0))} {tempunit}"
			feels = f"{round(main.get('feels_like', 0))} {tempunit}"
			humid = f"{round(main.get('humidity', 0))} %"
			precip = f"{round(hourly[0].get('pop', 0) * 100)} %"
			wind = fulldata.get('wind', {})
			windSpd = f"{round(wind.get('speed', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
			windDir = f"{_(weatherhandler.WI.directionsign(round(wind.get('deg', 0))))}"
			windGusts = f"{round(hourly[0].get('wind', {}).get('gust', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
			uvIndex = ""  # OWM does not support UV-index at all
			visibility = f"{round(fulldata.get('visibility', 0) / 1000)} km"
			weather = fulldata.get("weather", [""])[0]
			shortDesc = weather.get("description", "")
			longDesc = ""  # OWM does not support long descriptions at all
			currtime = datetime.fromtimestamp(timeTs)
			isNight = self.getIsNight(currtime, sunrisestr, sunsetstr)
			yahoocode = self.nightSwitch(weatherhandler.WI.convert2icon("OWM", weather.get("id", "n/a")).get("yahooCode"), isNight)  # e.g. '801' -> {'yahooCode': '34', 'meteoCode': 'B'}
			iconfile = join(iconpath, f"{yahoocode}.png")
			iconpix = LoadPixmap(cached=True, path=iconfile) if iconfile and exists(iconfile) else None
			hourData.append([timestr, press, temp, feels, humid, precip, windSpd, windDir, windGusts, uvIndex, visibility, shortDesc, longDesc, iconpix])
			dayList = []
			if hourly:
				currday = datetime.fromisoformat(hourly[0].get("dt_txt", "1900-01-01 00:00:00")).replace(hour=0, minute=0, second=0, microsecond=0)
				for hour in hourly:  # collect data on future hours of current day
					isotime = hour.get("dt_txt", "1900-01-01 00:00:00")
					timestr = isotime[11:16]
					main = hour.get("main", {})
					press = f"{round(main.get('pressure', 0))} mbar"
					temp = f"{round(main.get('temp', 0))} {tempunit}"
					feels = f"{round(main.get('feels_like', 0))} {tempunit}"
					humid = f"{round(main.get('humidity', 0))} %"
					precip = f"{round(hour.get('pop', 0) * 100)} %"
					wind = hour.get("wind", {})
					windSpd = f"{round(wind.get('speed', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
					windDir = f"{_(weatherhandler.WI.directionsign(round(wind.get('deg', 0))))}"
					windGusts = f"{round(wind.get('gust', 0))} {'km/h' if config.plugins.OAWeather.windspeedMetricUnit.value == 'km/h' else 'm/s'}"
					uvIndex = ""  # OWM does not support UV-index at all
					visibility = f"{round(hour.get('visibility', 0) / 1000)} km"
					weather = hour.get("weather", [""])[0]
					shortDesc = weather.get("description", "")
					longDesc = ""  # OWM does not support long descriptions at all
					currtime = datetime.fromisoformat(isotime)
					isNight = self.getIsNight(currtime, sunrisestr, sunsetstr)
					yahoocode = self.nightSwitch(weatherhandler.WI.convert2icon("OWM", weather.get("id", "n/a")).get("yahooCode"), isNight)
					iconfile = join(iconpath, f"{yahoocode}.png")
					iconpix = LoadPixmap(cached=True, path=iconfile) if iconfile and exists(iconfile) else None
					hourData.append([timestr, press, temp, feels, humid, precip, windSpd, windDir, windGusts, uvIndex, visibility, shortDesc, longDesc, iconpix])
					timeday = currtime.replace(hour=0, minute=0, second=0, microsecond=0)
					if timeday > currday:  # is a new day?
						currday = timeday
						dayList.append(hourData)
						hourData = []
						self.sunList.append((sunrisestr, sunsetstr))
			self.dayList = dayList

	def getIsNight(self, currtime, sunrisestr, sunsetstr):
		if sunrisestr and sunsetstr:
			sunrise = datetime.fromisoformat(sunrisestr)
			sunset = datetime.fromisoformat(sunsetstr)
			isNight = True if currtime < sunrise or currtime > sunset else False
		else:
			isNight = False
		return isNight

	def nightSwitch(self, iconcode, isNight):
		return self.YAHOOnightswitch.get(iconcode, iconcode) if config.plugins.OAWeather.nighticons.value and isNight else self.YAHOOdayswitch.get(iconcode, iconcode)

	def favoriteUp(self):
		if weatherhelper.favoriteList:
			self.currFavIdx = (self.currFavIdx - 1) % len(weatherhelper.favoriteList)
			callInThread(weatherhandler.reset, weatherhelper.favoriteList[self.currFavIdx], callback=self.parseData)

	def favoriteDown(self):
		if weatherhelper.favoriteList:
			self.currFavIdx = (self.currFavIdx + 1) % len(weatherhelper.favoriteList)
			callInThread(weatherhandler.reset, weatherhelper.favoriteList[self.currFavIdx], callback=self.parseData)

	def favoriteChoice(self):
		choiceList = [(item[0], item) for item in weatherhelper.favoriteList]
		self.session.openWithCallback(self.returnFavoriteChoice, ChoiceBox, title=_("Select desired location"), list=choiceList)

	def returnFavoriteChoice(self, favorite):
		if favorite is not None:
			config.plugins.OAWeather.weatherlocation.value = favorite[1]
			config.plugins.OAWeather.weatherlocation.save()
			callInThread(weatherhandler.reset, favorite[1], callback=self.parseData)

	def prevEntry(self):
		self["detailList"].up()
		self.updateDetailFrame()

	def nextEntry(self):
		self["detailList"].down()
		self.updateDetailFrame()

	def pageDown(self):
		self["detailList"].pageDown()
		self.updateDetailFrame()

	def pageUp(self):
		self["detailList"].pageUp()
		self.updateDetailFrame()

	def prevDay(self):
		self.currdaydelta = (self.currdaydelta - 1) % len(self.dayList)
		self.currdatehour = datetime.today().replace(minute=0, second=0, microsecond=0) + timedelta(days=self.currdaydelta)
		callInThread(weatherhandler.reset, callback=self.parseData)

	def nextDay(self):
		self.currdaydelta = (self.currdaydelta + 1) % len(self.dayList)
		self.currdatehour = datetime.today().replace(minute=0, second=0, microsecond=0) + timedelta(days=self.currdaydelta)
		callInThread(weatherhandler.reset, callback=self.parseData)

	def config(self):
		self.old_weatherservice = config.plugins.OAWeather.weatherservice.value
		if self.detailFrameActive:
			self.detailFrame.hideFrame()
		self.session.openWithCallback(self.configFinished, WeatherSettingsViewNew)

	def configFinished(self, result=None):
		self.detailLevels = config.plugins.OAWeather.detailLevel.choices
		self.detailLevelIdx = config.plugins.OAWeather.detailLevel.choices.index(
			config.plugins.OAWeather.detailLevel.value
		)
		if self.detailFrameActive:
			self.detailFrame.showFrame()
		if self.old_weatherservice != config.plugins.OAWeather.weatherservice.value:
			callInThread(weatherhandler.reset, callback=self.parseData)
		else:
			self.startRun()

	def exit(self):
		if self.detailFrameActive:
			self.detailFrame.hide()
			self.detailFrameActive = False
		else:
			self.session.deleteDialog(self.detailFrame)
			self.close()


class OAWeatherFavorites(Screen):
	def __init__(self, session):
		self.skin = weatherhelper.loadSkin("OAWeatherFavorites")
		Screen.__init__(self, session)
		self.newFavList = weatherhelper.favoriteList[:]
		self.addFavorite = False
		self.currindex = 0
		self.searchcity = ""
		self.currFavorite = ("", 0, 0)
		self.returnFavorite = ""
		self["favoriteList"] = List()
		self["headline"] = StaticText(_("Manage your favorites"))
		self["key_red"] = StaticText(_("Delete"))
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText(_("Edit"))
		self["key_blue"] = StaticText(_("Add"))
		self["actions"] = ActionMap(
			["OkCancelActions", "ColorActions"],
			{
				"ok": self.keyOk,
				"red": self.keyRed,
				"green": self.keyGreen,
				"yellow": self.keyYellow,
				"blue": self.keyBlue,
				"cancel": self.keyExit
			},
			-1
		)
		self.onShown.append(self.onShownFinished)

	def onShownFinished(self):
		self.updateFavoriteList()

	def updateFavoriteList(self):
		skinList = []
		for favorite in self.newFavList:
			weathercity, lon, lat = favorite
			skinList.append((weathercity, f"[lon={lon}, lat={lat}]"))
		self["favoriteList"].updateList(skinList)

	def returnCityname(self, weathercity):
		if weathercity:
			self.searchcity = weathercity
			callInThread(self.citySearch, weathercity)

	def citySearch(self, weathercity):
		services = {"MSN": "msn", "OpenMeteo": "omw", "openweather": "owm"}
		service = services.get(config.plugins.OAWeather.weatherservice.value, "msn")
		apikey = config.plugins.OAWeather.apikey.value
		if service == "owm" and len(apikey) < 32:
			self.session.open(MessageBox, text=_("The API key for OpenWeatherMap is not defined or invalid.\nPlease verify your input data.\nOtherwise your settings won't be saved."), type=MessageBox.TYPE_WARNING)
		else:
			WI = Weatherinfo(service, apikey)
			if WI.error:
				print("[WeatherSettingsViewNew] Error in module 'citySearch': %s" % WI.error)
				self.cityChoice((False, _("Error in Weatherinfo"), WI.error))
			else:
				geodataList = WI.getCitylist(weathercity, config.osd.language.value.replace('_', '-').lower(), count=15)
				if WI.error or geodataList is None or len(geodataList) == 0:
					print("[WeatherSettingsViewNew] Error in module 'citySearch': %s" % WI.error)
					self.cityChoice((False, _("Error getting City ID"), _("City '%s' not found! Please try another wording." % weathercity)))
				else:
					cityList = []
					for item in geodataList:
						try:
							cityList.append((item[0], item[1], item[2]))
						except Exception:
							print("[WeatherSettingsViewNew] Error in module 'showMenu': faulty entry in resultlist.")
					self.cityChoice((True, cityList, ""))

	def cityChoice(self, answer):
		if answer[0] is True:
			self.searchcity = ""
			self.session.openWithCallback(self.returnCityChoice, ChoiceBox, title=_("Select your location"), list=tuple(answer[1]))
		elif answer[0] is False:
			self.session.open(MessageBox, text=answer[2], type=MessageBox.TYPE_WARNING, timeout=3)
			self.session.openWithCallback(self.returnCityname, VirtualKeyBoard, title=_("Weather cityname (at least 3 letters):"), text=self.searchcity)

	def returnCityChoice(self, answer):
		if answer is not None:
			weathercity, lon, lat = answer
			location = (weatherhelper.reduceCityname(weathercity), lon, lat)
			if self.addFavorite:
				self.add2FavList(location)
				self.addFavorite = False
			else:
				self.newFavList[self.currindex] = location
			self.updateFavoriteList()

	def add2FavList(self, newcomer):
		append = True
		newFavList = []
		for favorite in self.newFavList:
			if not weatherhelper.isDifferentLocation(newcomer, favorite):  # newcomer contains new coordinates?
				favorite = favorite if len(favorite[0]) > len(newcomer[0]) else newcomer  # use the one that has more information
				append = False  # so don't append the newcomer
			newFavList.append(favorite)
		if append:
			newFavList.append(newcomer)
		self.newFavList = newFavList

	def keyRed(self):
		current = self["favoriteList"].getCurrentIndex()
		if self.newFavList and current is not None:
			self.currFavorite = self.newFavList[current]
			if weatherhelper.isDifferentLocation(self.currFavorite, config.plugins.OAWeather.weatherlocation.value):
				msgtxt = _("Do you really want do delete favorite\n'%s'?" % self.currFavorite[0])
				weatherhelper.saveFavorites()
				self.session.openWithCallback(self.returnKeyRed, MessageBox, msgtxt, MessageBox.TYPE_YESNO, timeout=10, default=False)
			else:
				msgtxt = _("The favorite '%s' corresponds to the set weather city name and therefore cannot be deleted." % self.currFavorite[0])
				self.session.open(MessageBox, msgtxt, MessageBox.TYPE_WARNING, timeout=3)

	def returnKeyRed(self, answer):
		if answer is True and self.currFavorite in self.newFavList:
			self.newFavList.remove(self.currFavorite)
			self.updateFavoriteList()

	def keyYellow(self):
		self.currindex = self["favoriteList"].getCurrentIndex()
		if self.newFavList and self.currindex is not None:
			weathercity = weatherhelper.isolateCityname(self.newFavList[self.currindex][0])
			self.session.openWithCallback(self.returnCityname, VirtualKeyBoard, title=_("Weather cityname (at least 3 letters):"), text=weathercity)

	def keyGreen(self):
		weatherhelper.setFavoriteList(self.newFavList)
		weatherhelper.saveFavorites()

		config.plugins.OAWeather.save()
		config.save()

		self.session.open(MessageBox, _("Favorites have been successfully saved!"), MessageBox.TYPE_INFO, timeout=2)

	def keyBlue(self):
		self.addFavorite = True
		self.session.openWithCallback(self.returnCityname, VirtualKeyBoard, title=_("Weather cityname (at least 3 letters):"), text="")

	def keyOk(self):
		current = self["favoriteList"].getCurrentIndex()
		returnFavorite = self.newFavList[current] if self.newFavList and current is not None else None
		self.checkChanges(returnFavorite)

	def keyExit(self):
		self.checkChanges(None)

	def checkChanges(self, returnFavorite):
		if self.newFavList != weatherhelper.favoriteList:
			self.returnFavorite = returnFavorite
			msgtxt = _("Do you really want do exit without saving your modified favorite list?")
			self.session.openWithCallback(self.returnCheckChanges, MessageBox, msgtxt, MessageBox.TYPE_YESNO, timeout=10, default=False)
		else:
			self.close(returnFavorite)

	def returnCheckChanges(self, answer):
		if answer is True:
			self.close(self.returnFavorite)


weatherhandler = WeatherHandler()
