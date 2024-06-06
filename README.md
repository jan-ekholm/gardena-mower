# Gardena Mower

This is a simple server for fetching status data for a Gardena robotic mower from Gardena's cloud
and publishing the data to an MQTT server. It is heavily based on Gardena's sample Websocket app
with some additions and cleanups.

## Prerequisites

- set up account on Gardena's cloud.
- register application.

## Installing


## Configuration

```
# your client id
CLIENT_ID=12345678-1234-abcd-4321-12345678

# secret for the above client id
CLIENT_SECRET=12345678-1234-abcd-4321-cdef-1234567890ab

# secret from the created API
API_KEY=12345678-1234-abcd-4321-cdef-1234567890ab

# set to true to see verbose logging of network data
TRACE_WEBSOCKET=false

# IP address and port to the MQTT server where data is published to
MQTT_BROKER=192.168.1.40
MQTT_PORT=1883

# optional username and password for authenticating with the MQTT server
#MQTT_USERNAME=username
#MQTT_PASSWORD=password

```