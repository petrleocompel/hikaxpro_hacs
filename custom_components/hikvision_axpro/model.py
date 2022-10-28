# To use this code, make sure you
#
#     import json
#
# and then, to convert JSON from a string, do
#
#     result = welcome_from_dict(json.loads(json_string))

from enum import Enum
from dataclasses import dataclass
from typing import Any, List, Optional, TypeVar, Callable, Type, cast


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


class DetectorType(Enum):
    OTHER = "other"
    PASSIVE_INFRARED_DETECTOR = "passiveInfraredDetector"
    WIRELESS_EXTERNAL_MAGNET_DETECTOR = "wirelessExternalMagnetDetector"
    WIRELESS_TEMPERATURE_HUMIDITY_DETECTOR = "wirelessTemperatureHumidityDetector"


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


class ZoneAttrib(Enum):
    WIRED = "wired"
    WIRELESS = "wireless"


class ZoneType(Enum):
    FOLLOW = "Follow"
    INSTANT = "Instant"


@dataclass
class Zone:
    id: int
    name: str
    status: Status
    tamper_evident: bool
    shielded: bool
    bypassed: bool
    armed: bool
    is_arming: bool
    alarm: bool
    sub_system_no: int
    linkage_sub_system: List[int]
    detector_type: DetectorType
    stay_away: bool
    zone_type: ZoneType
    zone_attrib: ZoneAttrib
    device_no: int
    abnormal_or_not: bool
    charge: Optional[str] = None
    charge_value: Optional[int] = None
    signal: Optional[int] = None
    temperature: Optional[int] = None
    humidity: Optional[int] = None
    model: Optional[str] = None
    is_via_repeater: Optional[bool] = None
    version: Optional[str] = None
    magnet_open_status: Optional[bool] = None
    input_list: Optional[List[InputList]] = None
    is_support_add_type: Optional[bool] = None
    access_module_type: Optional[AccessModuleType] = None
    module_channel: Optional[int] = None

    @staticmethod
    def from_dict(obj: Any) -> 'Zone':
        assert isinstance(obj, dict)
        id = from_int(obj.get("id"))
        name = from_str(obj.get("name"))
        status = Status(obj.get("status"))
        tamper_evident = from_bool(obj.get("tamperEvident"))
        shielded = from_bool(obj.get("shielded"))
        bypassed = from_bool(obj.get("bypassed"))
        armed = from_bool(obj.get("armed"))
        is_arming = from_bool(obj.get("isArming"))
        alarm = from_bool(obj.get("alarm"))
        sub_system_no = from_int(obj.get("subSystemNo"))
        linkage_sub_system = from_list(from_int, obj.get("linkageSubSystem"))
        detector_type = DetectorType(obj.get("detectorType"))
        stay_away = from_bool(obj.get("stayAway"))
        zone_type = ZoneType(obj.get("zoneType"))
        zone_attrib = ZoneAttrib(obj.get("zoneAttrib"))
        device_no = from_int(obj.get("deviceNo"))
        abnormal_or_not = from_bool(obj.get("abnormalOrNot"))
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
        access_module_type = from_union([AccessModuleType, from_none], obj.get("accessModuleType"))
        module_channel = from_union([from_int, from_none], obj.get("moduleChannel"))
        return Zone(id, name, status, tamper_evident, shielded, bypassed, armed, is_arming, alarm, sub_system_no, linkage_sub_system, detector_type, stay_away, zone_type, zone_attrib, device_no, abnormal_or_not, charge, charge_value, signal, temperature, humidity, model, is_via_repeater, version, magnet_open_status, input_list, is_support_add_type, access_module_type, module_channel)

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
        result["abnormalOrNot"] = from_bool(self.abnormal_or_not)
        result["charge"] = from_union([from_str, from_none], self.charge)
        result["chargeValue"] = from_union([from_int, from_none], self.charge_value)
        result["signal"] = from_union([from_int, from_none], self.signal)
        result["temperature"] = from_union([from_int, from_none], self.temperature)
        result["humidity"] = from_union([from_int, from_none], self.humidity)
        result["model"] = from_union([from_str, from_none], self.model)
        result["isViaRepeater"] = from_union([from_bool, from_none], self.is_via_repeater)
        result["version"] = from_union([from_str, from_none], self.version)
        result["magnetOpenStatus"] = from_union([from_bool, from_none], self.magnet_open_status)
        result["InputList"] = from_union([lambda x: from_list(lambda x: to_class(InputList, x), x), from_none], self.input_list)
        result["isSupportAddType"] = from_union([from_bool, from_none], self.is_support_add_type)
        result["accessModuleType"] = from_union([lambda x: to_enum(AccessModuleType, x), from_none], self.access_module_type)
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


def welcome_from_dict(s: Any) -> ZonesResponse:
    return ZonesResponse.from_dict(s)


def welcome_to_dict(x: ZonesResponse) -> Any:
    return to_class(ZonesResponse, x)
