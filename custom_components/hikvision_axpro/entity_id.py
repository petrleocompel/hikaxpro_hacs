"""Helpers for valid Home Assistant object/entity IDs."""

from __future__ import annotations

from hashlib import sha1
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

INVALID_OBJECT_ID_RE = re.compile(r"[^a-z0-9_]")


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


def build_entity_id(domain: str, device_name: str | None, *parts: object) -> str:
    """Build a valid entity_id: ``{domain}.{device}_{suffix}_{id}``.

    Example: ``sensor.ax_pro_temperature_0``.
    """
    object_parts = [normalized_object_id(device_name, fallback="axpro")]
    for part in parts:
        if part is None:
            continue
        object_parts.append(normalized_object_id(str(part)))
    return f"{domain}.{'_'.join(object_parts)}"


def migrate_invalid_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename registry entries whose object_id is not a valid HA slug."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not has_invalid_object_id_chars(entity.entity_id):
            continue

        domain, object_id = entity.entity_id.split(".", 1)
        new_object_id = normalized_object_id(object_id)
        new_entity_id = f"{domain}.{new_object_id}"

        if new_entity_id == entity.entity_id:
            continue

        if registry.async_get(new_entity_id) is not None:
            # Avoid clobbering an existing entity; append a short unique suffix.
            new_entity_id = f"{domain}.{new_object_id}_{entity.unique_id[-6:]}"
            new_entity_id = (
                f"{domain}.{normalized_object_id(new_entity_id.split('.', 1)[1])}"
            )

        _LOGGER.info(
            "Migrating invalid entity_id %s -> %s", entity.entity_id, new_entity_id
        )
        registry.async_update_entity(entity.entity_id, new_entity_id=new_entity_id)
