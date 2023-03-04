# hikaxpro_hacs
HACS repository of Hikvision Ax Pro integration for home assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

## Support

### Supported Sensors / Detectors
- Wireless external magnetic sensors
- Wireless slim magnetic sensor
- Wireless magnet Shock Detector
- Wireless temperature humidity sensors
- Wireless PIR sensors
- Wireless glass break sensors
- Wireless PIR AM curtain sensor
- Wireless PIR CAM sensor
- Wired magnetic contact sensor
- Wireless Smoke Detector

### Attributes
- Alarm
- Armed
- Battery
- Bypass
- Humidity
- Is via repeater
- Magnet presence
- Signal
- Stay away
- Tamper
- Temperature

### Examples
Example screens of integration. 

**Magnetic Sensor**
![Magnetic Sensor](https://user-images.githubusercontent.com/9423543/222737996-4eefb9a5-a09a-4713-a87e-71664580aaf2.png)

**PIR Sensor**
![PIR Sensor](https://user-images.githubusercontent.com/9423543/222738007-1961348c-9e94-46de-9a29-40aedc726e38.png)


## Installation

### HACS

1. Install HACS if you don't have it already
2. Open HACS in Home Assistant
3. Go to "Integrations" section
4. Click ... button on top right and in menu select "Custom repositories"
5. Add repository https://github.com/petrleocompel/hikaxpro_hacs and select category "Integration"
6. Search for "hikaxpro_hacs" and install it
7. Restart Home Assistant

### Manual

Download the [zip](https://github.com/petrleocompel/hikaxpro_hacs/archive/refs/heads/master.zip) and extract it. Copy the folder `hikaxpro_hacs` to your `custom_components` folder.

