#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

# http://joyunspeakable.com
# david@joyunspeakable.com

# MIT License

# Copyright (c) 2017 David Garozzo

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


# Special thanks to: Matt Farley, matt@farleyfamily.net, for sharing his python script
# 	https://community.automatic.com/automatic/topics/sharing-my-websockets-real-time-notification-script?utm_source=notification&utm_medium=email&utm_campaign=new_comment&utm_content=topic_link
#	https://pastebin.com/5UM22bSj

#

# Dependency: https://github.com/invisibleroads/socketIO-client
# Install client first: sudo pip install -U socketIO-client

import indigo

import os
import random
import sys
import time
import datetime

import httplib, urllib
import json
import re
import serial

import threading

from socketIO_client import SocketIO

import requests

from requests.exceptions import ConnectionError

    
# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

################################################################################
class Plugin(indigo.PluginBase):

	vehicleId = ""
	history = {}
	history_counter = 0
	history_limit = 100
	event = {}
	car = {}
	automaticWebSocketThreadRunning = False


	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
		self.debug = True
		self.triggerList = []


	########################################
	def startup(self):
		if "debugLogging" in self.pluginPrefs:
			self.debug = self.pluginPrefs["debugLogging"]
		self.debugLog(u"startup called")

	def shutdown(self):
		self.debugLog(u"shutdown called")

	def _addVehicleToCars(self, vehicleJson):
	
		global car

		self.debugLog(u"_addVehicleToCars: %s" % (vehicleJson['id']))

		if vehicleJson['id'] not in self.car:
			self.car[ vehicleJson['id'] ] = {}
			if vehicleJson['display_name'] != None:
				self.debugLog( vehicleJson['display_name'] )
				self.car[ vehicleJson['id'] ][ 'name' ] = vehicleJson['display_name']
			else:
				self.debugLog( "%s %s %s %s" % ( vehicleJson['year'], vehicleJson['make'], vehicleJson['model'], vehicleJson['submodel'] ) )	
				self.car[ vehicleJson['id'] ][ 'name' ] = "%s %s %s %s" % ( vehicleJson['year'], vehicleJson['make'], vehicleJson['model'], vehicleJson['submodel'] )
			self.car[ vehicleJson['id'] ]['previousMilesFromHome'] = 0.0
			self.car[ vehicleJson['id'] ]['currentMilesFromHome'] = 0.0
	

	########################################
	# Poll all of the states from the API and pass new values to
	# Indigo Server.
	def _refreshStatesFromAPI(self, dev, logRefresh):

		vehicleDidUpdate = False
		
		localPropsCopy = dev.pluginProps
		
		self.debugLog( "_refreshStatesFromAPI for %s (%s)" % (dev.name, localPropsCopy["vehicle"]) )
		
		keyValueList = []
		if "vehicle" in dev.states:
			try:
				vehicleJson = self._requestVehicle(localPropsCopy["vehicle"])
				if logRefresh:
					self.debugLog(u"received \"%s\" %s to %s" % (dev.name, "vehicle", vehicleJson))
				if dev.states["vehicle"] != vehicleJson:
					vehicleDidUpdate = True
					self.debugLog(u"vehicleJson updated")
					self.debugLog(vehicleJson)
					keyValueList.append({'key':'vehicle', 'value':vehicleJson, 'uiValue':vehicleJson})

					jsonResponse = json.loads(vehicleJson)
					self._addVehicleToCars( jsonResponse )
					
			except Exception, e:
				indigo.server.log("FYI - Exception caught getting vehicle info: " + str(e))
				pass


		if "trip" in dev.states:
			try:
				tripJson = self._requestTripsForVehicle(localPropsCopy["vehicle"])
				if logRefresh:
					self.debugLog(u"received \"%s\" %s to %s" % (dev.name, "trip", tripJson))
				if dev.states["trip"] != tripJson:
					if vehicleDidUpdate:
						self.debugLog(u"tripJson updated")
						self.debugLog(tripJson)
					keyValueList.append({'key':'trip', 'value':tripJson, 'uiValue':tripJson})
			except Exception, e:
				indigo.server.log("FYI - Exception caught getting trip info: " + str(e))
				pass

		if "user" in dev.states:
			try:
				userJson = self._requestUser()
				if logRefresh:
					self.debugLog(u"received \"%s\" %s to %s" % (dev.name, "user", userJson))
				if dev.states["user"] != userJson:
					self.debugLog(u"userJson updated")
					self.debugLog(userJson)
					keyValueList.append({'key':'user', 'value':userJson, 'uiValue':userJson})
			except Exception, e:
				indigo.server.log("FYI - Exception caught getting user info: " + str(e))
				pass

		if "tag" in dev.states:
			try:
				tagJson = self._requestTags()
				if logRefresh:
					self.debugLog(u"received \"%s\" %s to %s" % (dev.name, "tag", tagJson))
				if dev.states["tag"] != tagJson:
					self.debugLog(u"tagJson updated")
					self.debugLog(tagJson)
					keyValueList.append({'key':'tag', 'value':tagJson, 'uiValue':tagJson})
			except Exception, e:
				indigo.server.log("FYI - Exception caught getting tag info: " + str(e))
				pass

		dev.updateStatesOnServer(keyValueList)

	def on_connect(self):
		indigo.server.log(u"socketIO connect")

	def on_disconnect(self):
		indigo.server.log(u"socketIO disconnect")

	def on_reconnect(self):
		indigo.server.log(u"socketIO reconnect")


	"""
		Websocket Error ****************************************************
	"""
	def on_error(self, *args):
		indigo.server.log('on_error start')
		for arg in args:
			indigo.server.log(str(arg))
		indigo.server.log('on_error end')


	"""
		Triage websocket events, decide what to do ****************************************************
	"""
	
	######################################################################################
	# Indigo Trigger Start/Stop
	######################################################################################

	def triggerStartProcessing(self, trigger):
		self.debugLog(u"<<-- entering triggerStartProcessing: %s (%d)" % (trigger.name, trigger.id))
		self.triggerList.append(trigger.id)
		self.debugLog(u"exiting triggerStartProcessing -->>")

	def triggerStopProcessing(self, trigger):
		self.debugLog(u"<<-- entering triggerStopProcessing: %s (%d)" % (trigger.name, trigger.id))
		if trigger.id in self.triggerList:
			self.debugLog(u"TRIGGER FOUND")
			self.triggerList.remove(trigger.id)
		self.debugLog(u"exiting triggerStopProcessing -->>")
	
	######################################################################################
	# Indigo Trigger Firing
	######################################################################################

	def triggerEvent(self, carId, eventId):
		self.debugLog(u"<<-- entering triggerEvent: %s " % eventId)
		for trigId in self.triggerList:
			trigger = indigo.triggers[trigId]
			if trigger.pluginTypeId == eventId:
				self.debugLog( u"%s %s" % (trigger.pluginProps[u'vehicle'], str(carId) ) )
				if trigger.pluginProps[u'vehicle'] == str(carId):
					indigo.trigger.execute(trigger)
		return
	
	
	
	# *args can accept multiple arguments, coming through as args[0], args[1], etc
	def triage(self, *args):

		#self.debugLog("triage start")

		#for arg in args:
		#	indigo.server.log(str(arg))
		#	indigo.server.log( arg["type"] )

		# Any globals that will be modified must be called out
		global event
		global history
		global history_counter
		global vehicleId
		global car

		# Car ID to isolate tracking without cross-talk confusion
		self.vehicleId = args[0]['vehicle']['id']
		#indigo.server.log(str(self.vehicleId))
		if self.vehicleId not in self.car:
			self._addVehicleToCars( json.loads( self._requestVehicle( self.vehicleId ) ) )

		carName = self.car[ self.vehicleId ][ 'name' ]
		#self.debugLog(str(carName))

		# Test for new event but occurs prior to an event we already received (thus can be disregarded, even though we missed it, tan-pis)
		# Will error on the first event since there's no last event    
		try:
			newTimestamp = datetime.datetime.strptime(args[0]['location']['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ');
			lastTimestamp = datetime.datetime.strptime(self.event[self.vehicleId]['location']['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ');
			#self.debugLog("newTimestamp: " + str(newTimestamp.isoformat(' ')))
			#self.debugLog("lastTimestamp: " + str(lastTimestamp.isoformat(' ')))
			if newTimestamp < lastTimestamp:
				#self.debugLog("Skipping historic lagging event, we already received newer events: " + args[0]['type'])
				return
		except Exception, e:
			indigo.server.log("FYI - Exception testing newTimestamp vs Old Timestamp (normal for first event received): " + str(e))
			pass

		# capture the previous event type so we can be able to emulate a possible missing ignition:on event
		try:
			previousEventType = self.event[self.vehicleId]['type']
		except Exception, e:
			# first time through... just assume the ignition was off before this
			previousEventType = "ignition:off"

		# Capture all the json data in event
		self.event[self.vehicleId] = args[0];

		# Test for duplicate
		if self.event[self.vehicleId]['id'] in self.history.values():
			self.debugLog("Skipping duplicate: " + self.event[self.vehicleId]['type'])
			return


		# which device are we getting a trigger for?
		devTriggered = {}
		try:
			for dev in indigo.devices.iter("self"):
				# each dev will be one that matches one of our custom plugin devices
				if( self.vehicleId == dev.pluginProps["vehicle"] ):
					self.debugLog(dev.name)
					devTriggered = dev
					break
		except Exception, e:
			indigo.server.log("FYI - Exception caught looking for trigger device: " + str(e))
		
		
		# update the device's states
		if( devTriggered != {} ):
			self._refreshStatesFromAPI(devTriggered, False)
		else:
			indigo.server.log("Trigger received, but no device found for it")
			return

		# New notification, record it to history
		if self.history_counter > self.history_limit: self.history_counter = 0
		self.history[self.history_counter] = self.event[self.vehicleId]['id']
		self.history_counter += 1    

		# Share what we're dealing with
		eventType = self.event[self.vehicleId]['type']
		if eventType != 'location:updated':
			indigo.server.log(carName + ":" + eventType + " @ " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
		else:

			# it seems like sometimes I don't get the ignition:on event, so the first event I get
			# is location:updated when a drive starts. So, check to see if the previous event
			# was ignition:off or trip:finished. If so, and the current event is location:updated,
			# trigger the ignition:on event.
			if previousEventType == 'ignition:off' or previousEventType == 'trip:finished':
				self.triggerEvent(self.vehicleId, "ignition_on")
		
		# sound an Event that can be used for Triggering
		self.triggerEvent(self.vehicleId, eventType.replace(":", "_"))


		# Google Location Geocode and Distance Matrix ETA
		self.debugLog( "getting ETA" )
		ETA = self.getETA(self.vehicleId)

		self.debugLog( "getting location" )
		location = self.getLocation(self.vehicleId)

		self.debugLog( "updating miles" )
		
		if self.event[self.vehicleId]['type'] == 'ignition:on':
			self.car[self.vehicleId]['previousMilesFromHome'] = 0.0
			self.car[self.vehicleId]['currentMilesFromHome'] = 0.0
			self.debugLog(self.car[self.vehicleId]['name'] + " Started; Ignition on at " + location + ", " + ETA)

		if self.event[self.vehicleId]['type'] == 'ignition:off':
			self.car[self.vehicleId]['previousMilesFromHome'] = 0.0
			self.car[self.vehicleId]['currentMilesFromHome'] = 0.0
			self.debugLog(self.car[self.vehicleId]['name'] + " Parked; Ignition off at " + location)

		if self.event[self.vehicleId]['type'] == 'trip:finished':
			self.car[self.vehicleId]['previousMilesFromHome'] = 0.0
			self.car[self.vehicleId]['currentMilesFromHome'] = 0.0
			self.debugLog(self.car[self.vehicleId]['name'] + " Parked; Trip finished at " + location)

		if self.event[self.vehicleId]['type'] == 'location:updated':
		
			self.debugLog('PreviousMiles = ' + str(self.car[self.vehicleId]['previousMilesFromHome']));
			self.debugLog('CurrentMiles = ' + str(self.car[self.vehicleId]['currentMilesFromHome']));
		
			try:
				percentChange = ((self.car[self.vehicleId]['previousMilesFromHome'] - self.car[self.vehicleId]['currentMilesFromHome']) / self.car[self.vehicleId]['previousMilesFromHome']) * 100
			except Exception, e:
				# Divide by zero when car[vehicleId]['previousMilesFromHome'] is zero
				percentChange = 0.0
				self.car[self.vehicleId]['previousMilesFromHome'] = self.car[self.vehicleId]['currentMilesFromHome']            
			
			# Only notify en route if there is a significant change in progress towards the house (or we're less than a mile away)
			if percentChange > 50.0 or self.car[self.vehicleId]['currentMilesFromHome'] == 0.0:
				self.car[self.vehicleId]['previousMilesFromHome'] = self.car[self.vehicleId]['currentMilesFromHome']
				if percentChange > 50.0:
					self.triggerEvent(self.vehicleId, 'approaching_home')
				indigo.server.log(self.car[self.vehicleId]['name'] + " En Route; At " + location + ", " + ETA)
			else:
				self.debugLog("Skipping due to lack of progress *towards* home; percent change = " + str(percentChange)) 


		# update the device's states again - for miles from home and eta
		if "ETA" in devTriggered.states:
			if devTriggered.states["ETA"] != ETA:
				devTriggered.updateStateOnServer( 'ETA', value=ETA )

		
		if "location" in devTriggered.states:
			if devTriggered.states["location"] != location:
				devTriggered.updateStateOnServer( 'location', value=location )


		if "previousMilesFromHome" in devTriggered.states:
			if devTriggered.states["previousMilesFromHome"] != self.car[self.vehicleId]['previousMilesFromHome']:
				devTriggered.updateStateOnServer( 'previousMilesFromHome', value=self.car[self.vehicleId]['previousMilesFromHome'] )


		if "currentMilesFromHome" in devTriggered.states:
			if devTriggered.states["currentMilesFromHome"] != self.car[self.vehicleId]['currentMilesFromHome']:
				devTriggered.updateStateOnServer( 'currentMilesFromHome', value=self.car[self.vehicleId]['currentMilesFromHome'] )
		
		self.debugLog("triage end")    


	"""
		Get ETA via Google Distance Matrix ****************************************************
	"""
	def getETA(self, vehicleId):

		# Any globals that will be modified must be called out
		global event
		global history
		global history_counter
		global car

		try:
			self.debugLog( "getETA for %s" % vehicleId )
			
			googleMapsApiKey = self.pluginPrefs["googleMapsAPIKey"]
			
			##self.debugLog( googleMapsApiKey )

			theUrl = 'https://maps.googleapis.com/maps/api/distancematrix/json?origins='+str(self.event[vehicleId]['location']['lat'])+','+str(self.event[vehicleId]['location']['lon'])+'&' + urllib.urlencode({'destinations':self.pluginPrefs["homeAddress"]}) + '&key='+googleMapsApiKey+'&units=imperial'
			self.debugLog( theUrl )
			
			response = requests.get(theUrl, timeout=2)
			
			self.debugLog( response.text )
			
			json_data = json.loads(response.text)
		
			text = json_data['rows'][0]['elements'][0]['duration']['text']
			seconds = json_data['rows'][0]['elements'][0]['duration']['value']
		
			timestamp = datetime.datetime.strptime(self.event[vehicleId]['location']['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
			timestamp = timestamp - datetime.timedelta(hours=4)
		
			# Give ETA as event timestamp plus google travel time to home
			ETA = timestamp + datetime.timedelta(seconds=seconds)
		
			self.debugLog( ETA )
			
			# Record last ETA Distance and this ETA Distance to help determine if we'll notify en route
			distance = str(json_data['rows'][0]['elements'][0]['distance']['text']).split()
			if distance[1] == 'mi':
				self.car[vehicleId]['currentMilesFromHome'] = float(distance[0]);
			else:
				self.car[vehicleId]['currentMilesFromHome'] = 0.0;
		
			self.debugLog( text + " / " + str(self.car[vehicleId]['currentMilesFromHome']) + " miles from home, ETA " + ETA.strftime("%I:%M %p") )
		
			conn.close()
			return text + " / " + str(self.car[vehicleId]['currentMilesFromHome']) + " miles from home, ETA " + ETA.strftime("%I:%M %p")
		except Exception, e:
			conn.close()
			indigo.server.log('Location unknown, distance matrix calculation failed: ' + str(e))
			return 'unknown ETA'

	"""
		Google Geocode Location ****************************************************
	"""
	def getLocation(self, vehicleId):

		# Any globals that will be modified must be called out
		global event
		global history
		global history_counter
		global car
		
		text = 'unknown location'    

		try:
			self.debugLog("getLocation %s" % vehicleId)

			googleMapsApiKey = self.pluginPrefs["googleMapsAPIKey"]
	
			#self.debugLog( googleMapsApiKey )
			
			apiURL = 'https://maps.googleapis.com/maps/api/geocode/json?latlng='+str(self.event[vehicleId]['location']['lat'])+','+str(self.event[vehicleId]['location']['lon'])+'&key='+googleMapsApiKey
			##self.debugLog( apiURL )
						
			response = requests.get(apiURL, timeout=2)

			##self.debugLog( response.text )

			json_data = json.loads(response.text)

			for component in json_data['results'][0]['address_components']:
				self.debugLog( "for loop address_components" )
				if component['types'][0] == 'route':
					text = component['long_name']
					self.debugLog( "route found %s" % text )
					break
		except Exception, e:
			indigo.server.log('Location unknown, geocode failed: ' + str(e))
			pass
	
		conn.close()

		self.debugLog( "getLocation: %s" % text )
		return text

	def AutomaticWebSocketThread(self):
		global automaticWebSocketThreadRunning
		try:
			self.automaticWebSocketThreadRunning = True
			
			self.debugLog(u"AutomaticWebSocketThread starting...")

			io = SocketIO('https://stream.automatic.com', 443, params={'token': self.pluginPrefs['clientId'] + ':' + self.pluginPrefs['clientSecret']}, wait_for_connection=False)
			io.on('connect', self.on_connect)
			io.on('disconnect', self.on_disconnect)
			io.on('reconnect', self.on_reconnect)
			io.on('trip:finished', self.triage)
			io.on('location:updated', self.triage)
			io.on('ignition:on', self.triage)
			io.on('ignition:off', self.triage)
			io.on('notification:speeding', self.triage)
			io.on('notification:hard_break', self.triage)
			io.on('notification:hard_accel', self.triage)
			io.on('mil:on', self.triage)
			io.on('mil:off', self.triage)
			io.on('error', self.on_error)
			io.wait()
			self.automaticWebSocketThreadRunning = False
			indigo.server.log(u"SocketIO no longer waiting")
		except ConnectionError:
			self.automaticWebSocketThreadRunning = False
			indigo.server.log(u"The server is down. Try again later.")

	########################################
	def runConcurrentThread(self):
		global automaticWebSocketThreadRunning
		try:		
			#indigo.server.log( str(threading.activeCount()) )
			### TODO
			#self._refreshAccessToken();
			while True:
				if self.automaticWebSocketThreadRunning == False:
					tw = threading.Thread(target=self.AutomaticWebSocketThread)
					tw.start()
					self.debugLog("AutomaticWebSocketThread started")
				#self.debugLog(u"runConcurrentThread")
				for dev in indigo.devices.iter("self"):
					if not dev.enabled or not dev.configured:
						indigo.server.log(u"runConcurrentThread:dev not enabled or configured")
						continue

					#self._refreshStatesFromAPI(dev, False)
				self.sleep(60)
		except self.StopThread:
			pass	# Optionally catch the StopThread exception and do any needed cleanup.

	########################################
	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		return (True, valuesDict)

	########################################
	def validatePrefsConfigUi(self, valuesDict):
		self.debug = valuesDict["debugLogging"]
		return (True, valuesDict)

	########################################
	def deviceStartComm(self, dev):
		# Called when communication with the hardware should be established.
		# Here would be a good place to poll out the current states from the
		# meter. If periodic polling of the meter is needed (that is, it
		# doesn't broadcast changes back to the plugin somehow), then consider
		# adding that to runConcurrentThread() above.
		self.debugLog(u"deviceStartComm")
		self._refreshStatesFromAPI(dev, True)

	def deviceStopComm(self, dev):
		# Called when communication with the hardware should be shutdown.
		pass


	########################################
	# Custom Plugin Action callbacks (defined in Actions.xml)
	######################
	def doRefreshStatesFromAPI(self, pluginAction, dev):

		self._refreshStatesFromAPI(dev, True)


	############################
	# Devices.xml callback methods
	############################

	def _refreshAccessToken(self):
	
		jsonResponse = json.loads(self.pluginPrefs['accessTokenJson'])
		
		data = self._requestAccessToken(jsonResponse["refresh_token"], self.pluginPrefs['clientId'], self.pluginPrefs['clientSecret'], "refresh_token")

		self._saveAccessToken(data)

	def _requestData(self, target, paramsList={}):
	
		data = ""
		try:
			jsonResponse = json.loads(self.pluginPrefs['accessTokenJson'])
			self.debugLog("Bearer %s" % jsonResponse["access_token"])
	
			params = urllib.urlencode(paramsList)

			if params != "":
				params = "?" + params

			headersData = {"Content-type": "application/x-www-form-urlencoded", "Authorization": "Bearer %s" % jsonResponse["access_token"]}

			r = requests.get('https://api.automatic.com/' + target + '/' + params, timeout=2, headers=headersData)
			data = r.text

		except Exception, e:
			indigo.server.log("FYI - Exception caught _requestData: " + str(e))

		return data

	def _requestVehicle(self, vehicleId):

		data = self._requestData("vehicle/" + str(vehicleId) + "/")
		return data

	def _requestVehicles(self):
	
		data = self._requestData("vehicle")
		return data

	def _requestTrips(self):
	
		data = self._requestData("trip", { 'started_at__gte': 1431126000, 'started_at__lte':2545951522, 'limit':1 } ) #long(time.time()) } ) #, 'ended_at__gte':1431126000, 'ended_at__lte':long(time.time()) } )
		return data

	def _requestTripsForVehicle(self, vehicleId):
	
		data = self._requestData("trip", { 'started_at__gte': 1431126000, 'started_at__lte':2545951522, 'limit':1, 'vehicle':str(vehicleId) } ) #long(time.time()) } ) #, 'ended_at__gte':1431126000, 'ended_at__lte':long(time.time()) } )
		return data

	def _requestUser(self):
	
		data = self._requestData("user/me")
		return data

	def _requestTags(self):
	
		data = self._requestData("tag")
		return data

	def getAuthorization(self, valuesDict):
		
		self.debugLog(u"getAuthorization")
		
		currentLocation = ""
		if valuesDict["automaticLocationApproved"]:
			currentLocation = "scope:current_location%20"
		self.pluginPrefs["automaticLocationApproved"] = valuesDict["automaticLocationApproved"]
		
		authorizationURL = "https://accounts.automatic.com/oauth/authorize/?client_id=%s&response_type=code&scope=%sscope:public%%20scope:user:profile%%20scope:location%%20scope:vehicle:profile%%20scope:vehicle:events%%20scope:trip%%20scope:behavior" % (valuesDict["clientId"], currentLocation)
		self.debugLog( authorizationURL )
		self.browserOpen( authorizationURL )
		
		return valuesDict

	def _requestAccessToken(self, code, clientId, clientSecret, grantType):
		data = ""
		try:
			if grantType == "refresh_token":
				codeType = "refresh_token"
				postURL = "/oauth/access_token/"
			else:
				codeType = "code"
				postURL = "/oauth/access_token"

			headersData = {"Content-type": "application/x-www-form-urlencoded", "Accept": "*/*", "User-Agent": "AutomaticOBDPlugin"}
			r = requests.post('https://accounts.automatic.com' + postURL, timeout=2, headers=headersData, data={'client_id': clientId, 'client_secret': clientSecret, codeType: code, 'grant_type': grantType})
			data = r.text

			indigo.server.log(data)
		except Exception, e:
			indigo.server.log("FYI - Exception caught _requestAccessToken: " + str(e))

		return data
		
	def _saveAccessToken(self, data):

		try:
			jsonResponse = json.loads(data)
			
			# this will throw if access_token does not exist
			indigo.server.log(jsonResponse["access_token"])

			# store the access token!
			# or maybe store the whole response??
			self.pluginPrefs["accessTokenJson"] = data
			
			return True
		except Exception, e:
			indigo.server.log("FYI - Exception caught saving access token: " + str(e))
			return False

	def getAccessToken(self, valuesDict):
		
		self.debugLog(u"getAccessToken")
		
		valuesDict["accessTokenFailCheckbox"] = "false"
	
		# extract value of code from the CallbackURL
		m = re.search('code=([0-9a-f]*)', valuesDict["callbackURL"])

		if m:
			code = m.group(1)
			self.debugLog(code)
		else:
			self.debugLog( 'invalud URL format - code not found' )
			valuesDict["callbackURL"] = ""
			valuesDict["accessTokenFailCheckbox"] = "true"
			return valuesDict
		
		data = self._requestAccessToken(code, valuesDict["clientId"], valuesDict["clientSecret"], 'authorization_code')

		if self._saveAccessToken(data):

			try:
				self.pluginPrefs["clientId"] = valuesDict["clientId"]
				self.pluginPrefs["clientSecret"] = valuesDict["clientSecret"]

				valuesDict["accessTokenFailCheckbox"] = "success"
				valuesDict["accessTokenJson"] = data

			except Exception, e:
				indigo.server.log("FYI - Exception caught saving clientId and Secret: " + str(e))			
			
		else:
			indigo.server.log( 'unable to save access_token' )
			valuesDict["callbackURL"] = ""
			valuesDict["accessTokenJson"] = ""
			valuesDict["accessTokenFailCheckbox"] = "true"
		
		return valuesDict

	def _getVehicles(self):
	
		self.debugLog(u"_getVehicles")
		
		data = self._requestVehicles()
		
		self.debugLog(data)
		jsonResponse = json.loads(data)
		
		myArray = []
		for result in jsonResponse["results"]:
			if result['display_name'] != None:
				self.debugLog( result['display_name'] )
				myArray.append( [ result['id'], result['display_name'] ] )
			else:
				self.debugLog( "%s %s %s %s" % ( result['year'], result['make'], result['model'], result['submodel'] ) )	
				myArray.append( ( [ result['id'], "%s %s %s %s" % ( result['year'], result['make'], result['model'], result['submodel'] ) ] ) )

		return myArray

	def getVehiclesList(self, filter="", valuesDict=None, typeId="", targetId=0):
	
		myArray = []
		
		try:
			self.debugLog(u"getVehiclesList")
			myArray = self._getVehicles()
		except Exception, e:
			indigo.server.log("FYI - Exception caught getting vehicles list: " + str(e))
			
		return myArray
		
