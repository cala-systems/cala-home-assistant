# Cala local API specifications

Machine-readable descriptions of the interface between a Cala heat pump
water heater and a local controller such as this integration.

| File | Format | Covers |
|---|---|---|
| [`asyncapi.yaml`](asyncapi.yaml) | [AsyncAPI 3.0](https://www.asyncapi.com/docs/reference/specification/v3.0.0) | The MQTT contract: `state` telemetry, `command` / `command/response`, `context`, `availability` |
| [`pairing.openapi.yaml`](pairing.openapi.yaml) | [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0) | The one-shot HTTP `POST /pair` provisioning endpoint and its encryption scheme |

## Status

These documents were reverse-engineered from this integration (v0.4.0) and
checked against live broker traffic from a heater on firmware v8.4.1. They
are accurate as to *message shapes*; where the *meaning* of a field or a
firmware behaviour could not be determined from the client side, the text
says `UNCONFIRMED`. Those markers are the to-do list for Cala engineers —
grep for them.

## Viewing

* AsyncAPI: paste `asyncapi.yaml` into [AsyncAPI Studio](https://studio.asyncapi.com/)
  or run `npx @asyncapi/cli validate docs/api/asyncapi.yaml`.
* OpenAPI: run `npx @redocly/cli lint docs/api/pairing.openapi.yaml`, or
  render it with `npx @redocly/cli preview-docs docs/api/pairing.openapi.yaml`.

## Keeping them current

When a firmware or integration change adds, renames or removes a topic or
payload field, update the matching schema here in the same PR. The
AsyncAPI document is written from the heater's point of view (`send` =
heater publishes, `receive` = heater subscribes).
