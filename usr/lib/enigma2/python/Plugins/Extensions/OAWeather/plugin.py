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
# along with OAWeather.  If not, see <http://www.gnu.org/licenses/>.

# Some parts are taken from MetrixHD skin and MSNWeather Plugin.
# mod by lululla 20250629
# -fix asiatic language and icons 20250706
# -refactory favoritelist

import json
import logging
import pickle
import sys
from datetime import datetime, timedelta
from time import time
from xml.etree.ElementTree import parse, tostring

from os import fsync, listdir, remove, chmod, replace  # , stat
from os.path import exists, expanduser, getmtime, isfile, join

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
    ConfigText,
    configfile
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
OAWEATHER_FAV = resolveFilename(SCOPE_CONFIG, "oaweather_fav.json")
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
    log_file = "/tmp/OAWeather.log"
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


class WeatherHelper():
    def __init__(self):
        self.version = __version__
        self.favoritefile = self.get_writable_path(OAWEATHER_FAV)
        logger.info(f"Using favorite file: {self.favoritefile}")
        self.locationDefault = ("Frankfurt am Main, DE", 8.68417, 50.11552)
        self.favoriteList = []

        try:
            self.readFavoriteList()
            self.syncWithConfig()
        except Exception as e:
            logger.error(f"Initialization error: {str(e)}")
            config.plugins.OAWeather.weathercity.value = GEODATA[0]
            config.plugins.OAWeather.owm_geocode.value = GEODATA[1]
            config.plugins.OAWeather.weathercity.save()
            config.plugins.OAWeather.owm_geocode.save()

    @staticmethod
    def searchLocation(city_name, callback, session):
        """Static method to search locations safely"""
        try:
            # Get the active weather service
            service = config.plugins.OAWeather.weatherservice.value
            apikey = config.plugins.OAWeather.apikey.value

            # Initialize weather info
            WI = Weatherinfo(service, apikey)
            if WI.error:
                raise Exception(WI.error)

            # Get city list
            geodatalist = WI.getCitylist(
                city_name,
                config.osd.language.value.replace('_', '-').lower()
            )

            if not geodatalist:
                raise Exception(_("No locations found"))

            # Prepare results
            results = [(item[0], float(item[1]), float(item[2])) for item in geodatalist]

            # Show selection screen
            session.openWithCallback(
                lambda result: WeatherHelper._safeCallback(callback, result),
                ChoiceBox,
                title=_("Select location"),
                list=[(f"{item[0]} [lon={item[1]:.3f}, lat={item[2]:.3f}]", item) for item in results]
            )

        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            WeatherHelper._safeCallback(callback, None)
            session.open(MessageBox, str(e), MessageBox.TYPE_ERROR)

    @staticmethod
    def _safeCallback(callback, result):
        """Safely execute callback if it exists"""
        if callable(callback):
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Callback error: {str(e)}")

    def syncWithConfig(self):
        current_city = config.plugins.OAWeather.weathercity.value
        current_geocode = config.plugins.OAWeather.owm_geocode.value
        if current_city and current_geocode and current_city != self.locationDefault[0]:
            try:
                lon, lat = current_geocode.split(",")
                location = (current_city, float(lon), float(lat))
                if location not in self.favoriteList:
                    self.addFavorite(location)
                config.plugins.OAWeather.weatherlocation.value = location
                config.plugins.OAWeather.weatherlocation.save()
            except Exception as e:
                logger.error(f"Error syncing config: {str(e)}")

    def get_writable_path(self, filename):
        paths_to_try = [
            resolveFilename(SCOPE_CONFIG, filename),
            resolveFilename(SCOPE_HDD, filename),
            "/tmp/" + filename,
            expanduser("~/" + filename)
        ]

        for path in paths_to_try:
            try:
                testfile = path + ".test"
                with open(testfile, "w") as f:
                    f.write("test")
                remove(testfile)
                logger.info(f"Writable path found: {path}")
                return path
            except Exception as e:
                logger.warning(f"Path not writable: {path} - {str(e)}")

        fallback = "/tmp/" + filename
        logger.warning(f"Using fallback path: {fallback}")
        return fallback

    def saveFavorites(self):
        """Improved version but with the same name for compatibility"""
        try:
            logger.info("Saving %d favorites to %s" % (len(self.favoriteList), self.favoritefile))

            temp_file = "%s.tmp" % self.favoritefile
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.favoriteList, f, indent=2, ensure_ascii=False)
                f.flush()
                fsync(f.fileno())

            replace(temp_file, self.favoritefile)
            chmod(self.favoritefile, 0o644)

            logger.info("Favorites saved successfully")
            return True

        except Exception as e:
            logger.error("Main save error: %s" % str(e))

            try:
                fallback = resolveFilename(SCOPE_CONFIG, "oaweather_fav.json")
                with open(fallback, "w", encoding="utf-8") as f:
                    json.dump(self.favoriteList, f, indent=2, ensure_ascii=False)
                logger.info("Fallback used: %s" % fallback)
                return True
            except Exception as fallback_error:
                logger.critical("Fallback error: %s" % str(fallback_error))
                return False

    def showFavoriteSelection(self, session, callback):
        choiceList = [(item[0], item) for item in self.favoriteList]
        session.openWithCallback(
            lambda favorite: self.handleFavoriteSelection(favorite, callback) if favorite else None,
            ChoiceBox,
            title=_("Select location"),
            list=choiceList
        )

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

    def handleFavoriteSelection(self, favorite, callback=None):
        if favorite is None:
            return

        try:
            # Extract location data
            location = favorite[1] if isinstance(favorite, tuple) and len(favorite) > 1 else favorite

            # Add to favorites if not already present
            if not any(not self.isDifferentLocation(location, fav) for fav in self.favoriteList):
                self.addFavorite(location)

            # Update config
            config.plugins.OAWeather.weatherlocation.value = location
            config.plugins.OAWeather.weathercity.value = location[0]
            config.plugins.OAWeather.owm_geocode.value = f"{location[1]},{location[2]}"
            config.plugins.OAWeather.save()
            config.save()

            logger.info(f"Location set to: {location[0]}")

            # Refresh weather data
            if callback:
                callInThread(weatherhandler.reset, location, callback)
            else:
                callInThread(weatherhandler.reset, location)

        except Exception as e:
            logger.error(f"Error handling favorite selection: {str(e)}")
            raise

    def returnFavoriteChoice(self, favorite):
        if favorite is not None:
            config.plugins.OAWeather.weatherlocation.value = favorite[1]
            config.plugins.OAWeather.weatherlocation.save()
            weatherhelper.addFavorite(favorite[1])
            callInThread(weatherhandler.reset, favorite[1], self.configFinished)

    def setFavoriteList(self, favoriteList):
        self.favoriteList = favoriteList

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


"""
this config goes after helper class!!!
config.plugins.OAWeather.weatherlocation
It is not a setting that the user changes directly in the UI
It is managed automatically through:
Selecting favorites
Searching for new locations
"""
weatherhelper = WeatherHelper()
weatherhelper.readFavoriteList()
choiceList = [(item, item[0]) for item in weatherhelper.favoriteList]
config.plugins.OAWeather.weatherlocation = ConfigSelection(default=weatherhelper.locationDefault, choices=[])
weatherhelper.updateConfigChoices()


class WeatherSettingsViewNew(ConfigListScreen, Screen):

    def __init__(self, session):
        self.session = session
        self.skin = weatherhelper.loadSkin("WeatherSettingsViewNew")
        """
        # skintext = ""
        # xml = parse(join(PLUGINPATH, "skinconfig.xml")).getroot()
        # for screen in xml.findall('screen'):
            # if screen.get("name") == "WeatherSettingsViewNew":
                # skintext = tostring(screen).decode()
        # self.skin = skintext
        """
        Screen.__init__(self, session)
        self.setTitle(_('Setup'))
        self.status = ""
        self["status"] = Label()
        Neue_keymap = '/usr/lib/enigma2/python/Plugins/Extensions/OAWeather/keymap.xml'
        readKeymap(Neue_keymap)
        self.old_weatherlocation = config.plugins.OAWeather.weatherlocation.value
        self.old_weatherservice = config.plugins.OAWeather.weatherservice.value
        self.onChangedEntry = []
        self.list = []
        ConfigListScreen.__init__(self, self.list, session=self.session, on_change=self.changedEntry)

        self["key_green"] = StaticText(_("Save"))
        self["key_blue"] = StaticText(_("Add Fav"))
        self["key_yellow"] = StaticText(_("Defaults"))
        self["key_red"] = StaticText(_("Select location"))
        self["blueActions"] = HelpableActionMap(
            self,
            ["ColorActions", "OkCancelActions", "OAWeatherActions"],
            {
                "ok": self.keyOK,
                "left": self.keyLeft,
                "right": self.keyRight,
                "cancel": self.close,
                "green": self.keySave,
                "blue": self.addCurrentToFavorites,
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
        if len(weathercity) < 3:
            self.showError(_("City name must be at least 3 characters"))
            return

        self.closeonsave = closesave
        weatherhelper.searchLocation(weathercity, self.returnCityChoice, self.session)

    def returnCityChoice(self, selected_city_str):
        if not selected_city_str:
            return

        try:
            city_part, coords_part = selected_city_str.split('[', 1)
            city_name = city_part.strip()
            lon_str, lat_str = coords_part.replace(']', '').split(',')
            lon = float(lon_str.replace('lon=', '').strip())
            lat = float(lat_str.replace('lat=', '').strip())

            location = (
                weatherhelper.reduceCityname(city_name),
                lon,
                lat
            )

            if getattr(self, 'addFavorite', False):
                if not self.add2FavList(location):
                    self.session.open(
                        MessageBox,
                        _("Location already in favorites"),
                        MessageBox.TYPE_INFO,
                        timeout=3
                    )
                self.addFavorite = False
            else:
                curr_idx = getattr(self, 'currindex', 0)
                if curr_idx < len(getattr(self, 'newFavList', [])):
                    self.newFavList[curr_idx] = location

            if hasattr(self, 'updateFavoriteList'):
                self.updateFavoriteList()

            config.plugins.OAWeather.weathercity.value = city_name
            config.plugins.OAWeather.owm_geocode.value = f"{lon},{lat}"

            if getattr(self, 'closeonsave', False):
                self.keySave()

        except ValueError as e:
            logger.error(f"Error parsing city selection: {str(e)}")
            self.session.open(
                MessageBox,
                _("Invalid location format"),
                MessageBox.TYPE_ERROR,
                timeout=3
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.session.open(
                MessageBox,
                _("Error processing location data"),
                MessageBox.TYPE_ERROR,
                timeout=3
            )

    def showError(self, message):
        self.session.open(MessageBox, message, MessageBox.TYPE_WARNING)

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
        configfile.save()

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

    def addCurrentToFavorites(self):
        try:
            city = config.plugins.OAWeather.weathercity.value
            lon, lat = config.plugins.OAWeather.owm_geocode.value.split(',')
            location = (city, float(lon), float(lat))

            if weatherhelper.addFavorite(location):
                self.session.open(
                    MessageBox,
                    _("Location added to favorites"),
                    MessageBox.TYPE_INFO
                )
            else:
                self.session.open(
                    MessageBox,
                    _("Location already in favorites"),
                    MessageBox.TYPE_WARNING
                )

        except Exception as e:
            logger.error(f"Error adding favorite: {str(e)}")
            self.session.open(
                MessageBox,
                _("Error saving location"),
                MessageBox.TYPE_ERROR
            )


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
        # self.currLocation = config.plugins.OAWeather.weatherlocation.value
        self.currLocation = self.getValidLocation()
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

    def getValidLocation(self):
        """Get valid location from config or use default"""
        try:
            location = config.plugins.OAWeather.weatherlocation.value
            if location and len(location) == 3:
                return location
        except:
            pass
        return weatherhelper.locationDefault

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
        """
        # skintext = ""

        # params = {
            # "picpath": join(PLUGINPATH, "Images")
        # }
        # xml = None
        # width = screenwidth.width()
        # if width >= 1920:
            # xmlpath = join(PLUGINPATH, "skinfhd.xml")
        # elif width <= 1280:
            # xmlpath = join(PLUGINPATH, "skin.xml")
        # else:
            # xmlpath = None  # No matching skin

        # if xmlpath and exists(xmlpath):
            # xml = parse(xmlpath).getroot()

        # if xml is not None:
            # for screen in xml.findall("screen"):
                # if screen.get("name") == "OAWeatherPlugin":
                    # skintext = tostring(screen).decode()
                    # for key in params:
                        # try:
                            # skintext = skintext.replace("{%s}" % key, params[key])
                        # except Exception as e:
                            # print("Error replacing key: %s -> %s" % (key, str(e)))
                    # break

        # self.skin = skintext
        """
        self.skin = weatherhelper.loadSkin("OAWeatherPlugin")
        Screen.__init__(self, session)

        try:
            weatherLocation = config.plugins.OAWeather.weatherlocation.value
            # Ensure the saved location exists in favorites
            if weatherLocation in weatherhelper.favoriteList:
                self.currFavIdx = weatherhelper.favoriteList.index(weatherLocation)
            else:
                # If not, use first favorite or default
                self.currFavIdx = 0 if weatherhelper.favoriteList else 0
                config.plugins.OAWeather.weatherlocation.value = weatherhelper.favoriteList[self.currFavIdx] if weatherhelper.favoriteList else weatherhelper.locationDefault
                config.plugins.OAWeather.weatherlocation.save()
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
        self["description"] = Label(_('GREEN: MANAGEMENT FAVORITES | MENU: SETUP | INFO: DETAILS | HOME'))
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
            ["OAWeatherActions", "ColorActions", "InfoActions"],
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
        for idx in range(1, 6):
            self["weekday%s_temp" % idx].text = ""

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
        """Opens the complete favorite management screen"""
        self.session.openWithCallback(
            self.favoriteManagementClosed,
            OAWeatherFavorites
        )

    def favoriteManagementClosed(self, result=None):
        """Callback when the favorite management screen is closed"""
        if result:
            # Update config with selected location
            config.plugins.OAWeather.weathercity.value = result[0]
            config.plugins.OAWeather.owm_geocode.value = f"{result[1]},{result[2]}"
            config.plugins.OAWeather.weatherlocation.value = result
            config.plugins.OAWeather.save()

            # Reset weather data
            callInThread(weatherhandler.reset, result, self.configFinished)

    def returnFavoriteChoice(self, favorite):
        weatherhelper.handleFavoriteSelection(favorite, self.configFinished)

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
        self.dayList = [[]]
        self.sunList = []
        self.moonList = []
        self.na = _("n/a")

        self.currdaydelta = 0
        self.currdatehour = datetime.today().replace(
            minute=0, second=0, microsecond=0
        )
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
            ["OAWeatherActions", "ColorActions", "InfoActions"],
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

        if exists(moonrisepix):
            self["moonrisepix"].instance.setPixmapFromFile(moonrisepix)
        else:
            self["moonrisepix"].hide()

        if exists(moonsetpix):
            self["moonsetpix"].instance.setPixmapFromFile(moonsetpix)
        else:
            self["moonsetpix"].hide()

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
                    _("No data"), "--", "--", "--", "--", "--",
                    "--", "--", "--", "--", "--",
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
                logger.warning(f"Unsupported service: {weatherservice}")
                self.dayList = []

            # Initialize dayList if empty
            if not hasattr(self, "dayList") or not self.dayList:
                self.dayList = [[]]  # List with one empty day
                self.session.open(
                    MessageBox,
                    _("Weather data unavailable"),
                    MessageBox.TYPE_WARNING
                )

        except Exception as e:
            logger.error(f"Data parsing error: {str(e)}")
            self.dayList = [[]]
        finally:
            self.updateDisplay()

    def msnparser(self):
        iconpath = config.plugins.OAWeather.iconset.value
        iconpath = join(ICONSETROOT, iconpath) if iconpath else join(PLUGINPATH, "Icons")
        dayList = []
        responses = weatherhandler.getFulldata().get("responses")
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
        weatherhelper.showFavoriteSelection(self.session, self.parseData)

    def returnFavoriteChoice(self, favorite):
        weatherhelper.handleFavoriteSelection(favorite, self.parseData)

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

    def nextDay(self):
        if not hasattr(self, 'dayList') or not self.dayList:
            self.session.open(
                MessageBox,
                _("Weather data unavailable"),
                MessageBox.TYPE_WARNING
            )
            return

        try:
            self.currdaydelta = (self.currdaydelta + 1) % len(self.dayList)
            self.currdatehour = datetime.today().replace(
                minute=0, second=0, microsecond=0
            ) + timedelta(days=self.currdaydelta)
            self.updateDisplay()
        except Exception as e:
            logger.error(f"Weather day change error: {str(e)}")
            self.session.open(
                MessageBox,
                _("Error changing day"),
                MessageBox.TYPE_ERROR
            )

    def prevDay(self):
        if not hasattr(self, 'dayList') or not self.dayList:
            self.session.open(
                MessageBox,
                _("Weather data unavailable"),
                MessageBox.TYPE_WARNING
            )
            return

        try:
            self.currdaydelta = (self.currdaydelta - 1) % len(self.dayList)
            self.currdatehour = datetime.today().replace(
                minute=0, second=0, microsecond=0
            ) + timedelta(days=self.currdaydelta)
            self.updateDisplay()
        except Exception as e:
            logger.error(f"Weather day change error: {str(e)}")
            self.session.open(
                MessageBox,
                _("Error changing day"),
                MessageBox.TYPE_ERROR
            )

    def updateDisplay(self):
        if hasattr(self, 'dayList') and self.dayList:
            self.updateSkinList()
            self.updateMoonData()

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

        self.favoritefile = OAWEATHER_FAV
        self._initFile()
        self.newFavList = weatherhelper.favoriteList[:]
        self.selected_index = None
        self.pending_changes = False

        self["favoriteList"] = List(enableWrapAround=True)
        self["headline"] = StaticText(_("Manage Favorites"))
        self["key_red"] = StaticText(_("Delete"))
        self["key_green"] = StaticText(_("Save"))
        self["key_yellow"] = StaticText(_("Edit"))
        self["key_blue"] = StaticText(_("Add"))

        self["actions"] = ActionMap(
            ["OAWeatherFavoritesActions", "ColorActions", "OkCancelActions"],
            {
                "ok": self.onSelect,
                "cancel": self.onCancel,
                "red": self.onDelete,
                "green": self.onSave,
                "yellow": self.onEdit,
                "blue": self.startAddFavorite,
                "up": self.onUp,
                "down": self.onDown
            },
            -1
        )
        self.onShown.append(self.initScreen)

    def _initFile(self):
        """Safely load a JSON file"""
        try:
            if not exists(self.favoritefile):
                with open(self.favoritefile, 'w') as f:
                    json.dump([], f)
                chmod(self.favoritefile, 0o644)
                logger.info(f"File creato: {self.favoritefile}")
        except Exception as e:
            logger.error(f"Errore creazione file: {str(e)}")
            raise

    def initScreen(self):
        """Initialize when screen becomes visible"""
        self._refreshList()
        self.checkCurrentLocation()

    def _refreshList(self):
        """Update the list of favorites"""
        try:
            list_items = [
                (fav[0], "Lon: %.3f, Lat: %.3f" % (fav[1], fav[2]), idx)
                for idx, fav in enumerate(self.newFavList)
            ]
            self["favoriteList"].setList(list_items)
        except Exception as e:
            logger.error("Update list error: %s" % str(e))
            self.showError(_("Error updating list"))

    def checkCurrentLocation(self):
        """Highlight current location if present"""
        current = config.plugins.OAWeather.weatherlocation.value
        if current in self.newFavList:
            idx = self.newFavList.index(current)
            self["favoriteList"].setIndex(idx)

    def startAddFavorite(self):
        """Start adding a new favorite location"""
        self.session.openWithCallback(
            self.cityNameEntered,
            VirtualKeyBoard,
            title=_("Enter city name (e.g. 'Rome, IT')"),
            text=""
        )

    def cityNameEntered(self, city_name):
        """Handle the city name entered in VirtualKeyBoard"""
        if city_name:
            self._startCitySearch(city_name)

    def _startCitySearch(self, city_name):
        """Start city search after name is entered"""
        if city_name and len(city_name) >= 3:
            weatherhelper.searchLocation(
                city_name,
                self._handleSearchResult,
                self.session
            )
        else:
            self._showMessage(_("Please enter at least 3 characters"), "warning")

    def _handleSearchResult(self, result):
        """Handle search results in different formats"""
        if not result:
            logger.debug("Search cancelled by user")
            return

        try:
            logger.debug(f"Received search result: {type(result)} - {result}")

            # CASE 1: Tuple with formatted string and separate data (MSN format)
            if (isinstance(result, tuple) and len(result) == 2 and
                    isinstance(result[0], str) and 'lon=' in result[0] and 'lat=' in result[0] and
                    isinstance(result[1], (tuple, list)) and len(result[1]) == 3):

                logger.debug("MSN format detected")
                formatted_str, data_tuple = result
                city_name = data_tuple[0]
                lon, lat = data_tuple[1], data_tuple[2]

            # CASE 2: String with coordinates in brackets
            elif isinstance(result, str) and '[' in result and ']' in result:
                logger.debug("String with coordinates detected")
                city_part, coords_part = result.split('[', 1)
                city_name = city_part.strip()
                coords = coords_part.replace(']', '').strip()

                if 'lon=' in coords and 'lat=' in coords:
                    lon_str = coords.split('lon=')[1].split(',')[0].strip()
                    lat_str = coords.split('lat=')[1].strip()
                    lon = float(lon_str)
                    lat = float(lat_str)
                else:
                    raise ValueError("Invalid coordinate format")

            # CASE 3: Simple tuple (city, lon, lat)
            elif isinstance(result, (tuple, list)) and len(result) == 3:
                logger.debug("Simple tuple format detected")
                city_name, lon, lat = result[0], result[1], result[2]

            # CASE 4: City name only (fallback)
            elif isinstance(result, str):
                logger.debug("City name only received")
                city_name = result.strip()
                lon, lat = 0.0, 0.0
                self._showMessage(_("Coordinates not available for this location"), "warning")

            else:
                error_msg = f"Unsupported result format: {type(result)}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Final validation
            if not city_name:
                error_msg = "Empty city name"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Adding new location: {city_name} ({lon}, {lat})")
            self._addToFavorites(city_name, lon, lat)

        except Exception as e:
            error_msg = f"Error processing result: {str(e)} - Raw data: {result}"
            logger.error(error_msg)
            self._showMessage(_("Error processing location data"), "error")

    def _addToFavorites(self, city, lon, lat):
        """Add validated location to favorites with simplified city name"""
        try:
            # Normalize city name: take only the part before first comma
            simple_city_name = city.split(',')[0].strip()

            new_fav = [
                simple_city_name,
                float(lon),
                float(lat)
            ]

            # Check for duplicates
            for existing in self.newFavList:
                if existing[0].lower() == simple_city_name.lower():
                    self._showMessage(_("Location already exists"), "info")
                    return
                if abs(existing[1] - float(lon)) < 0.01 and abs(existing[2] - float(lat)) < 0.01:
                    self._showMessage(_("Location with similar coordinates already exists"), "info")
                    return

            self.newFavList.append(new_fav)
            self._refreshList()
            self.pending_changes = True
            logger.info(f"Added new favorite: {new_fav}")
            self._showMessage(_("Location added successfully"), "info")

        except ValueError as e:
            logger.error(f"Invalid location data: {str(e)}")
            self._showMessage(_("Invalid location coordinates"), "error")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self._showMessage(_("Error adding location"), "error")

    def _showMessage(self, message, msg_type):
        """Show messages to the user"""
        msg_map = {
            "info": MessageBox.TYPE_INFO,
            "warning": MessageBox.TYPE_WARNING,
            "error": MessageBox.TYPE_ERROR
        }

        if isinstance(msg_type, int):
            msgtype = msg_type
        else:
            msgtype = msg_map.get(msg_type.lower(), MessageBox.TYPE_INFO)

        self.session.open(
            MessageBox,
            message,
            msgtype,
            timeout=3
        )

    def onSelect(self):
        try:
            selected = self["favoriteList"].getCurrent()
            if not selected:
                return

            logger.debug(f"Selected item RAW: {selected}")

            # Get the original data from newFavList using the index
            if isinstance(selected, (tuple, list)) and len(selected) >= 3:
                location_data = self.newFavList[selected[2]]
            else:
                # Fallback if format is different
                location_data = selected

            logger.debug(f"Location data to save: {location_data}")

            # Update all relevant config values
            config.plugins.OAWeather.weathercity.value = location_data[0]
            config.plugins.OAWeather.owm_geocode.value = f"{location_data[1]},{location_data[2]}"
            config.plugins.OAWeather.weatherlocation.value = (location_data[0], location_data[1], location_data[2])

            # Save config immediately
            config.plugins.OAWeather.save()
            configfile.save()

            # Update weatherhelper favorites if needed
            if location_data not in weatherhelper.favoriteList:
                weatherhelper.addFavorite(location_data)

            logger.info(f"Config updated to: {location_data[0]}")

            # Reset weather data with new location
            callInThread(weatherhandler.reset, location_data)

            # Close and return selected location
            self.close(location_data)

        except Exception as e:
            logger.error(f"Selection failed: {str(e)}")
            self._showMessage(_("Error selecting location"), MessageBox.TYPE_ERROR)

    def onCancel(self):
        if self.pending_changes:
            self.session.openWithCallback(
                self._handleExitConfirmation,
                MessageBox,
                _("You have unsaved changes. Save before exiting?"),
                MessageBox.TYPE_YESNO
            )
        else:
            self.close(None)

    def _handleExitConfirmation(self, result):
        if result is None:
            return
        elif result:
            self.onSave()
        else:
            self.close(None)

    def onDelete(self):
        """Delete selected favorite"""
        current = self.getCurrentFavorite()
        if current:
            self.session.openWithCallback(
                lambda result: self.confirmDelete(current, result),
                MessageBox,
                _("Delete {}?").format(current[0]),
                MessageBox.TYPE_YESNO
            )

    def confirmDelete(self, favorite, confirmed):
        """Delete location with full synchronization"""
        if confirmed:
            try:
                # 1. Remove from both lists
                if favorite in self.newFavList:
                    self.newFavList.remove(favorite)
                if favorite in weatherhelper.favoriteList:
                    weatherhelper.favoriteList.remove(favorite)

                # 2. Atomic save
                weatherhelper.saveFavorites()  # Uses helper's method

                # 3. Clear cache
                if exists(CACHEFILE):
                    remove(CACHEFILE)

                # 4. Check if deleted was active location
                current_loc = config.plugins.OAWeather.weatherlocation.value
                if current_loc == favorite:
                    config.plugins.OAWeather.weatherlocation.value = weatherhelper.locationDefault
                    config.plugins.OAWeather.weathercity.value = weatherhelper.locationDefault[0]
                    config.plugins.OAWeather.owm_geocode.value = f"{weatherhelper.locationDefault[1]},{weatherhelper.locationDefault[2]}"
                    config.plugins.OAWeather.save()
                    configfile.save()
                    weatherhandler.reset(weatherhelper.locationDefault)

                # 5. Sync all configs
                weatherhelper.syncWithConfig()

                # 6. Update UI
                self._refreshList()
                self._showMessage(_("Location deleted"), MessageBox.TYPE_INFO)

            except Exception as e:
                logger.error(f"Delete error: {str(e)}")
                self._showMessage(_("Delete failed"), MessageBox.TYPE_ERROR)

    def onSave(self):
        try:
            # Update both lists
            weatherhelper.favoriteList = self.newFavList[:]

            weatherhelper.saveFavorites()

            if exists(CACHEFILE):
                remove(CACHEFILE)

            self.pending_changes = False
            self._showMessage(_("Favorites saved successfully"), "info")

            weatherhelper.updateConfigChoices()

        except Exception as e:
            logger.error(f"Save error: {str(e)}")
            self._showMessage(_("Error saving favorites"), "error")

    def onEdit(self):
        """Edit selected item"""
        current = self.getCurrentFavorite()
        if current:
            self.selected_index = self["favoriteList"].getIndex()
            self.session.openWithCallback(
                self.handleEditResult,
                VirtualKeyBoard,
                title=_("Edit city name"),
                text=current[0]
            )

    def handleEditResult(self, new_name):
        """Handle edit result"""
        if new_name and self.selected_index is not None:
            try:
                old = self.newFavList[self.selected_index]
                self.newFavList[self.selected_index] = (new_name, old[1], old[2])
                self.pending_changes = True
                self._refreshList()
            except IndexError:
                self.showError(_("Invalid selection"))

    def getCurrentFavorite(self):
        """Return currently selected favorite"""
        idx = self["favoriteList"].getIndex()
        if 0 <= idx < len(self.newFavList):
            return self.newFavList[idx]
        return None

    def handleExitConfirmation(self, result, return_value):
        """Handle exit decision"""
        if result is None:
            return
        elif result:
            self.onSave()
        else:
            self.close(return_value)

    def onUp(self):
        self["favoriteList"].up()

    def onDown(self):
        self["favoriteList"].down()


class TestScreen(Screen):
    """Does not affect performance (used only in debug)"""
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


weatherhandler = WeatherHandler()
