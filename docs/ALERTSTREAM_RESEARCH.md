# AlertStream research spike (#143 / #2)

Status: **research only** — not productized. Local polling remains the supported path.

## Documented endpoints

From Hikvision ISAPI (general) `isapi.pdf` §15.3:

| Endpoint | Role |
|---|---|
| `GET /ISAPI/Event/notification/alertStream` | Long-lived HTTP stream of device events |
| `/ISAPI/Event/notification/httpHosts` | Configure HTTP notification targets |
| `/ISAPI/Event/notification/subscribeEvent` | Subscribe / unsubscribe helpers |

The Security Control SDK HTML guide (V6.1.5.X) focuses on `SecurityCP` status/control APIs and does **not** usefully document AX Pro zone-motion event taxonomy for `alertStream`.

`hikaxpro` already defines `Endpoints.AlertStream` but this integration does not open the stream.

## What we already observed on AX Pro

Prior experiments (see [#143](https://github.com/petrleocompel/hikaxpro_hacs/issues/143)):

- Stream can emit `cidEvent` payloads for **arm / disarm**.
- Arm and disarm share the same CID event type (`armAndDisarm`); distinguishing them needs careful state correlation.
- It is still unclear whether **disarmed zone motion** (PIR trigger for automations) is pushed on the stream, or only when the area is armed / when ARC-style notification flags are enabled.

ARC config mentions flags such as `zoneAlarmEnabled`, `operateEventEnabled`, `systemStatusEnabled` — these may gate what is uploaded, and may not equal a full local event bus for HA automations.

## Recommended next experiments (manual)

1. Open a long-lived `GET /ISAPI/Event/notification/alertStream?format=json` with a valid session cookie while the panel is **disarmed**.
2. Trigger a PIR / door contact; capture whether any event arrives and its `eventType` / CID code.
3. Repeat while **armed**; compare payloads.
4. Inspect `/ISAPI/Event/notification/httpHosts/capabilities` and `subscribeEventCap` on a live panel.
5. Only if disarmed motion events are reliable: implement an optional background listener that updates coordinator zone state (keeping polling as fallback).

## Product decision

Do **not** ship alertStream yet:

- Incomplete event taxonomy for AX Pro
- Risk of panel instability (same class of load issues as aggressive polling)
- Arm/disarm events alone do not solve the main automation use case in #143

Keep using configurable scan interval; prefer `exDevStatus` + zone status polling for entity updates.
