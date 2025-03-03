# hikaxpro_hacs
HACS repository of Hikvision Ax Pro integration for home assistant

**Type**: Local integration (not using any cloud connection - only connecting to device)
**IOT Class**: `local_polling` aka Pulling data from device in predefined interval (default 30 sec)

For reporting issue with log please use issues.
For feature request there is a feature request in issues.
For other questions checkout first [#FAQ](#faq) section. Otherwise, use [discussions](https://github.com/petrleocompel/hikaxpro_hacs/discussions).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

## Supported devices
- AX Pro series
- AX Hub - introduced in version 1.2.0 

## Support
- Sub zones control (Opt-in - after configuration reload integration)

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
- Status
- Tamper
- Temperature

### Examples
Example screens of integration. 

**Magnetic Sensor**
![Magnetic Sensor](https://user-images.githubusercontent.com/9423543/222737996-4eefb9a5-a09a-4713-a87e-71664580aaf2.png)

**PIR Sensor**
![PIR Sensor](https://user-images.githubusercontent.com/9423543/222738007-1961348c-9e94-46de-9a29-40aedc726e38.png)

**Main System Device**
![Main System Device](https://user-images.githubusercontent.com/9423543/224548626-823a6cfa-5c15-4a6a-97d2-32831797253c.png)


## Installation

### Pre-check
> ⚠️ Please make sure your user you will be using will have role "Admin" and it is not same as "Installer" or remove the "Installer" completely. (Referring to issue #108)

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

## FAQ

### Can I see sensors with this?
Yes, supported sensors are [listed above](#supported-sensors--detectors).
> ⚠️ But there is a delay of pulling interval to see the data / the status. 

### Can I make data appear faster? / Can I speed up updating sensors?
Yes and No. **Default is 30 seconds**.

Yes you can lower the `pull interval` via configuration of integration.
> ⚠️ But you can hit a limit with number of devices and cameras. Your system can become unstable.
> But I admit some smaller system can run with 2 seconds `pull interval` stable. It also depends on your device. 

Examples:
- [Real time update and sensor excluding #157](https://github.com/petrleocompel/hikaxpro_hacs/issues/157)
- [Hikvision IP Cam disconnected by AX Pro #124](https://github.com/petrleocompel/hikaxpro_hacs/issues/124)

### Is there another way to do it? Receive events only?
**No**. HikVision does not have that API. Maybe there could be, but I did not find it.
Documentation of HikVision devices is now behind "partner portal".
You have to be in partner program and login to get current documentation.  
I am using old documentation and even there a some API is not documented. Or statuses and attributes.

I still have some stuff to implement to improve the situation ([found event stream for arm/disarm/alarm #143](https://github.com/petrleocompel/hikaxpro_hacs/issues/143#issuecomment-2539032085)) but this is the current state.

### Why do not get in touch with HikVision to improve?
**Maybe they would have a problem with this integration**. I really do not want to get **DMCA** request.
Examples:
- https://www.home-assistant.io/blog/2023/10/13/removal-of-mazda-connected-services-integration/
- https://github.com/Andre0512/hOn?tab=readme-ov-file#takedown-story

### Cannot arm my system with HA.

Check your batteries for devices. Check that all zones are closed / not triggered.

If you use Hik-Connect app - you can press the **diagnosis** button on the "system overview page".
It will tell you why you cannot arm the system. 

This integration is not bypassing any "zones" so you might have to set it up via "Hik-Connect" / Web interface.

### Everything seems fine I can arm in "Hik-Connect" app but not in HA.

Is installer account in the system ? What account you are using with the integration?
Sadly to make it work we need to be an Admin user.

Some systems work with login "admin" some with the user who set it up via Hik-Connect account.
So even your "Hik-Connect" used email address might be the correct one.

But still in "Web Interface" of your device after you log in there should not be and Installer account. 
If there is and if it has a same email as your user it is the problem and needs to be removed.
