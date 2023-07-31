# Changelog

## v2.0.1
- **fix**: undocumented accessModuleType `transmitter` #55

## v2.0.0

> From version 2.0.0 configuration option "AXHub" is no more needed, currently being kept for later internal debug purposes.
> Should not be used until told for debug.

- **refactor**: use native attrs
- **feat**: loading of devices from configuration
- **fix**: add missing "Wireless Dual-Tech Detector" 
- **fix**: area initialization + updates 
- **fix**: missing detectorType
- **fix**: Separate Area Arm/Disarm 
- **fix**: a lot models fixes
- **fix**: AXHub internal lib
- **fix**: runtime errors unknown types fixes 
- **fix**: runtime errors, missing enum values

## v1.3.1
- **fix**: (AX Hub) Arm / disarm + code support #31

## v1.3.0
- **feat**: add Status sensor entity #35

## v1.2.0
- **feat**: AX Hub - final support, debug, arm/disarm #31

## v1.1.2
- **fix**: AX Hub models `Zones` #31

## v1.1.1
- **fix**: AX Hub models `Zones` and `SubSys` #31

## v1.1.0
- **feat**: AX Hub support #31

## v1.0.6
- **fix**: AX Hub session cookie #31
- **fix**: AX Hub connect logging #31

## v1.0.5
- **fix**: AX Hub connect logging #31
- **fix**: AX Hub connect URL encoding #31

## v1.0.4
- **fix**: Session Capabilities AX Hub call with auth #31
- **chore**: convert CRLF to LF
- **chore**: gitignore
- **chore**: test runner and test requirements

## v1.0.3
- **fix**: areas arming/disarming and updates #32

## v1.0.2
- **fix**: safe get session data for AXHub #31

## v1.0.1
- **fix**: more logging for AXHub #31

## v1.0.0
- **BREAKING CHANGE**: icons and correct state of magnets - invert state of magnets to match presence #27
- **feat**: add internal API lib - `AXHub` #31
- **fix**: missing undocumented `AccessModuleType` `inputMainZone` #14
- **chore**: Update `README.md`

## v0.10.0
- **feat**: implementation of multiple areas
  - subsystem arm/disarm
  - opt-in using subsystems
  - README.md update

## v0.9.2
- **fix**: remove logging debug

## v0.9.1
- **fix**: missing state of `Arming`

## v0.9.0
- **feat**: add `Wireless Smoke Detector`

## v0.8.2
- **fix**: Zone model init mixup
- **fix**: python deprecations

## v0.8.1
- **fix**: not requiring optional params of Zone

## v0.8.0
- **feat**: add sensors `entity description`

## v0.7.0
- **feat**: add more sensor types
- **feat**: add `Wireless Magnet Shock Detector`

## v0.6.4
- **fix**: add missing `AccessModuleType`
- **fix**: crash on parsing enums

## v0.6.3
- **fix**: add missing services.yaml
- **fix**: manifest.json order, dependencies, issue tracker

## v0.6.2
- **fix**: sensor.py typo

## v0.6.1
- **fix**: invalid info provided by sensors

## v0.6.0
- **feat**: add detail info `Armed`, `Alarm`, `Stay away`, `Is via repeater`

## v0.5.2
- **fix**: missing slim magnetic contact sensor init

## v0.5.1
- **fix**: manifest version
- **fix**: invalid status attribute

## v0.5.0
- **feat**: add lang `sl` @DejanBukovec
- **feat**: add lang `cs`
- **feat**: add detail info `Battery`, `Signal`, `Tamper`, `Bypass`
- **feat**: add `Slim Magnetic Contact`, `Wireless PIR CAM Detector` support
- **fix**: init of platform

## v0.4.1
- **fix**: missing await in init
- **fix**: type conversion safety
- **fix**: add missing zone type `Delay`

## v0.4.0
- **feat**: added sensors loading
- **feat**: added support for temperatures of sensors
- **feat**: added support for magnetic sensors
- **feat**: added support for humidity sensors
- **fix**: multiple instances support
- **fix**: load of name and model of system
