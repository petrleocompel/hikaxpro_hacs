import consts
from xml.etree import ElementTree


def serialize_object(obj):
    result = f"<{type(obj).__name__}>"
    
    for prop, value in vars(obj).items():
        if prop in consts.XML_SERIALIZABLE_NAMES:
            result += f"<{prop}>{value}</{prop}>"
    
    result += f"</{type(obj).__name__}>"

    return result


def get_mac_address_of_interface(xml_data, interface_id):
    try:
        root = ElementTree.fromstring(xml_data)
        namespaces = {'xmlns': consts.XML_SCHEMA}        
        for ni_element in root.findall('xmlns:NetworkInterface', namespaces):
            if ni_element.find('xmlns:id', namespaces).text == str(interface_id):
                link_elm = ni_element.find('xmlns:Link', namespaces)
                return link_elm.find('xmlns:MACAddress', namespaces).text
    except(Exception) as ex:
        return ''
    
    return ''
