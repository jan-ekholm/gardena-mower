import json
from enum import StrEnum
import logging.handlers
from typing import Union, Optional

import websocket
import datetime
import time
import sys
import requests
from decouple import config
import rich
import paho.mqtt.client as paho

# account specific values
API_KEY = config("API_KEY")
API_SECRET = config("API_SECRET")

# other constants
AUTHENTICATION_HOST = 'https://api.authentication.husqvarnagroup.dev'
SMART_HOST = 'https://api.smart.gardena.dev'

logger: logging.Logger = logging.getLogger("gardena-mower")

auth_token: Optional[str] = None
service_id: Optional[str] = None


class MoverActivity(StrEnum):
    unknown = "UNKNOWN"
    none = "NONE"
    charging = "OK_CHARGING"
    leaving = "OK_LEAVING"
    cutting = "OK_CUTTING"
    searching = "OK_SEARCHING"
    parked_timer = "PARKED_TIMER"
    parked_auto_timer = "PARKED_AUTOTIMER"
    parked_park_selected = "PARKED_PARK_SELECTED"
    cutting_extra = "OK_CUTTING_TIMER_OVERRIDDEN"
    paused = "PAUSED"


class MoverError(StrEnum):
    unknown = "UNKNOWN"
    no_error = "NO_ERROR"
    no_message = "NO_MESSAGE"
    hatch_open = "OFF_HATCH_OPEN"
    no_loop_signal = "NO_LOOP_SIGNAL"
    off_hatch_closed = "OFF_HATCH_CLOSED"
    lifted = "LIFTED"


class BatteryState(StrEnum):
    unknown = "UNKNOWN"
    charging = "CHARGING"
    ok = "OK"


class Mover:
    def __init__(self):
        self.name = "UNKNOWN"
        self.serial = -1
        self.model_type = "UNKNOWN"
        self.state = "UNKNOWN"
        self.activity: MoverActivity = MoverActivity.unknown
        self.battery_level = -1
        self.battery_state: BatteryState = BatteryState.unknown
        self.rf_link_level = -1
        self.rf_link_state = "UNKNOWN"
        self.operating_hours = -1
        self.last_error_code: MoverError = MoverError.unknown

    def __str__(self):
        if self.last_error_code is not None:
            return f"[name: {self.name}: model: {self.model_type}, serial: {self.serial}, activity: {self.activity.name}, battery state: {self.battery_state.name}, battery: {self.battery_level}%, rf state: {self.rf_link_state}, rf level: {self.rf_link_level}, error: {self.last_error_code.name}]"

        return f"[name: {self.name}: model: {self.model_type}, serial: {self.serial}, activity: {self.activity.name}, battery state: {self.battery_state.name}, battery: {self.battery_level}%, rf state: {self.rf_link_state}, rf level: {self.rf_link_level}]"


class MqttClient:
    FIRST_RECONNECT_DELAY = 1
    RECONNECT_RATE = 2
    MAX_RECONNECT_COUNT = 12
    MAX_RECONNECT_DELAY = 60

    def __init__(self, broker_ip: str, broker_port: int):
        self.subscribe_topic = None

        logger.info(f"connecting to MQTT broker at {broker_ip}:{broker_port}")

        self.client = paho.Client(callback_api_version=paho.CallbackAPIVersion.VERSION2, client_id="gardena")

        # configure authentication
        username = config("MQTT_USERNAME", default=None)
        password = config("MQTT_PASSWORD", default=None)
        if username is not None and password is not None:
            self.client.username_pw_set(username=username, password=password)

        # self.client.tls_set()

        # callbacks
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_connect_fail = self.on_connect_fail
        self.client.on_subscribe = self.on_subscribe

        self.client.connect(broker_ip, broker_port)

        self.client.loop_start()

    def publish(self, topic: str, message: Union[str, bytes, bytearray, int, float]):
        """Publish the given message to the given topic."""
        self.client.publish(topic=topic, payload=message, retain=True)

    def subscribe(self, serial):
        if self.subscribe_topic is not None:
            return

        self.subscribe_topic = f"gardena/mower/{serial}/command"
        self.client.subscribe(self.subscribe_topic)

    def on_connect(self, client, userdata, connect_flags, reason, properties):
        logger.info("connected ok to broker")

    def on_subscribe(self, client, userdata, mid, reason_codes, properties):
        logger.info(f"subscribe ok to topic {self.subscribe_topic}")

    def on_message(self, client, userdata, message):
        topic = message.topic
        command = message.payload.decode("utf-8")
        logger.debug(f"topic: {message.topic}, data: {command}")

        topic_parts = topic.split("/")
        if len(topic_parts) != 4:
            logger.error(f"invalid topic: {topic}")
            return

        try:
            serial = int(topic_parts[2])
        except ValueError:
            logger.error(f"invalid serial in topic: {topic}")
            return

        logger.info(f"received command '{command}' for mower {serial}")

        if command == "park":
            self.park_mover()
        elif command == "start_1h":
            self.start_mower(1)
        elif command == "start_3h":
            self.start_mower(3)
        elif command == "start_6h":
            self.start_mower(6)

    def on_disconnect(self, client, userdata, disconnect_flags, reason, properties):
        logging.info(f"disconnected with result code: {reason}")
        reconnect_count, reconnect_delay = 0, MqttClient.FIRST_RECONNECT_DELAY
        while reconnect_count < MqttClient.MAX_RECONNECT_COUNT:
            logging.info(f"reconnecting in {reconnect_delay} seconds")
            time.sleep(reconnect_delay)

            try:
                client.reconnect()
                logging.info("reconnected successfully!")
                return
            except Exception as err:
                logging.error(f"{err}. reconnect failed. Retrying")

            reconnect_delay *= MqttClient.RECONNECT_RATE
            reconnect_delay = min(reconnect_delay, MqttClient.MAX_RECONNECT_DELAY)
            reconnect_count += 1

        logging.info(f"reconnect failed after {reconnect_count} attempts. Exiting...")

    def on_connect_fail(self, client, userdata):
        logger.error("failed to connect to broker")

    def park_mover(self):
        headers = {
            "Content-Type": "application/vnd.api+json",
            "x-api-key": API_KEY,
            "Authorization": "Bearer " + auth_token
        }

        data = {
            "data": {
                "type": "MOWER_CONTROL",
                "id": "random_id",
                "attributes": {
                    "command": "PARK_UNTIL_NEXT_TASK",
                    "seconds": 0,
                }
            }
        }

        r = requests.put(f'{SMART_HOST}/v1/command/{service_id}', headers=headers, json=data)
        if r.status_code != 202:
            logger.error(f"failed to park mower, status code: {r.status_code}, {r.text}")
        else:
            logger.info("mower sent park command")

    def start_mower(self, hours: int):
        headers = {
            "Content-Type": "application/vnd.api+json",
            "x-api-key": API_KEY,
            "Authorization": "Bearer " + auth_token
        }

        data = {
            "data": {
                "type": "MOWER_CONTROL",
                "id": "random_id",
                "attributes": {
                    "command": "START_SECONDS_TO_OVERRIDE",
                    "seconds": hours * 3600,
                }
            }
        }

        r = requests.put(f'{SMART_HOST}/v1/command/{service_id}', headers=headers, json=data)
        if r.status_code != 202:
            logger.error(f"failed to park mower, status code: {r.status_code}, {r.text}")
        else:
            logger.info(f"mower sent start command, moving {hours} h")


class WebSocketClient:

    def __init__(self, mover: Mover, broker: MqttClient):
        self.mover = mover
        self.broker = broker
        self.live = False

    def on_message(self, ws, message):
        message = json.loads(message)
        # rich.print(message)

        if "type" in message and message["type"] == "MOWER" and "attributes" in message:
            attributes = message["attributes"]
            self.mover.state = self.get_attribute_value(attributes, "state", "UNKNOWN")
            self.mover.operating_hours = int(self.get_attribute_value(attributes, "operatingHours", "-1"))
            activity_str = self.get_attribute_value(attributes, "activity", None)
            last_error_code_str = self.get_attribute_value(attributes, "lastErrorCode", None)

            if activity_str is not None:
                try:
                    self.mover.activity = MoverActivity(activity_str)
                except ValueError:
                    print(f"**** unknown activity: {activity_str}")
                    self.mover.activity = MoverActivity.unknown

            if last_error_code_str is not None:
                try:
                    self.mover.last_error_code = MoverError(last_error_code_str)
                except ValueError:
                    print(f"**** unknown error code: {last_error_code_str}")
                    self.mover.last_error_code = MoverError.unknown

            logger.info(f"{self.mover}")

            # publish all data
            self.publish_mower_data()

        elif "type" in message and message["type"] == "COMMON" and "attributes" in message:
            attributes = message["attributes"]
            self.mover.name = self.get_attribute_value(attributes, "name", "UNKNOWN")
            self.mover.serial = int(self.get_attribute_value(attributes, "serial", "-1"))
            self.mover.model_type = self.get_attribute_value(attributes, "modelType", "UNKNOWN")
            battery_state_str = self.get_attribute_value(attributes, "batteryState", "UNKNOWN")
            self.mover.battery_level = int(self.get_attribute_value(attributes, "batteryLevel", "-1"))
            self.mover.rf_link_level = int(self.get_attribute_value(attributes, "rfLinkLevel", "-1"))
            self.mover.rf_link_state = self.get_attribute_value(attributes, "rfLinkState", "UNKNOWN")

            try:
                self.mover.battery_state = BatteryState(battery_state_str)
            except ValueError:
                logger.error(f"unknown battery state: {battery_state_str}")
                self.mover.battery_state = BatteryState.unknown

            # publish all data
            self.publish_mower_data()

            logger.info(f"{self.mover}")

        elif message["type"] == "DEVICE":
            # we need the service id for the mower
            relationships = message["relationships"]
            services = relationships["services"]
            for service in services["data"]:
                if service["type"] == "MOWER":
                    global service_id
                    service_id = service["id"]
                    logger.debug(f"mower service id: {service_id}")

        elif message["type"] == "LOCATION":
            # we don't care about these
            pass

        else:
            logger.warn(f"unhandled message: {message["type"]}")
            rich.print(message)

    def on_error(self, ws, error):
        logger.error(f"error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.live = False

        logger.debug("websocket closed")
        if close_status_code:
            logger.debug(f"status code: {close_status_code}")
        if close_msg:
            logger.debug(f"status message: {close_msg}")

    def on_open(self, ws):
        logger.info("connected ok")
        self.live = True

    def get_attribute_value(self, attributes, name, default):
        if name not in attributes:
            return default

        attribute = attributes[name]

        if "value" not in attribute:
            return default

        return attribute["value"]

    def publish_mower_data(self):
        if self.mover.serial == -1:
            return

        # let the MQTT client subscribe to topics
        self.broker.subscribe(self.mover.serial)

        self.broker.publish(f"gardena/mower/{self.mover.serial}/battery", self.mover.battery_level)
        self.broker.publish(f"gardena/mower/{self.mover.serial}/battery_state", self.mover.battery_state.name)
        self.broker.publish(f"gardena/mower/{self.mover.serial}/activity", self.mover.activity.name)
        self.broker.publish(f"gardena/mower/{self.mover.serial}/last_error", self.mover.last_error_code.name)
        self.broker.publish(f"gardena/mower/{self.mover.serial}/operating_hours", self.mover.operating_hours)


def init_logger():
    """Sets up a rotating file logger and a console logger."""
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s')

    # console logger
    console_log_handler = logging.StreamHandler()
    console_log_handler.setLevel(logging.DEBUG)
    console_log_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(filename="gardena-mower.log", maxBytes=1000 * 1000 * 10, backupCount=10)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_log_handler)
    logger.addHandler(file_handler)


def init_websocket() -> Optional[websocket.WebSocketApp]:
    """Set up the websocket connection to Gardena's server."""
    logger.debug("setting up websocket")

    payload = {'grant_type': 'client_credentials', 'client_id': API_KEY, 'client_secret': API_SECRET}

    r = requests.post(f'{AUTHENTICATION_HOST}/v1/oauth2/token', data=payload)
    if r.status_code != 200:
        logger.error(f"failed to authenticate, status code: {r.status_code}, {r.text}")
        return None

    global auth_token

    response = r.json()
    auth_token = response["access_token"]
    expires_in = int(response["expires_in"])

    logger.debug(f"logged in, token: {auth_token}")
    logger.debug(f"expires in: {expires_in} seconds")

    # rich.print(r.json())

    headers = {
        "Content-Type": "application/vnd.api+json",
        "x-api-key": API_KEY,
        "Authorization": "Bearer " + auth_token
    }

    logger.debug("getting locations")
    r = requests.get(f'{SMART_HOST}/v1/locations', headers=headers)
    if r.status_code != 200:
        logger.error(f"failed to get locations, status code: {r.status_code}, {r.text}")
        return None

    response = r.json()
    if len(response["data"]) == 0:
        logger.error("missing location, system not set up?")
        return None

    location_id = response["data"][0]["id"]
    logger.debug(f"location id: {location_id}")

    payload = {
        "data": {
            "type": "WEBSOCKET",
            "attributes": {
                "locationId": location_id
            },
            "id": "does-not-matter"
        }
    }

    logger.debug("getting websocket ID")
    r = requests.post(f'{SMART_HOST}/v1/websocket', json=payload, headers=headers)

    if r.status_code != 201:
        logger.error(f"failed to open websocket, status code: {r.status_code}, {r.text}")
        return None

    logger.debug("websocket ID obtained, connecting")
    response = r.json()
    websocket_url = response["data"]["attributes"]["url"]
    websocket.enableTrace(config("TRACE_WEBSOCKET", cast=bool))

    mover = Mover()
    client = WebSocketClient(mover=mover, broker=mqtt_client)
    ws = websocket.WebSocketApp(
        websocket_url,
        on_message=client.on_message,
        on_error=client.on_error,
        on_open=client.on_open,
        on_close=client.on_close)

    return ws


def run_websocket():
    while True:
        if (ws := init_websocket()) is None:
            logger.error("failed to init websocket")

        logger.debug("starting websocket main loop")
        ws.run_forever(ping_interval=150, ping_timeout=1)

        logger.debug("websocket main loop done, pausing and reconnecting")

        time.sleep(10)

    # Thread(target=run).start()


if __name__ == "__main__":
    init_logger()

    mqtt_broker = config("MQTT_BROKER")
    mqtt_port = config("MQTT_PORT", cast=int)

    # connect to the MQTT broker
    if (mqtt_client := MqttClient(mqtt_broker, mqtt_port)) is None:
        logger.error("failed to create MQTT client")
        sys.exit(1)

    run_websocket()

    while True:
        time.sleep(60)
        now = datetime.datetime.now()
        logger.debug("alive")
