"""Parse tests for model fields aligned with test_payloads dumps."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "hikvision_axpro"


def _load_model():
    """Load model.py without requiring Home Assistant."""
    name = "hikvision_axpro.model"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, COMPONENT / "model.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


model = _load_model()


def test_detector_wiring_mode_noeol():
    assert model.DetectorWiringMode("noEOL") is model.DetectorWiringMode.NO_EOL


def test_access_module_type_four_wired_output():
    assert (
        model.AccessModuleType("fourWiredOutput")
        is model.AccessModuleType.FOUR_WIRED_OUTPUT
    )


def test_access_module_type_rs485_r3_wireless_recv():
    assert (
        model.AccessModuleType("RS485R3WirelessRecv")
        is model.AccessModuleType.RS485_R3_WIRELESS_RECV
    )


def test_relay_attrib_wireless():
    assert model.RelayAttrib("wireless") is model.RelayAttrib.WIRELESS


def test_zone_status_extra_fields_from_payload():
    """Snippet shaped like Zones: dumps in 2025-03-12 / 2026-04-16 logs."""
    payload = {
        "id": 0,
        "name": "vstupní dveře ",
        "status": "online",
        "sensorStatus": "normal",
        "magnetOpenStatus": False,
        "tamperEvident": False,
        "shielded": False,
        "bypassed": False,
        "armed": False,
        "isArming": False,
        "alarm": False,
        "charge": "normal",
        "chargeValue": 100,
        "signal": 121,
        "realSignal": 135,
        "signalType": "R3",
        "temperature": 23,
        "subSystemNo": 1,
        "linkageSubSystem": [1],
        "detectorType": "magneticContact",
        "model": "0x00006",
        "stayAway": False,
        "zoneType": "Delay",
        "InputList": [
            {"id": 1, "enabled": False, "mode": "normalClose"},
            {
                "id": 2,
                "enabled": True,
                "mode": "normalOpen",
                "inputZoneID": 3,
                "pulseNum": 2,
                "timeout": 5,
            },
        ],
        "isViaRepeater": False,
        "zoneAttrib": "wireless",
        "version": "V1.0.0",
        "deviceNo": 1,
        "abnormalOrNot": False,
        "isMasking": False,
        "antiMaskingEnabled": True,
        "mountingType": "wall",
        "waterDetectorAlarm": "no",
        "healthStatus": "normal",
        "workMode": "detector",
        "pollingOptionEnable": False,
        "associateRelayCfg": [],
    }
    zone = model.Zone.from_dict(payload)
    assert zone.sensor_status == "normal"
    assert zone.real_signal == 135
    assert zone.signal_type == "R3"
    assert zone.is_masking is False
    assert zone.anti_masking_enabled is True
    assert zone.mounting_type == "wall"
    assert zone.water_detector_alarm == "no"
    assert zone.health_status == "normal"
    assert zone.work_mode == "detector"
    assert zone.polling_option_enable is False
    assert zone.associate_relay_cfg == []
    assert zone.input_list is not None
    assert zone.input_list[1].input_zone_id == 3
    assert zone.input_list[1].pulse_num == 2
    assert zone.input_list[1].timeout == 5


def test_zone_wired_status_fields():
    payload = {
        "id": 0,
        "name": "Churrasqueira",
        "status": "online",
        "sensorStatus": "normal",
        "zoneAttrib": "wired",
        "moduleType": "localWired",
        "accessModuleType": "localZone",
        "moduleChannel": 1,
        "relatedAccessModuleID": 2,
        "tamperEvident": False,
        "shielded": False,
        "bypassed": False,
        "armed": True,
        "isArming": False,
        "alarm": False,
        "isMasking": False,
        "subSystemNo": 1,
        "linkageSubSystem": [1],
        "detectorType": "passiveInfraredDetector",
        "stayAway": False,
        "zoneType": "Instant",
        "deviceNo": 1,
        "abnormalOrNot": False,
    }
    zone = model.Zone.from_dict(payload)
    assert zone.module_type == "localWired"
    assert zone.related_access_module_id == 2
    assert zone.access_module_type is model.AccessModuleType.LOCAL_ZONE


def test_zone_config_wired_noeol_from_detector_dump():
    """Config-like Detector info from 2026-04-16 log."""
    payload = {
        "supportLinkageKeypadList": [],
        "id": 0,
        "zoneName": "Churrasqueira",
        "detectorType": "passiveInfraredDetector",
        "detectorAccessMode": "NC",
        "detectorWiringMode": "noEOL",
        "zoneType": "Instant",
        "subSystemNo": 1,
        "doubleZoneCfgEnable": False,
        "linkageSubSystem": [1],
        "armMode": "and",
        "pulseSensitivity": 30,
        "zoneAttrib": "wired",
        "address": 15,
        "moduleType": "localWired",
        "accessModuleType": "localZone",
        "moduleChannel": 1,
        "finalDoorExitEnabled": False,
        "timeRestartEnabled": False,
        "relatedKeypadNo": 0,
        "supportLinkageSubSystemList": [1],
        "enterDelay": 30,
        "exitDelay": 30,
        "stayArmDelayTime": 0,
        "sirenDelayTime": 0,
        "stayAwayEnabled": False,
        "chimeEnabled": False,
        "silentEnabled": False,
        "timeout": 0,
        "timeoutType": "recover",
        "deviceNo": 1,
        "model": "0x00001",
        "reportSendDelayTimeEnabled": False,
        "reportSendDelayTime": 0,
        "AlarmSoundInterlink": {
            "supportLinkageZones": [],
            "linkageZones": [],
        },
        "armNoBypassEnabled": False,
    }
    cfg = model.ZoneConfig.from_dict(payload)
    assert cfg.detector_wiring_mode is model.DetectorWiringMode.NO_EOL
    assert cfg.detector_access_mode is model.DetectorAccessMode.NC
    assert cfg.access_module_type is model.AccessModuleType.LOCAL_ZONE
    assert cfg.device_no == 1
    assert cfg.model == "0x00001"
    assert cfg.report_send_delay_time_enabled is False
    assert cfg.report_send_delay_time == 0
    assert cfg.alarm_sound_interlink is not None
    assert cfg.alarm_sound_interlink.linkage_zones == []
    assert cfg.address == 15
    assert cfg.module_type == "localWired"
    assert cfg.support_linkage_keypad_list == []
    assert cfg.related_keypad_no == 0


def test_zone_config_rs485_r3_wireless_recv_related_keypad_list():
    """Zones behind RS485 R3 wireless receivers send relatedKeypadNo as a list."""
    payload = {
        "supportLinkageKeypadList": [1],
        "id": 0,
        "zoneName": "Living room",
        "detectorType": "indoorDualTechnologyDetector",
        "zoneType": "Delay",
        "subSystemNo": 1,
        "linkageSubSystem": [1],
        "armMode": "and",
        "zoneAttrib": "wireless",
        "accessModuleType": "RS485R3WirelessRecv",
        "relatedAccessModuleID": 1,
        "moduleType": "extendWireless",
        "relatedKeypadNo": [],
        "supportLinkageSubSystemList": [1, 2],
        "enterDelay": 60,
        "exitDelay": 60,
        "stayArmDelayTime": 30,
        "sirenDelayTime": 0,
        "stayAwayEnabled": True,
        "chimeEnabled": False,
        "silentEnabled": False,
        "chimeWarningType": "single",
        "timeoutType": "tigger",
        "timeout": 30,
        "relateDetector": True,
        "detectorSeq": "AABBCCDDEEFF",
        "RelatedChanList": [
            {
                "RelatedChan": {
                    "relator": "host",
                    "cameraSeq": "",
                    "relatedChan": 0,
                    "linkageCameraName": "",
                }
            }
        ],
        "doubleKnockEnabled": False,
        "doubleKnockTime": 5,
        "CrossZoneCfg": {
            "isAssociated": False,
            "supportAssociatedZone": [1, 2, 3, 4, 5],
            "alreadyAssociatedZone": [],
            "supportLinkageChannelID": [],
            "alreadyLinkageChannelID": [],
            "associateTime": 1800,
        },
        "newKeyZoneTriggerTypeCfg": "zoneStatus",
        "zoneStatusCfg": "triggerArm",
        "armNoBypassEnabled": False,
        "RelatedPIRCAM": {
            "supportLinkageZones": [],
            "linkageZone": [],
            "linkagePIRCAMName": "",
        },
        "deviceNo": 3,
        "model": "0x000CA",
    }
    cfg = model.ZoneConfig.from_dict(payload)
    assert (
        cfg.access_module_type is model.AccessModuleType.RS485_R3_WIRELESS_RECV
    )
    assert cfg.related_keypad_no == []
    assert cfg.module_type == "extendWireless"
    assert cfg.detector_type is model.DetectorType.INDOOR_DUAL_TECHNOLOGY_DETECTOR
    assert cfg.support_linkage_keypad_list == [1]


def test_relay_switch_conf_and_alarm_cfg_extras():
    payload = {
        "id": 0,
        "name": "Garagepoort",
        "related": True,
        "outputModuleNo": 1,
        "channelNo": 0,
        "deviceNo": 21,
        "subSystem": [1],
        "scenarioType": ["manual"],
        "OriginalStatus": "off",
        "supportLinkageSubSystemList": [1],
        "relayAttrib": "wireless",
        "alarmCfg": {
            "alarmType": [],
            "supportAssociatedZone": [],
            "associateZoneCfg": [],
            "supportDisarmLinkageZone": [],
            "disarmLinkageZone": [],
            "supportLinkageChannelID": [],
            "linkageChannelID": [],
            "alarmLogic": "or",
            "relayMode": "pulse",
            "pulseDuration": 1,
            "contactStatus": "open",
            "zoneTemperature": [],
        },
        "manualCfg": {"relayMode": "latch", "pulseDuration": 0},
    }
    conf = model.RelaySwitchConf.from_dict(payload)
    assert conf.output_module_no == 1
    assert conf.channel_no == 0
    assert conf.device_no == 21
    assert conf.alarm_cfg is not None
    assert conf.alarm_cfg.zone_temperature == []


def test_exdev_siren_keypad_outputmod_remote():
    """Fields from ExDevStatus dumps in 2025-03-12 style payloads."""
    siren = model.Siren.from_dict(
        {
            "id": 1,
            "seq": "Q1",
            "name": "Siren",
            "status": "online",
            "tamperEvident": False,
            "charge": "normal",
            "chargeValue": 95,
            "signal": 120,
            "realSignal": 140,
            "signalType": "R3",
            "model": "0x7A001",
            "temperature": 25,
            "subSystemList": [1],
            "sirenColor": "red",
            "isViaRepeater": False,
            "version": "V1.0.0",
            "deviceNo": 5,
            "abnormalOrNot": False,
            "sirenAttrib": "wireless",
            "mainPowerSupply": True,
            "accessModuleType": "localSiren",
            "intercomServiceEnabled": False,
        }
    )
    assert siren.charge_value == 95
    assert siren.real_signal == 140
    assert siren.signal_type == "R3"
    assert siren.siren_color == "red"
    assert siren.access_module_type == "localSiren"
    assert siren.intercom_service_enabled is False

    keypad = model.Keypad.from_dict(
        {
            "id": 1,
            "seq": "K1",
            "name": "Keypad",
            "status": "online",
            "tamperEvident": False,
            "charge": "normal",
            "chargeValue": 80,
            "signal": 100,
            "realSignal": 110,
            "signalType": "RX",
            "model": "0x92000",
            "temperature": 22,
            "subSystemList": [1],
            "isViaRepeater": False,
            "version": "V1.0.0",
            "deviceNo": 3,
            "abnormalOrNot": False,
        }
    )
    assert keypad.charge_value == 80
    assert keypad.real_signal == 110
    assert keypad.signal_type == "RX"
    assert keypad.abnormal_or_not is False

    output_mod = model.OutputMod.from_dict(
        {
            "id": 1,
            "seq": "Q07565510",
            "status": "online",
            "model": "0x71011",
            "relayList": [
                {
                    "id": 0,
                    "name": "Vrata garáž ",
                    "subSystem": [1],
                    "status": "off",
                    "scenarioType": ["manual"],
                }
            ],
            "deviceNo": 7,
            "version": "V1.0.0",
            "signal": 121,
            "realSignal": 152,
            "signalType": "R3",
            "temperature": 29,
            "isViaRepeater": False,
            "voltValue": 12,
            "voltValueV20": 12.1,
            "currentValue": 1,
            "powerLoad": 0,
            "abnormalOrNot": False,
            "tamperEvident": False,
        }
    )
    assert output_mod.device_no == 7
    assert output_mod.version == "V1.0.0"
    assert output_mod.real_signal == 152
    assert output_mod.signal_type == "R3"
    assert output_mod.abnormal_or_not is False

    remote = model.Remote.from_dict(
        {
            "id": 1,
            "name": "Remote",
            "seq": "R1",
            "model": "0x81000",
            "charge": "normal",
            "isViaRepeater": False,
            "subSystemList": [1],
            "relatedNetUserName": "admin",
            "userNickName": "me",
            "version": "V1.0.0",
            "deviceNo": 9,
            "abnormalOrNot": False,
            "SelKeyList": [{"SelKey": {"key": 1, "func": "panic", "outputNo": 0}}],
        }
    )
    assert remote.sub_system_list == [1]
    assert remote.abnormal_or_not is False

    output = model.OutputStatusFull.from_dict(
        {
            "id": 0,
            "name": "rele1",
            "status": "on",
            "accessModuleType": "fourWiredOutput",
            "relatedAccessModuleID": 2,
            "address": 15,
            "relayAttrib": "wired",
            "scenarioType": ["manual"],
            "subSystemList": [1],
            "linkage": "manualCtrl",
            "deviceNo": 16,
            "charge": "normal",
            "chargeValue": 100,
        }
    )
    assert output.charge_value == 100
    assert output.access_module_type == "fourWiredOutput"

    ext = model.ExtensionModule.from_dict(
        {
            "id": 1,
            "name": "Expander",
            "status": "online",
            "model": "0x73001",
            "type": "RS485R3WirelessRecv",
            "detailType": "wireless",
            "address": 1,
            "deviceNo": 10,
            "moduleAttrib": "wired",
            "version": "V1.0.0",
            "tamperEvident": False,
            "subSystemList": [1],
            "OutputList": [
                {"outputID": 0, "status": "off", "subSystemList": [1]},
            ],
        }
    )
    assert ext.model == "0x73001"
    assert ext.detail_type == "wireless"
    assert ext.device_no == 10
    assert ext.version == "V1.0.0"
    assert ext.sub_system_list == [1]
    assert ext.output_list is not None
    assert ext.output_list[0].output_id == 0


def test_relay_status_accepts_wireless_attrib():
    status = model.RelayStatus.from_dict(
        {
            "id": 0,
            "name": "relay",
            "status": "off",
            "relayAttrib": "wireless",
            "deviceNo": 7,
            "subSystemList": [1],
            "scenarioType": ["manual"],
        }
    )
    assert status.relay_attrib is model.RelayAttrib.WIRELESS


def test_relay_status_is_on_accepts_string_and_enum():
    """exDevStatus uses string status; comparing to Enum always failed (#195)."""
    assert model.relay_status_is_on("on") is True
    assert model.relay_status_is_on("ON") is True
    assert model.relay_status_is_on("off") is False
    assert model.relay_status_is_on(model.RelayStatusEnum.ON) is True
    assert model.relay_status_is_on(model.RelayStatusEnum.OFF) is False
    assert model.relay_status_is_on(None) is False
    # Old buggy comparison: str == Enum is always False
    assert ("on" == model.RelayStatusEnum.ON) is False

    output = model.OutputStatusFull.from_dict(
        {"id": 0, "name": "rele1", "status": "on", "accessModuleType": "fourWiredOutput"}
    )
    assert model.relay_status_is_on(output.status) is True
