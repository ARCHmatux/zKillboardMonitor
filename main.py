#!/usr/bin/env python3
import os
import sys
import json
import logging
import requests
import signal
import sqlite3
import time

from discord_webhook import DiscordWebhook, DiscordEmbed
import humanize

# Configurables
configurationFilePath = "configuration.json"
loglevel = "INFO"
# End Configurables

# Class Poller - Functionality to read from zKillboard RedisQ interface
class Poller(object):
    def __init__(self, redisqURL):
        self.is_running = False
        self.url = redisqURL
        self.statistics = {
            'killmails_recieved': 0
        }
        signal.signal(signal.SIGTERM, self.handle_sigterm)
        logging.info("Poller: Initialized.")
    def run(self):
        self.is_running = True
        while self.is_running:
            logging.info("Poller: Polling RedisQ for Killmails.")
            try:
                response = requests.get(self.url,allow_redirects=False,timeout=30)
                if response.status_code == 200:
                    responseJson = json.loads(response.text)
                    logging.info("Poller: Recieved response.")
                    if responseJson['package'] != None:
                        logging.info("Poller: Response included killmail, yield for processing.")
                        # Run onMessage process for each recieved killmail
                        self.statistics['killmails_recieved']+=1
                        yield responseJson
                    else:
                        logging.info("Poller: Response Package was None, retrying in 10s.")
                        time.sleep(10)
                else:
                    logging.error("Poller: Attempt to contact redisq was not successful")
                    if response.status_code == 302:
                        logging.critical("Poller: Redisq attempted 302 redirect, likely banned. Exiting!")
                        sys.exit(1)
                    elif response.status_code == 400:
                        logging.error("Poller: RedisQ Returned 400 sack was null")
                        time.sleep(10)
                        continue
                    elif response.status_code == 401:
                        logging.error("Poller: RedisQ returned 401 Unauthorized!")
                        time.sleep(10)
                        continue
                    elif response.status_code == 429:
                        logging.critical("Poller: RedisQ returned 429 Rate Limited!")
                        logging.critical(response.raise_for_status())
                        logging.critical("Poller: Exiting to prevent Ban!")
                        sys.exit(1)
                    elif response.status_code == 502:
                        logging.error("Poller: Requests returned 502 Server Error Bad Gateway!")
                        time.sleep(60)
                    elif response.status_code == 521:
                        logging.error("Poller: Requests returned 521 Server Error!")
                        time.sleep(60)
                    else:
                        logging.error("Poller: Unknown or null response code: " + response.status_code + response.reason)
                        time.sleep(10)
                        continue
            except requests.exceptions.Timeout:
                logging.error("Poller: Connection Timeout. Retrying in 60s.")
                time.sleep(60)
                continue
            except requests.exceptions.ConnectionError:
                logging.error("Poller: Connection Error. Retrying in 10s.")
                time.sleep(10)
                continue
            except requests.exceptions.RequestException:
                logging.critical("Poller: Unhandled Request Exception. Closing gracefully.")
                logging.exception("Poller:")
                self.exit_gracefully()

    def handle_sigterm(self, signum, frame):
        logging.info("Poller: SIGTERM recieved")
        self.exit_gracefully()
    def exit_gracefully(self):
        logging.info("Poller: Shutting down")
        self.is_running = False
    def get_statistics(self):
        return self.statistics

# Extend DiscordWebhook to allow URL to be set by method
class DiscordWebhookStatsTracker(object):
    def __init__(self):
        self.statistics = {
            'execution_count': 0
        }
    def increment_execution(self):
        self.statistics['execution_count']+=1
    def get_statistics(self):
        return self.statistics

# ESI Cache Database Class
class ESICacheDatabase(object):
    def __init__(self, sqlitePath):
        self.path = sqlitePath
        logging.info("ESICacheDatabase: SQLite path is: " + self.path)
        if os.path.exists(self.path):
            logging.info("ESICacheDatabase: SQLite database present")
        else:
            logging.warning("ESICacheDatabase: SQLite database missing, will be created and initialized")
            self._initialize()

    def _initialize(self):
        sqlite_connection = sqlite3.connect(self.path)
        sqlite_cursor = sqlite_connection.cursor()
        sqlite_cursor.execute("""
            CREATE TABLE cache_data ( 
                ID                   INTEGER NOT NULL  PRIMARY KEY,
                Name                 VARCHAR(100) NOT NULL,
                ParentID             INTEGER,
                CHECK ( ID >= 0 ),
                CHECK ( ID <= 2147483647 )
            )
        """)
        sqlite_connection.commit()
        sqlite_connection.close()
        logging.warning("ESICacheDatabase: Database created and initialized")

    def create(self, id: int, name: str, parentID: int = None):
        # Add Try Except
        sqlite_connection = sqlite3.connect(self.path)
        sqlite_cursor = sqlite_connection.cursor()
        data = (id, name, parentID)
        sqlite_cursor.execute("INSERT INTO cache_data VALUES(?, ?, ?)", data)
        sqlite_connection.commit()
        sqlite_connection.close()
        return True

    def get(self, id: int):
        # Add Try Except
        sqlite_connection = sqlite3.connect(self.path)
        sqlite_cursor = sqlite_connection.cursor()
        rawdata = sqlite_cursor.execute("SELECT ID, Name, ParentID FROM cache_data WHERE ID = ?",(id,)).fetchone()
        logging.debug("ESICacheDatabase: Get " + str(id) + " Returned: " + str(rawdata))
        returndata = None
        if rawdata is not None:
            returndata = {
                "id": rawdata[0],
                "name": rawdata[1],
                "parent": rawdata[2]
            }
        return returndata

    def update(self):
        pass
        # This will be implemented later if required

    def delete(self):
        pass
        # This will be implemented later if required


# ESI Class
class ESILookup(object):
    def __init__(self, esiBaseURL: str, esiDataSource: str, esiIdentifier: str, esiCacheDatabase):
        self.config = {
            'baseurl': esiBaseURL,
            'datasource': esiDataSource,
            'identity': esiIdentifier
        }
        self.statistics = {
            'query_count': 0,
            'cache_hit': 0,
            'cache_miss': 0
        }
        self.cache = esiCacheDatabase

    def _updateStatistics(self):
        self.statistics['query_count']+=1

    def get_statistics(self):
        return self.statistics

    def set_baseurl(self, esiBaseURL: str):
        self.config['baseurl'] = esiBaseURL

    def set_datasource(self, esiDataSource: str):
        self.config['datasource'] = esiDataSource

    def set_baseurl(self, esiIdentifier: str):
        self.config['identity'] = esiIdentifier
    
    def _request(self, fullURL: str, headers: str):
        try:
            response = requests.get(fullURL, headers=headers, timeout=10)
            self._updateStatistics()
            return response
        except requests.exceptions.RequestException:
            logging.error("ESILookup: ESI request error.")
            logging.exception("ESILookup:")

    def lookup(self, queryType: str, queryValue: int):
        cacheResponse = self._checkcache(queryValue)
        if cacheResponse is not None:
            result = cacheResponse
        else:
            esiData = self._esilookup(queryType, queryValue)
            self._addtocache(esiData)
            result = esiData
        return result

    def _addtocache(self, esiData):
        if "parent" in esiData:
            self.cache.create(esiData['id'], esiData['name'], esiData['parent'])
        else:
            self.cache.create(esiData['id'], esiData['name'])

    def _checkcache(self, queryValue: int):
        logging.debug("ESILookup: Checking Cache for: " + str(queryValue))
        cacheResponse = self.cache.get(queryValue)
        if cacheResponse is not None:
            self.statistics['cache_hit']+=1
            logging.debug("ESILookup: Cache hit for: " + str(queryValue))
            return cacheResponse
        else:
            self.statistics['cache_miss']+=1
            logging.debug("ESILookup: Cache miss for: " + str(queryValue))
            return None

    def _esilookup(self, queryType: str, queryValue: int = None):
        headers = {
            'User-Agent': self.config['identity']
        }
        match queryType:
            case "character_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "characters/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "corporation_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "corporations/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "alliance_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "alliances/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "type_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "universe/types/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "faction":
                logging.debug("ESILookup: lookup: queryType: " + queryType)
                fullURL = self.config['baseurl'] + "universe/factions/" + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "system_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "universe/systems/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "constellation_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "universe/constellations/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case "region_id":
                logging.debug("ESILookup: lookup: queryType: " + queryType + " queryValue: " + str(queryValue))
                fullURL = self.config['baseurl'] + "universe/regions/{0}/".format(queryValue) + self.config['datasource']
                esiResponse =  self._request(fullURL, headers)
            case _:
                raise Exception("queryType was not a valid query type")

        match esiResponse.status_code :
            case 200:
                responseJson = json.loads(esiResponse.text)
                # Sanitize response
                if queryType == "faction":
                    faction = next(faction for faction in responseJson if faction['faction_id'] == queryValue)
                    cleanData = {
                        "id": queryValue,
                        "name": faction['name']
                    }
                else:
                    cleanData = {
                        "id": queryValue,
                        "name": responseJson['name']
                    }
                if queryType == "system_id":
                    cleanData.update({"parent": responseJson['constellation_id']})
                elif queryType == "constellation_id":
                    cleanData.update({"parent": responseJson['region_id']})
                return cleanData

            case _:
                if esiResponse.text:
                    logging.error("ESI Query returned non 200 response: " + str(esiResponse.status_code) + " Data: " + str(esiResponse.text))
                else:
                    logging.error("ESI Query returned non 200 response: " + str(esiResponse.status_code))
                raise Exception("ESI Response was not valid")

# Class Killmail - Used to store recieved killmails and functionality to retrieve further information and relevance for processing
class Killmail(object):
    def __init__(self, responseJson):
        # ToDo: Include logic here to determine if package is valid
        # Populate class variables from recieved data
        self.kill_id = responseJson['package']['killID']
        self.kill_timestamp = time.strptime(responseJson['package']['killmail']['killmail_time'],"%Y-%m-%dT%H:%M:%S%z")
        self.kill_raw_data = responseJson['package']['killmail']
        self.kill_zkill_data = responseJson['package']['zkb']
        self.kill_additional_data_pulled = False
        self.kill_additional_data = {}
        self.kill_location_data_pulled = False
        self.kill_location_data = {}
        self.kill_feeds_relevant = False
        self.kill_feeds_to_alert = []
        self.capsule_ship_ids = [ 670, 33328 ]

    def get_additional_data(self, esiLookup):
        # Method to determine what data to request from ESI, construct URL and Parameters and call
        # Returned data will populate self.kill_additional_data
        if self.kill_additional_data_pulled:
            return True
        else:
            # ESI Data
            logging.debug("get_additional_data: Fetching Additional Data from ESI for: " + str(self.kill_id))
            self.kill_additional_data['victim_ship_name'] = esiLookup.lookup(
                "type_id",
                self.kill_raw_data['victim']['ship_type_id']
            )['name']
            # If victim is not a character it must be a corporation (for structure and corporation anchored object lossmails)
            if "character_id" in self.kill_raw_data['victim'].keys():
                self.kill_additional_data['victimType'] = "Character"
                self.kill_additional_data['victimID'] = self.kill_raw_data['victim']['character_id']
                self.kill_additional_data['victim_name'] = esiLookup.lookup(
                    "character_id",
                    self.kill_additional_data['victimID']
                )['name']
                
            else:
                self.kill_additional_data['victimType'] = "Corporation"
                self.kill_additional_data['victimID'] = self.kill_raw_data['victim']['corporation_id']
                self.kill_additional_data['victim_name'] = esiLookup.lookup(
                    "corporation_id",
                    self.kill_additional_data['victimID']
                )['name']

            if "alliance_id" in self.kill_raw_data['victim'].keys():
                self.kill_additional_data['victimGroupType'] = "Alliance"
                self.kill_additional_data['victimGroupID'] = self.kill_raw_data['victim']['alliance_id']
                self.kill_additional_data['victim_group_name'] = esiLookup.lookup(
                    "alliance_id",
                    self.kill_additional_data['victimGroupID']
                )['name']
                
            else:
                self.kill_additional_data['victimGroupType'] = "Corporation"
                self.kill_additional_data['victimGroupID'] = self.kill_raw_data['victim']['corporation_id']
                self.kill_additional_data['victim_group_name'] = esiLookup.lookup(
                    "corporation_id",
                    self.kill_additional_data['victimGroupID']
                )['name']

            killer = next(
                attacker for attacker in self.kill_raw_data['attackers'] if attacker['final_blow'] == True
            )

            if "character_id" in killer.keys():
                self.kill_additional_data['killerCharacterID'] = killer['character_id']
                self.kill_additional_data['killer_character_name'] = esiLookup.lookup(
                    "character_id",
                    self.kill_additional_data['killerCharacterID']
                )['name']
                self.kill_additional_data['killer_zkillboard_URL']  = "https://zkillboard.com/character/{}/".format(
                    str(self.kill_additional_data['killerCharacterID'])
                )
            elif self.kill_zkill_data['npc'] == True:
                self.kill_additional_data['killer_character_name'] = "NPC"
                self.kill_additional_data['killer_zkillboard_URL']  = None
            else:
                self.kill_additional_data['killer_character_name'] = None
                self.kill_additional_data['killer_zkillboard_URL']  = None

            if "ship_type_id" in killer.keys():
                self.kill_additional_data['killer_ship_name'] = esiLookup.lookup(
                    "type_id",
                    killer['ship_type_id']
            )['name']
            else:
                self.kill_additional_data['killer_ship_name'] = None

            if "alliance_id" in killer.keys():
                self.kill_additional_data['killer_group_name'] = esiLookup.lookup(
                    "alliance_id",
                    killer['alliance_id']
                )['name']
            elif "corporation_id" in killer.keys():
                self.kill_additional_data['killer_group_name'] = esiLookup.lookup(
                    "corporation_id",
                    killer['corporation_id']
                )['name']
            elif "faction_id" in killer.keys():
                self.kill_additional_data['killer_group_name'] = esiLookup.lookup(
                    "faction",
                    killer['faction_id']
                    )['name']
            else:
                self.kill_additional_data['killer_group_name'] = None

            # Get Location Data
            self.get_location_data(esiLookup)

            # Other Data
            self.kill_additional_data['zKillboardURL'] = "https://zkillboard.com/kill/{}/".format(
                str(self.kill_id)
            )

            self.kill_additional_data['victim_zkillboard_URL'] = "https://zkillboard.com/{}/{}/".format(
                self.kill_additional_data['victimType'].lower(),
                str(self.kill_additional_data['victimID'])
            )

            self.kill_additional_data['victim_ship_image_URL'] = "https://images.evetech.net/types/{}/render?size=64".format(
                str(self.kill_raw_data['victim']['ship_type_id'])
            )

            if self.kill_additional_data['victimGroupType'] == "Alliance":
                self.kill_additional_data['victim_group_image_URL'] = "https://images.evetech.net/alliances/{}/logo".format(
                    str(self.kill_additional_data['victimGroupID'])
                )
            elif self.kill_additional_data['victimGroupType'] == "Corporation":
                self.kill_additional_data['victim_group_image_URL'] = "https://images.evetech.net/corporations/{}/logo".format(
                    str(self.kill_additional_data['victimGroupID'])
                )
            else:
                self.kill_additional_data['victim_group_image_URL'] = "https://images.evetech.net/alliances/1/logo"
            self.kill_additional_data['killer_count'] = len(self.kill_raw_data['attackers'])

            self.kill_additional_data_pulled = True
            return True

    def get_location_data(self, esiLookup):
        if self.kill_location_data_pulled:
            return True
        else:
            logging.debug("get_location_data: Fetching Location Data from ESI for: " +str(self.kill_id))
            system = esiLookup.lookup(
                "system_id",
                self.kill_raw_data['solar_system_id']
            )

            constellation = esiLookup.lookup(
                "constellation_id",
                system['parent']
            )

            region = self.kill_location_data['locationRegion'] = esiLookup.lookup(
                "region_id",
                constellation['parent']
            )

            self.kill_location_data['location_system_id'] = self.kill_raw_data['solar_system_id']
            self.kill_location_data['location_system'] = system['name']
            self.kill_location_data['locationConstellationID'] = system['parent']
            self.kill_location_data['locationConstellation'] = constellation['name']
            self.kill_location_data['locationRegionID'] = constellation['parent']
            self.kill_location_data['locationRegion'] = region['name']
            self.kill_location_data_pulled = True
            return True

    def _is_relevant_entity(self, feed):
        feedEntityType = feed['entity']['entity_type']
        feedEntityID = feed['entity']['entity_id']
        relationship = "None"
        if feedEntityType in self.kill_raw_data['victim'] and self.kill_raw_data['victim'][feedEntityType] != None and self.kill_raw_data['victim'][feedEntityType] == feedEntityID:
            # Entity is the victim.
            relationship =  "Loss"

        for attacker in self.kill_raw_data['attackers']:
            if feedEntityType in attacker and attacker[feedEntityType] != None and attacker[feedEntityType] == feedEntityID:
                # Entity is among the attackers.
                relationship = "Kill" # Yes even if both the attacker and victim are the feed tracked entity we class this as a kill for simplicity. ToDo: Add AWOX
        
        return relationship

    def _is_relevant_location(self, feed, esiLookup):
        feedLocationType = feed['location']['location_type']
        feedLocationID = feed['location']['location_id']
        killSystemID = self.kill_raw_data['solar_system_id']
        relationship = "None"
        match feedLocationType:
            case "system_id":
                if feedLocationID == killSystemID:
                    relationship = "Kill"
            case "constellation_id":
                self.get_location_data(esiLookup)
                if self.kill_location_data['locationConstellationID'] == feedLocationID:
                    relationship = "Kill"
            case "region_id":
                self.get_location_data(esiLookup)
                if self.kill_location_data['locationRegionID'] == feedLocationID:
                    relationship = "Kill"
            case _:
                # Log error invalid location_type
                pass

        return relationship

    def _is_relevant_label(self, feed):
        relationship = "None"
        if "labels" in self.kill_zkill_data and feed['label']['zkb_label'] in self.kill_zkill_data['labels']:
            relationship = "Kill"
        return relationship

    def add_feed_if_relevant(self, feed, esiLookup):
        # Method to check if a feed is relevant to self.
        # If feed is not relevant return false.
        # If feed is relevant, determine relationship, store in self.kill_feeds_relevant and set kill_feeds_relevant to True
        # Feed format is documented in README.txt
        logging.debug("add_feed_if_relevant: Checking relevance for Kill: " + str(self.kill_id) + " and feed: " + feed['name'])
        relevantFeed = {}
        relevantFeed['name'] = feed['name']
        relevantFeed['webhook'] = feed['webhook']
        relevantFeed['relationship'] = "None"
        if feed['include_empty_pods'] == False and self.kill_raw_data['victim']['ship_type_id'] in self.capsule_ship_ids and self.kill_zkill_data['totalValue'] == 10000:
            logging.debug("add_feed_if_relevant: Ignoring Empty Pod for Kill: " + str(self.kill_id) + " and feed: " + feed['name'])
        else:
            match feed['feed_type']:
                case "entity":
                    logging.debug("add_feed_if_relevant: Checking Entity relevance for feed: " + feed['name'])
                    relevantFeed['relationship'] = self._is_relevant_entity(feed)
                case "location":
                    logging.debug("add_feed_if_relevant: Checking Location relevance for feed: " + feed['name'])
                    relevantFeed['relationship'] = self._is_relevant_location(feed, esiLookup)
                case "label":
                    logging.debug("add_feed_if_relevant: Checking Label relevance for feed: " + feed['name'])
                    relevantFeed['relationship'] = self._is_relevant_label(feed)

        if relevantFeed['relationship'] != "None":
            # Uniqueness check
            # Prevents a webhook from recieving multiple instances of the same killmail
            if next((feed for feed in self.kill_feeds_to_alert if feed['webhook'] == relevantFeed['webhook']), None) == None:
                self.kill_feeds_to_alert.append(relevantFeed)
                self.kill_feeds_relevant = True
                logging.debug("add_feed_if_relevant: Kill: " + str(self.kill_id) + " is relevant to feed: " + feed['name'])
                return True
            else:
                logging.debug("add_feed_if_relevant: Kill: " + str(self.kill_id) + " is relevant to feed: " + feed['name'] + " but considered duplicate.")
                return False
        else:
            logging.debug("add_feed_if_relevant: Kill: " + str(self.kill_id) + " is not relevant to feed: " + feed['name'])
            return False

    def get_discord_alert_data(self):
        # If relevant feeds are found, process alerts
        if self.kill_additional_data_pulled == True:
            alertData = {
                'victim_name': self.kill_additional_data['victim_name'],
                'victim_zkillboard_URL': self.kill_additional_data['victim_zkillboard_URL'],
                'victim_ship_name': self.kill_additional_data['victim_ship_name'],
                'victim_ship_image_URL': self.kill_additional_data['victim_ship_image_URL'],
                'victim_group_name': self.kill_additional_data['victim_group_name'],
                'victim_group_image_URL': self.kill_additional_data['victim_group_image_URL'],
                'killer_character_name': self.kill_additional_data['killer_character_name'],
                'killer_zkillboard_URL': self.kill_additional_data['killer_zkillboard_URL'],
                'killer_ship_name': self.kill_additional_data['killer_ship_name'],
                'killer_group_name': self.kill_additional_data['killer_group_name'],
                'kill_location_system': self.kill_location_data['location_system'],
                'kill_location_region': self.kill_location_data['locationRegion'],
                'kill_zkillboard_URL': self.kill_additional_data['zKillboardURL'],
                'killer_count': self.kill_additional_data['killer_count'],
                'kill_zkillboard_value': self.kill_zkill_data['totalValue']
            }
            return alertData
        # Else Error or automatically attempt fetch?
    def get_relevant_feed_information(self):
        if self.kill_feeds_relevant == True:
            return self.kill_feeds_to_alert

# Class DiscordAlert - Used to construct and send a Discord Alert
class DiscordAlert(object):
    def __init__(self, feedData, alertData, discordWebhookStatsTracker):
        # ToDo: Define Format
        self.alert_information = alertData
        self.feed_information = feedData
        self.discord_webhook_stats = discordWebhookStatsTracker
        self.discord_webhook = DiscordWebhook(url=self.feed_information['webhook'])

        self.discord_title = "{} destroyed in {}({})".format(
            self.alert_information['victim_ship_name'],
            self.alert_information['kill_location_system'],
            self.alert_information['kill_location_region']
        )

        self.discord_description_victim_link = "[{}]({})".format(
            self.alert_information['victim_name'],
            self.alert_information['victim_zkillboard_URL']
        )
        
        self.discord_description_killer_link = "[{}]({})".format(
            self.alert_information['killer_character_name'],
            self.alert_information['killer_zkillboard_URL']
        )

        if self.alert_information['killer_count'] == 1:
            self.discord_description_end = "**Solo!**"
        elif self.alert_information['killer_count'] == 2:
            self.discord_description_end = "and **one** other."
        else:
            self.discord_description_end = "and **{}** others.".format(
                self.alert_information['killer_count']
            )

        self.discord_description = "**{}({})** lost their **{}** to **{}({})** flying in a **{}** {}".format(
            self.discord_description_victim_link,
            self.alert_information['victim_group_name'],
            self.alert_information['victim_ship_name'],
            self.discord_description_killer_link,
            self.alert_information['killer_group_name'],
            self.alert_information['killer_ship_name'],
            self.discord_description_end
        )

        if self.feed_information['relationship'] == "Loss":
            self.discord_embed_color = 15158332
            self.discord_embed_author_name = "Loss"
        else:
            self.discord_embed_color = 3066993
            self.discord_embed_author_name = "Kill"

        self.discord_embed = DiscordEmbed(
            title = self.discord_title,
            description = self.discord_description,
            color = self.discord_embed_color,
            url = self.alert_information['kill_zkillboard_URL']
        )

        self.discord_embed.set_author(
            name = self.discord_embed_author_name,
            url = self.alert_information['kill_zkillboard_URL'],
            icon_url = self.alert_information['victim_group_image_URL']
        )
        self.discord_embed.set_thumbnail(url=self.alert_information['victim_ship_image_URL'])
        self.human_kill_value = humanize.intword(self.alert_information['kill_zkillboard_value'])
        self.discord_embed.set_footer(text = self.human_kill_value)
        self.discord_embed.set_timestamp()
        self.discord_webhook.add_embed(self.discord_embed)

    def alert(self):
        response = self.discord_webhook.execute(remove_embeds=True, remove_files=True)
        self.discord_webhook_stats.increment_execution()
        logging.info("alert: Discord Response: " + str(response))

# Discord alerting function
def discordAlert(alertData, relevantFeed, discordWebhookStatsTracker):
    discordAlert = DiscordAlert(relevantFeed, alertData, discordWebhookStatsTracker)
    discordAlert.alert()

# Main killmail processing function
def onMessage(responseJson):
    killmail = Killmail(responseJson)

    logging.debug("onMessage: Started for Kill: " + str(killmail.kill_id))
    logging.info("onMessage: Processing Killmail: " + str(killmail.kill_id))

    for feed in configuration['feeds']:
        killmail.add_feed_if_relevant(feed, esiLookup)
    
    if killmail.kill_feeds_relevant:
        logging.info("onMessage: Obtaining Additional Data for Relevant Kill: " + str(killmail.kill_id))
        killmail.get_additional_data(esiLookup)
        if killmail.kill_additional_data_pulled:
            logging.info("onMessage: Triggering Alerting for Relevant Kill: " + str(killmail.kill_id))
            alertData = killmail.get_discord_alert_data()
            relevantFeedsToAlert = killmail.get_relevant_feed_information()
            for relevantFeed in relevantFeedsToAlert:
                discordAlert(alertData, relevantFeed, discordWebhookStatsTracker)
        logging.info("onMessage: Ending processing of Kill: " + str(killmail.kill_id))
    else:
        logging.info("onMessage: End for Non-Relevant Kill: " + str(killmail.kill_id))

def loadConfig(configurationFilePath):
    try:
        f = open(configurationFilePath)
        configuration = json.load(f)
        f.close()
        # ToDo: Ensure defaults are sanely set before proceeding
        logging.info("loadConfig: Configuration File Loaded")
        return configuration
    except:
        logging.critical("loadConfig: Fatal Error Reading Configuration File!")
        os._exit(1)

def configureLogging(logLevel):
    match logLevel:
        case "INFO":
            logging.basicConfig(
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)
        case "DEBUG":
            logging.basicConfig(
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.DEBUG,
		)
        case "WARNING":
            logging.basicConfig(
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.WARNING,
		)
        case "ERROR":
            logging.basicConfig(
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.ERROR,
		)
        case "CRITICAL":
            logging.basicConfig(
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.CRITICAL,
		)
        case _:
            logging.basicConfig(
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)

if __name__ == '__main__':
    # Configure Logging
    configureLogging(loglevel)
    logging.info("main: Logging Initialized")

    # Load Configuration
    configuration = loadConfig(configurationFilePath)

    # Set some vars for later use
    version = configuration['application']['version']
    logging.info("main: zKillboardMonitor Version: " + str(version))

    applicationIdentity = configuration['application']['name'] + "/" + configuration['application']['version'] + "by " + configuration['application']['author']

    # Create required objects
    poller = Poller(configuration['zkillboard']['redisq_url'])
    discordWebhookStatsTracker = DiscordWebhookStatsTracker()
    esiCacheDatabase = ESICacheDatabase(configuration['esicachedb']['cache_db_path'])
    esiLookup = ESILookup(configuration['eveesi']['esi_url'], configuration['eveesi']['esi_datasource'], applicationIdentity, esiCacheDatabase)

    # Try to run the poller
    try:
        for response in poller.run():
            onMessage(response)
    except (KeyboardInterrupt, Exception) as e:
        if not isinstance(e, KeyboardInterrupt):
            logging.error(str(e))
        poller.exit_gracefully()

    killmailsProcessed = poller.get_statistics()['killmails_recieved']
    discordAlertsSent = discordWebhookStatsTracker.get_statistics()['execution_count']
    esiLookups = esiLookup.get_statistics()['query_count']
    cacheHits = esiLookup.get_statistics()['cache_hit']
    cacheMisses = esiLookup.get_statistics()['cache_miss']
    statistics = "Killmails: {}, Alerts: {}, ESI Lookups: {}, Cache Hits: {}, Cache Misses: {}".format(killmailsProcessed,discordAlertsSent,esiLookups,cacheHits,cacheMisses)
    logging.info("main: Application Exiting. Statistics: " + statistics)
