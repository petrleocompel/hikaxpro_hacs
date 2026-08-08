"""Helpers for valid, predictable Home Assistant object/entity IDs.

Every entity id is derived from that entity's ``unique_id``, so the two
never drift apart and the id is unique by construction: no numeric
``_2`` suffixes appear when two panels carry zones with the same name.
An underscore only ever separates two distinct pieces of information —
the panel MAC stays one compact token, and the trailing number is the
zone (or area, battery, siren…) the entity belongs to::

    a4d5c26bb859-tamper-1  ->  binary_sensor.a4d5c26bb859_tamper_1
"""

from __future__ import annotations

from hashlib import sha1
import re

from homeassistant.util import slugify

INVALID_OBJECT_ID_RE = re.compile(r"[^a-z0-9_]")


def normalized_mac(mac: str | None) -> str:
    """Return the MAC as one compact token: ``a4d5c26bb859``.

    Separators carry no information here, and spelling the MAC out as
    ``a4:d5:...`` (or, once slugified, ``a4_d5_...``) turns a single
    identifier into six. Keeping it compact leaves ``_`` free to
    separate genuinely different parts of an id.
    """
    return re.sub(r"[^a-z0-9]", "", (mac or "").lower())


def normalized_object_id(value: str | None, fallback: str | None = None) -> str:
    """Return a valid HA object_id slug.

    Uses HA slugify first. If that produces an empty value, falls back to a
    slugified fallback, then finally to a deterministic hash-based identifier.
    """
    slug = slugify(value or "")
    if slug:
        return slug

    fallback_slug = slugify(fallback or "")
    if fallback_slug:
        return fallback_slug

    seed = (fallback or value or "entity").encode("utf-8")
    return f"entity_{sha1(seed).hexdigest()[:10]}"


def has_invalid_object_id_chars(entity_id: str) -> bool:
    """Return True when object_id contains chars outside [a-z0-9_]."""
    if "." not in entity_id:
        return True
    _, object_id = entity_id.split(".", 1)
    return bool(INVALID_OBJECT_ID_RE.search(object_id))


def build_entity_id(
    domain: str,
    unique_id: str | None,
    mac_id: str,
    device_name: str | None = None,
    number_marker: str = "",
) -> str:
    """Build ``<domain>.<device>_z<zone>_<name>_<compact mac>``.

    The parts come from the entity's own ``unique_id``, which is
    ``<compact mac>-<name>[-<number>]``, so the id is unique by
    construction and Home Assistant never has to disambiguate with a
    ``_2`` suffix when two panels carry zones of the same name.

A zone number is written ``z1`` rather than left bare, so it reads
    as a zone and can never be mistaken for one of those dedup suffixes.
    ``number_marker`` is what the number counts, so it is only ``"z"``
    for entities that really belong to a zone — a hub battery or a relay
    keeps its own plain number. The number sits next to the device it
    qualifies and the id ends on the MAC that says which panel::

        ingresso + a4d5c26bb859-tamper-1      (zone)
            -> binary_sensor.ingresso_z1_tamper_a4d5c26bb859
        alarm    + a4d5c26bb859-hub-battery-1 (not a zone)
            -> sensor.alarm_hub_battery_1_a4d5c26bb859
        alarm    + a4d5c26bb859-ac-power      (nothing numbered)
            -> binary_sensor.alarm_ac_power_a4d5c26bb859

    Only new entities are affected: Home Assistant keeps whatever
    entity_id the registry already holds for a known unique_id, so an
    existing installation — including hand-picked ids — is left as is.
    """
    tokens = [t for t in normalized_object_id(unique_id).split("_") if t]
    mac_token = normalized_object_id(mac_id)

    # Drop the MAC wherever it sits; it is re-appended at the end.
    rest = [t for t in tokens if t != mac_token]

    # A trailing run of digits identifies the zone / area / device.
    numbers: list[str] = []
    while rest and rest[-1].isdigit():
        numbers.insert(0, rest.pop())

    device = [t for t in slugify(device_name or "").split("_") if t]
    # A device already named after what the entity reports would repeat
    # itself ("front door alarm" + "alarm"); keep the leading copy only.
    while device and rest and device[-1] == rest[0]:
        rest.pop(0)
    # Likewise when the device name already ends in the number, as area
    # panels do ("Area 1" + area 1): no need to say it twice.
    while device and numbers and device[-1] == numbers[0]:
        numbers.pop(0)

    if number_marker:
        # A marked number leads, right after the device it qualifies.
        parts = [*device, *(f"{number_marker}{n}" for n in numbers), *rest]
    else:
        # An unmarked number stays attached to what it counts.
        parts = [*device, *rest, *numbers]
    if mac_token:
        parts.append(mac_token)
    return f"{domain}.{'_'.join(parts)}"
