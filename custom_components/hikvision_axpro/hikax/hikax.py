from typing import Optional, Any

import requests
from xml.etree import ElementTree
import consts
from models import SessionLoginCap, SessionLogin
from .helpers import sha256, xmlBuilder
from errors import errors
from datetime import datetime
import logging


_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

class HikAxPro:
    """HikVisison Ax Pro Alarm panel coordinator."""

    def __init__(self, host, username, password):
        self.host = host
        self.username = username
        self.password = password
        self.cookie = ''

    def get_session_params(self):
        response = requests.get(f"http://{self.username}:{self.password}@{self.host}{consts.Endpoints.Session_Capabilities}{self.username}")
        _LOGGER.debug("Session_Capabilities response")
        _LOGGER.debug("Status: %s", response.status_code)
        _LOGGER.debug("Content: %s", response.content)
        _LOGGER.debug("Text: %s", response.text)
        _LOGGER.debug("End Session_Capabilities response")
        if response.status_code == 200:
            try:
                session_cap = self.parse_session_response(response.text)
                return session_cap
            except:
                raise errors.IncorrectResponseContentError()
        else:
            return None

    @staticmethod
    def _root_get_value(root, ns, key, default = None) -> Any | None:
        item = root.find(key, ns)
        if item is not None:
            return item.text
        return default

    @staticmethod
    def parse_session_response(xml_data):
        _LOGGER.warning("Debug data %s", xml_data)
        root = ElementTree.fromstring(xml_data)
        namespaces = {'xmlns': consts.XML_SCHEMA}
        session_id = HikAxPro._root_get_value(root, namespaces, "xmlns:sessionID")
        challenge = HikAxPro._root_get_value(root, namespaces, "xmlns:challenge")
        salt = HikAxPro._root_get_value(root, namespaces, "xmlns:salt")
        salt2 = HikAxPro._root_get_value(root, namespaces, "xmlns:salt2")
        is_irreversible = HikAxPro._root_get_value(root, namespaces, "xmlns:isIrreversible", False)
        iterations = HikAxPro._root_get_value(root,namespaces, "xmlns:iterations")
        session_cap = SessionLoginCap.SessionLoginCap(
            sessionID=session_id,
            challange=challenge,
            salt=salt,
            salt2=salt2,
            isIrreversible=is_irreversible,
            iterations=int(iterations) if iterations is not None else None
        )
        return session_cap

    def encode_password(self, session_cap):
        if session_cap.isIrreversible:
            result = sha256.sha256(f"{self.username}{session_cap.salt}{self.password}")
            result = sha256.sha256(f"{self.username}{session_cap.salt2}{result}")
            result = sha256.sha256(f"{result}{session_cap.challange}")

            for i in range(2, session_cap.iteration):
                result = sha256.sha256(result)
        else:
            result = f"{sha256.sha256(self.password)}{session_cap.challange}"

            for i in range(1, session_cap.iteration):
                result = sha256.sha256(result)

        return result

    def connect(self):
        params = self.get_session_params()

        encoded_password = self.encode_password(params)

        xml = xmlBuilder.serialize_object(
            SessionLogin.SessionLogin(
                params.sessionID,
                self.username,
                encoded_password
            )
        )

        dt = datetime.now()
        timestamp = datetime.timestamp(dt)
        session_login_url = f"http://{self.host}{consts.Endpoints.Session_Login}?timeStamp={int(timestamp)}"
        result = False
        try:
            login_response: requests.Response = requests.post(session_login_url, xml)
            _LOGGER.debug("Connect response")
            _LOGGER.debug("Status: %s", login_response.status_code)
            _LOGGER.debug("Content: %s", login_response.content)
            _LOGGER.debug("Text: %s", login_response.text)
            _LOGGER.debug("End connect response")
            if login_response.status_code == 200:
                self.cookie = login_response.headers["Set-Cookie"].split(";")[0]
                result = True
        except:
            result = False

        return result

    @staticmethod
    def build_url(endpoint, is_json):
        param_prefix = "&" if "?" in endpoint else "?"
        return f"{endpoint}{param_prefix}format=json" if is_json else endpoint

    def _base_json_request(self, url: str, method: consts.Method = consts.Method.GET):
        endpoint = self.build_url(url, True)
        response = self.make_request(endpoint, method, is_json=True)

        if response.status_code != 200:
            raise errors.UnexpectedResponseCodeError(response.status_code, response.text)
        if response.status_code == 200:
            return response.json()

    def arm_home(self, sub_id: Optional[int]):
        sid = "0xffffffff" if sub_id is None else str(sub_id)
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.Alarm_ArmHome.replace('{}', sid)}",
                                       method=consts.Method.PUT)

    def arm_away(self, sub_id: Optional[int]):
        sid = "0xffffffff" if sub_id is None else str(sub_id)
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.Alarm_ArmAway.replace('{}', sid)}",
                                       method=consts.Method.PUT)

    def disarm(self, sub_id: Optional[int]):
        sid = "0xffffffff" if sub_id is None else str(sub_id)
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.Alarm_Disarm.replace('{}', sid)}",
                                       method=consts.Method.PUT)

    def subsystem_status(self):
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.SubSystemStatus}")

    def peripherals_status(self):
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.PeripheralsStatus}")

    def zone_status(self):
        endpoint = f"http://{self.host}{consts.Endpoints.ZoneStatus}"
        endpoint = self.build_url(endpoint, True)
        response = self.make_request(endpoint, consts.Method.GET)

        if response.status_code != 200:
            raise errors.UnexpectedResponseCodeError(response.status_code, response.text)

        return response.json()

    def bypass_zone(self, zone_id):
        endpoint = f"http://{self.host}{consts.Endpoints.BypassZone}{zone_id}"
        endpoint = self.build_url(endpoint, True)
        response = self.make_request(endpoint, consts.Method.PUT)

        if response.status_code != 200:
            raise errors.UnexpectedResponseCodeError(response.status_code, response.text)

        return response.status_code == 200

    def recover_bypass_zone(self, zone_id):
        endpoint = f"http://{self.host}{consts.Endpoints.RecoverBypassZone}{zone_id}"
        endpoint = self.build_url(endpoint, True)
        response = self.make_request(endpoint, consts.Method.PUT)

        return response.status_code == 200

    def get_interface_mac_address(self, interface_id):
        endpoint = f"http://{self.host}{consts.Endpoints.InterfaceInfo}"

        response = self.make_request(endpoint, consts.Method.GET)

        if response.status_code == 200:
            return xmlBuilder.get_mac_address_of_interface(response.text, interface_id)

        return ''

    def get_area_arm_status(self, area_id):
        endpoint = f"http://{self.host}{consts.Endpoints.AreaArmStatus}"
        endpoint = self.build_url(endpoint, True)

        data = {"SubSysList": [{"SubSys": {"id": area_id}}]}

        response = self.make_request(endpoint, consts.Method.POST, data=data, is_json=True)

        try:
            if response.status_code == 200:
                response_json = response.json()
                return response_json["ArmStatusList"][0]["ArmStatus"]["status"]
        except:
            return ''
        return ''

    def host_status(self):
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.HostStatus}")

    def siren_status(self):
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.SirenStatus}")

    def keypad_status(self):
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.KeypadStatus}")

    def repeater_status(self):
        return self._base_json_request(f"http://{self.host}{consts.Endpoints.RepeaterStatus}")

    def make_request(self, endpoint, method, data=None, is_json=False):
        headers = {"Cookie": self.cookie}

        if method == consts.Method.GET:
            response = requests.get(endpoint, headers=headers)
        elif method == consts.Method.POST:
            if is_json:
                response = requests.post(endpoint, json=data, headers=headers)
            else:
                response = requests.post(endpoint, data=data, headers=headers)
        elif method == consts.Method.PUT:
            if is_json:
                response = requests.post(endpoint, json=data, headers=headers)
            else:
                response = requests.put(endpoint, data=data, headers=headers)
        else:
            return None

        if response.status_code == 401:
            self.connect()
            response = self.make_request(endpoint, method, data, is_json)

        return response
