import logging
from enum import Enum
from dataclasses import dataclass
from typing import Any, List, Optional, TypeVar, Callable, Type, cast

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
EnumT = TypeVar("EnumT", bound=Enum)


def from_int(x: Any) -> int:
    assert isinstance(x, int) and not isinstance(x, bool)
    return x


def from_bool(x: Any) -> bool:
    assert isinstance(x, bool)
    return x


def from_str(x: Any) -> str:
    assert isinstance(x, str)
    return x


def from_list(f: Callable[[Any], T], x: Any) -> List[T]:
    assert isinstance(x, list)
    return [f(y) for y in x]


def from_none(x: Any) -> Any:
    assert x is None
    return x


def from_union(fs, x):
    for f in fs:
        try:
            return f(x)
        except:
            pass
    assert False


def to_enum(c: Type[EnumT], x: Any) -> EnumT:
    assert isinstance(x, c)
    return x.value


def to_class(c: Type[T], x: Any) -> dict:
    assert isinstance(x, c)
    return cast(Any, x).to_dict()


class AccessModuleType(Enum):
    LOCAL_TRANSMITTER = "localTransmitter"
    MULTI_TRANSMITTER = "multiTransmitter"
    LOCAL_ZONE = "localZone"
    LOCAL_RELAY = "localRelay"
    LOCAL_SIREN = "localSiren"
    KEYPAD = "keypad"
    # Undocumented type
    INPUT_MAIN_ZONE = "inputMainZone"


class DetectorType(Enum):
    ACTIVE_IR_DETECTOR = "activeInfraredDetector"
    CONTROL_SWITCH = "controlSwitch"
    DISPLACEMENT_DETECTOR = "displacementDetector"
    DOOR_CONTACT = "singleInfraredDetector"
    DOOR_MAGNETIC_CONTACT_DETECTOR = "magneticContact"
    DUAL_TECHNOLOGY_MOTION_DETECTOR = "dualTechnologyPirDetector"
    DYNAMIC_SWITCH = "dynamicSwitch"
    GAS_DETECTOR = "combustibleGasDetector"
    GLASS_BREAK_DETECTOR = "glassBreakDetector"
    HUMIDITY_DETECTOR = "humidityDetector"
    INDOOR_DUAL_TECHNOLOGY_DETECTOR = "indoorDualTechnologyDetector"
    IR_CURTAIN_DETECTOR = "curtainInfraredDetector"
    MAGNET_SHOCK_DETECTOR = "magnetShockDetector"
    PANIC_BUTTON = "panicButton"
    PIRCAM_DETECTOR = "pircam"
    PIR_DETECTOR = "passiveInfraredDetector"
    SHOCK_DETECTOR = "vibrationDetector"
    SLIM_MAGNETIC_CONTACT = "slimMagneticContact"
    SMART_LOCK = "smartLock"
    SMOKE_DETECTOR = "smokeDetector"
    TEMPERATURE_DETECTOR = "temperatureDetector"
    TRIPLE_TECHNOLOGY_DETECTOR = "tripleTechnologyPirDetector"
    WATER_DETECTOR = "waterDetector"
    WATER_LEAK_DETECTOR = "waterLeakDetector"
    WIRELESS_CODETECTOR = "wirelessCODetector"
    WIRELESS_DTAMCURTAIN_DETECTOR = "wirelessDTAMCurtainDetector"
    WIRELESS_EXTERNAL_MAGNET_DETECTOR = "wirelessExternalMagnetDetector"
    WIRELESS_GLASS_BREAK_DETECTOR = "wirelessGlassBreakDetector"
    WIRELESS_HEAT_DETECTOR = "wirelessHeatDetector"
    WIRELESS_PIRCEILING_DETECTOR = "wirelessPIRCeilingDetector"
    WIRELESS_PIRCURTAIN_DETECTOR = "wirelessPIRCurtainDetector"
    WIRELESS_SINGLE_INPUT_EXPANDER = "singleZoneModule"
    WIRELESS_SMOKE_DETECTOR = "wirelessSmokeDetector"
    WIRELESS_TEMPERATURE_HUMIDITY_DETECTOR = "wirelessTemperatureHumidityDetector"
    OTHER = "other"


def detector_model_to_name(model_id: Optional[str]) -> str:
    if model_id == "0x00001":
        return "Passive Infrared Detector"
    if model_id == "0x00005":
        return "Slim Magnetic Contact"
    if model_id == "0x00006":
        return "Magnetic Contact"
    if model_id == "0x00012":
        return "Wireless PIR CAM Detector"
    if model_id == "0x00015":
        return "Wireless Smoke Detector"
    if model_id == "0x00017":
        return "Wireless Magnet Shock Detector"
    if model_id == "0x00018":
        return "Glass Break Detector"
    if model_id == "0x00026":
        return "Wireless Temperature Humidity Detector"
    if model_id == "0x00028":
        return "Wireless External Magnet Detector"
    if model_id == "0x00032":
        return "Wireless PIR AM Curtain Detector"
    if model_id is not None:
        return str(model_id)
    return "Unknown"


@dataclass
class InputList:
    id: int
    enabled: bool
    mode: str

    @staticmethod
    def from_dict(obj: Any) -> 'InputList':
        assert isinstance(obj, dict)
        id = from_int(obj.get("id"))
        enabled = from_bool(obj.get("enabled"))
        mode = from_str(obj.get("mode"))
        return InputList(id, enabled, mode)

    def to_dict(self) -> dict:
        result: dict = {}
        result["id"] = from_int(self.id)
        result["enabled"] = from_bool(self.enabled)
        result["mode"] = from_str(self.mode)
        return result



class Status(Enum):
    ONLINE = "online"
    TRIGGER = "trigger"
    OFFLINE = "offline"
    BREAK_DOWN = "breakDown"
    HEART_BEAT_ABNORMAL = "heartbeatAbnormal"
    NOT_RELATED = "notRelated"


class ZoneAttrib(Enum):
    WIRED = "wired"
    WIRELESS = "wireless"


class ZoneType(Enum):
    """ delay zone """
    DELAY = "Delay"
    """ panic zone """
    EMERGENCY = "Emergency"
    """ fire zone """
    FIRE = "Fire"
    """ follow zone """
    FOLLOW = "Follow"
    """ gas zone """
    GAS = "Gas"
    """ key """
    KEY = "Key"
    """ medical zone """
    MEDICAL = "Medical"
    """ disabled zone """
    NON_ALARM = "Non-Alarm"
    """ 24 - hour silent zone """
    NO_SOUND_24 = "24hNoSound"
    """ perimeter zone """
    PERIMETER = "Perimeter"
    """ timeout zone """
    TIMEOUT = "Timeout"
    """ instant zone """
    INSTANT = "Instant"


@dataclass
class Zone:
    id: int
    name: str
    status: Optional[Status]
    tamper_evident: Optional[bool]
    shielded: Optional[bool]
    bypassed: Optional[bool]
    armed: bool
    is_arming: Optional[bool]
    alarm: Optional[bool]
    sub_system_no: Optional[int]
    linkage_sub_system: Optional[list[int]]
    detector_type: Optional[DetectorType]
    stay_away: Optional[bool]
    zone_type: Optional[ZoneType]
    zone_attrib: Optional[ZoneAttrib]
    device_no: Optional[int]
    abnormal_or_not: Optional[bool] = None
    charge: Optional[str] = None
    charge_value: Optional[int] = None
    signal: Optional[int] = None
    temperature: Optional[int] = None
    humidity: Optional[int] = None
    model: Optional[str] = None
    is_via_repeater: Optional[bool] = None
    version: Optional[str] = None
    magnet_open_status: Optional[bool] = None
    input_list: Optional[list[InputList]] = None
    is_support_add_type: Optional[bool] = None
    access_module_type: Optional[AccessModuleType] = None
    module_channel: Optional[int] = None

    @staticmethod
    def from_dict(obj: Any) -> 'Zone':
        assert isinstance(obj, dict)
        id = from_int(obj.get("id"))
        if obj.get("name") is None:
            name = f"Zone ID {id}"
        else:
            name = from_str(obj.get("name"))
        tamper_evident = from_union([from_bool, from_none], obj.get("tamperEvident"))
        shielded = from_union([from_bool, from_none], obj.get("shielded"))
        bypassed = from_union([from_bool, from_none], obj.get("bypassed"))
        armed = from_bool(obj.get("armed"))
        is_arming = from_union([from_bool, from_none], obj.get("isArming"))
        alarm = from_union([from_bool, from_none], obj.get("alarm"))
        sub_system_no = from_union([from_int, from_none], obj.get("subSystemNo"))

        try:
            linkage_sub_system = from_list(from_int, obj.get("linkageSubSystem"))
        except:
            _LOGGER.warning("Invalid zone linkage_sub_system %s", obj.get("linkage_sub_system"))
            _LOGGER.warning("Zone info: %s", obj)
            linkage_sub_system = None

        stay_away = from_union([from_bool, from_none], obj.get("stayAway"))
        device_no = from_union([from_int, from_none], obj.get("deviceNo"))
        abnormal_or_not = from_union([from_bool, from_none], obj.get("abnormalOrNot"))
        charge = from_union([from_str, from_none], obj.get("charge"))
        charge_value = from_union([from_int, from_none], obj.get("chargeValue"))
        signal = from_union([from_int, from_none], obj.get("signal"))
        temperature = from_union([from_int, from_none], obj.get("temperature"))
        humidity = from_union([from_int, from_none], obj.get("humidity"))
        model = from_union([from_str, from_none], obj.get("model"))
        is_via_repeater = from_union([from_bool, from_none], obj.get("isViaRepeater"))
        version = from_union([from_str, from_none], obj.get("version"))
        magnet_open_status = from_union([from_bool, from_none], obj.get("magnetOpenStatus"))
        input_list = from_union([lambda x: from_list(InputList.from_dict, x), from_none], obj.get("InputList"))
        is_support_add_type = from_union([from_bool, from_none], obj.get("isSupportAddType"))
        module_channel = from_union([from_int, from_none], obj.get("moduleChannel"))

        try:
            status = Status(obj.get("status"))
        except:
            _LOGGER.warning("Invalid status %s", obj.get("status"))
            _LOGGER.warning("Detector info: %s", obj)
            status = None
        try:
            detector_type = DetectorType(obj.get("detectorType"))
        except:
            _LOGGER.warning("Invalid detector type %s", obj.get("detectorType"))
            _LOGGER.warning("Detector info: %s", obj)
            detector_type = None
        try:
            zone_type = ZoneType(obj.get("zoneType"))
        except:
            _LOGGER.warning("Invalid zone type %s", obj.get("zoneType"))
            _LOGGER.warning("Detector info: %s", obj)
            zone_type = None
        try:
            zone_attrib = ZoneAttrib(obj.get("zoneAttrib"))
        except:
            _LOGGER.warning("Invalid zone attrib %s", obj.get("zoneAttrib"))
            _LOGGER.warning("Detector info: %s", obj)
            zone_attrib = None
        try:
            access_module_type = from_union([AccessModuleType, from_none], obj.get("accessModuleType"))
        except:
            _LOGGER.warning("Invalid accessModuleType %s", obj.get("accessModuleType"))
            _LOGGER.warning("Detector info: %s", obj)
            access_module_type = None
        return Zone(id, name, status, tamper_evident, shielded, bypassed, armed, is_arming, alarm, sub_system_no,
                    linkage_sub_system, detector_type, stay_away, zone_type, zone_attrib, device_no, abnormal_or_not,
                    charge, charge_value, signal, temperature, humidity, model, is_via_repeater, version,
                    magnet_open_status, input_list, is_support_add_type, access_module_type, module_channel)

    def to_dict(self) -> dict:
        result: dict = {}
        result["id"] = from_int(self.id)
        result["name"] = from_str(self.name)
        result["status"] = to_enum(Status, self.status)
        result["tamperEvident"] = from_bool(self.tamper_evident)
        result["shielded"] = from_bool(self.shielded)
        result["bypassed"] = from_bool(self.bypassed)
        result["armed"] = from_bool(self.armed)
        result["isArming"] = from_bool(self.is_arming)
        result["alarm"] = from_bool(self.alarm)
        result["subSystemNo"] = from_int(self.sub_system_no)
        result["linkageSubSystem"] = from_list(from_int, self.linkage_sub_system)
        result["detectorType"] = to_enum(DetectorType, self.detector_type)
        result["stayAway"] = from_bool(self.stay_away)
        result["zoneType"] = to_enum(ZoneType, self.zone_type)
        result["zoneAttrib"] = to_enum(ZoneAttrib, self.zone_attrib)
        result["deviceNo"] = from_int(self.device_no)
        result["abnormalOrNot"] = from_union([from_bool, from_none], self.abnormal_or_not)
        result["charge"] = from_union([from_str, from_none], self.charge)
        result["chargeValue"] = from_union([from_int, from_none], self.charge_value)
        result["signal"] = from_union([from_int, from_none], self.signal)
        result["temperature"] = from_union([from_int, from_none], self.temperature)
        result["humidity"] = from_union([from_int, from_none], self.humidity)
        result["model"] = from_union([from_str, from_none], self.model)
        result["isViaRepeater"] = from_union([from_bool, from_none], self.is_via_repeater)
        result["version"] = from_union([from_str, from_none], self.version)
        result["magnetOpenStatus"] = from_union([from_bool, from_none], self.magnet_open_status)
        result["InputList"] = from_union([lambda x: from_list(lambda x: to_class(InputList, x), x), from_none],
                                         self.input_list)
        result["isSupportAddType"] = from_union([from_bool, from_none], self.is_support_add_type)
        result["accessModuleType"] = from_union([lambda x: to_enum(AccessModuleType, x), from_none],
                                                self.access_module_type)
        result["moduleChannel"] = from_union([from_int, from_none], self.module_channel)
        return result


@dataclass
class ZoneList:
    zone: Zone

    @staticmethod
    def from_dict(obj: Any) -> 'ZoneList':
        assert isinstance(obj, dict)
        zone = Zone.from_dict(obj.get("Zone"))
        return ZoneList(zone)

    def to_dict(self) -> dict:
        result: dict = {}
        result["Zone"] = to_class(Zone, self.zone)
        return result


@dataclass
class ZonesResponse:
    zone_list: List[ZoneList]

    @staticmethod
    def from_dict(obj: Any) -> 'ZonesResponse':
        assert isinstance(obj, dict)
        zone_list = from_list(ZoneList.from_dict, obj.get("ZoneList"))
        return ZonesResponse(zone_list)

    def to_dict(self) -> dict:
        result: dict = {}
        result["ZoneList"] = from_list(lambda x: to_class(ZoneList, x), self.zone_list)
        return result


class Arming(Enum):
    AWAY = "away"
    STAY = "stay"
    VACATION = "vacation"
    DISARM = "disarm"
    ARMING = "arming"


@dataclass
class SubSys:
    id: int
    arming: Arming
    alarm: bool
    enabled: bool
    name: str
    delay_time: int

    @staticmethod
    def from_dict(obj: Any) -> 'SubSys':
        assert isinstance(obj, dict)
        id = from_int(obj.get("id"))
        try:
            arming = Arming(obj.get("arming"))
        except:
            _LOGGER.warning("Invalid subsys attr arming %s", obj.get("arming"))
            _LOGGER.warning("Subsys: %s", obj)
            arming = None
        alarm = from_bool(obj.get("alarm"))
        enabled = from_union([from_bool, from_none], obj.get("enabled"))
        if enabled is None:
            enabled = True
        name = from_union([from_str, from_none], obj.get("name"))
        delay_time = from_union([from_int, from_none], obj.get("delayTime"))
        return SubSys(id, arming, alarm, enabled, name, delay_time)

    def to_dict(self) -> dict:
        result: dict = {}
        result["id"] = from_int(self.id)
        result["arming"] = to_enum(Arming, self.arming)
        result["alarm"] = from_bool(self.alarm)
        result["enabled"] = from_bool(self.enabled)
        result["name"] = from_str(self.name)
        result["delayTime"] = from_int(self.delay_time)
        return result


@dataclass
class SubSysList:
    sub_sys: SubSys

    @staticmethod
    def from_dict(obj: Any) -> 'SubSysList':
        assert isinstance(obj, dict)
        sub_sys = SubSys.from_dict(obj.get("SubSys"))
        return SubSysList(sub_sys)

    def to_dict(self) -> dict:
        result: dict = {}
        result["SubSys"] = to_class(SubSys, self.sub_sys)
        return result


@dataclass
class SubSystemResponse:
    sub_sys_list: List[SubSysList]

    @staticmethod
    def from_dict(obj: Any) -> 'SubSystemResponse':
        assert isinstance(obj, dict)
        sub_sys_list = from_list(SubSysList.from_dict, obj.get("SubSysList"))
        return SubSystemResponse(sub_sys_list)

    def to_dict(self) -> dict:
        result: dict = {}
        result["SubSysList"] = from_list(lambda x: to_class(SubSysList, x), self.sub_sys_list)
        return result
