import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "fetch_zalo_pins.mjs"), "utf8");

assert.match(source, /ZALO_CDP_PORT/, "pin adapter must use loopback CDP");
assert.match(source, /ZALO_GROUP_NAME/, "pin adapter must resolve the requested group");
assert.match(source, /PINS_PATH/, "pin adapter must write normalized pins");
assert.match(source, /PINS_PATH must stay outside OUTPUT_ROOT/, "pin staging must stay outside final output");
assert.match(source, /pin-topic-one-on-one-controller/, "pin controller token must be explicit");
assert.match(source, /pin-topic-data-repository/, "pin repository fallback must be explicit");
assert.match(source, /loadPinTopics/, "pin adapter must use the read-only pin API");
assert.match(source, /group-ambiguous/, "pin adapter must reject ambiguous group names");
assert.match(source, /pin-conversation-mismatch/, "pin adapter must verify the exact conversation");
assert.match(source, /pin_page_cap_exceeded/, "pin adapter must cap rows");
assert.match(source, /atomicWrite/, "pin output must be atomic");
assert.match(source, /waitForZaloPage/, "pin adapter must wait for a ready renderer");
assert.match(source, /pinAuditCompleteness/, "pin adapter must record completeness");
assert.match(source, /bareTlds/, "pin adapter must recognize conservative bare domains");
assert.match(source, /depth > 8/, "pin adapter must inspect nested pin payloads");
assert.match(source, /topic.data/, "pin adapter must inspect the topic payload");
assert.match(source, /missing_pin_end_signal/, "pin adapter must not claim completeness without an end signal");
assert.match(source, /reportedPinCount/, "pin audit must preserve a reported pin total when available");
assert.match(source, /reportedPinCount\s*===\s*rows\.length/, "pin audit must require an exact reported total");
assert.match(source, /collectText/, "pin reader must not serialize nested message objects as [object Object]");

console.log("pin_contracts=PASS");
