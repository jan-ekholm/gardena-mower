# Gardena Mower

This is a simple server for fetching status data for a Gardena robotic mower from Gardena's cloud
and publishing the data to an MQTT server. It is heavily based on Gardena's sample Websocket app
with some additions and cleanups.

## Prerequisites

Set up an account on Husqvarna's cloud: https://developer.husqvarnagroup.cloud. After that set
up a new *GARDENA smart system API* which is used for the Gardena mowers. You do not need the 
*Automower Connect API* which seems to be for other mowers.

Take note of the *Application key* and *Application secret* values as those are used below in
the config file.

## Installing

Set up a Python virtual environment for the server:

```shell
% python3 -m venv venv
% . ./venv/bin/activate
```

Install all required packages:

```shell
% pip install -r requirements.txt
```

Create a file `.env` in the directory where you're running the script. It contains your
secrets and various parameters. As an altrnative you can set the same variables as normal
environment variables.

```
# key for the new application
API_KEY=12345678-1234-abcd-4321-cdef-1234567890ab

# secret for the above key
API_SECRET=12345678-1234-abcd-4321-cdef-1234567890ab

# set to true to see verbose logging of network data
TRACE_WEBSOCKET=false

# IP address and port to the MQTT server where data is published to
MQTT_BROKER=192.168.1.40
MQTT_PORT=1883

# optional username and password for authenticating with the MQTT server
#MQTT_USERNAME=username
#MQTT_PASSWORD=password
```

## Usage

Start the server:

```shell
% python3 ./gardena-mower.py
```

The data fetched from Gardena's cloud is published to an NQTT server. The server also listens to publishes to
a MQTT topic that contains commands that gets sent to Gardena's cloud and then down to your mower. You can start 
and park the mower.

The topics that are published to are:

```
gardena/mower/SERIAL/battery 
gardena/mower/SERIAL/battery_state
gardena/mower/SERIAL/activity
gardena/mower/SERIAL/last_error
gardena/mower/SERIAL/operating_hours 
```

where `SERIAL` is the serial number of the mower. The server will listen to incoming commands on the topic
`gardena/mower/SERIAL/command`. The recognized commands are:

* `start_1h` to start the mower for 1 hour. 
* `start_3h` to start the mower for 3 hours. 
* `start_6h` to start the mower for 6 hours. 
* `park` to park the mower.

## Logs

The server logs to a file `gardena-mower.log` in the current directory as well as to the console. The log file
is rotated after it reaches 1MB in size and 10 files files are kept. This can be tweaked in the `init_logger()` 
function.