import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

process.env.TZ = "Asia/Ho_Chi_Minh";
const { evaluatePinAudit, pinWindowStatus } = await import("./pin_audit_policy.mjs");

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "fetch_zalo_pins.mjs"), "utf8");
const policy = fs.readFileSync(path.join(here, "pin_audit_policy.mjs"), "utf8");

assert.match(source, /ZALO_CDP_PORT/, "pin adapter must use loopback CDP");
assert.match(source, /ZALO_GROUP_NAME/, "pin adapter must resolve the requested group");
assert.doesNotMatch(source, /START_AT/, "pin audit must not inherit the message date boundary");
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
assert.match(policy, /missing_pin_end_signal/, "pin policy must not claim completeness without an end signal");
assert.match(source, /reportedPinCount/, "pin audit must preserve a reported pin total when available");
assert.match(policy, /uiCount !== null && uiCount === rows/, "pin audit must require an exact UI total");
assert.match(source, /uiReportedPinCount/, "pin audit may reconcile against the exact open conversation's visible pin total");
assert.match(source, /evaluatePinAudit/, "pin audit must use the conservative completeness policy");
assert.match(source, /visibleConversationMatches/, "visible pin count must be bound to the exact open conversation");
assert.match(source, /collectText/, "pin reader must not serialize nested message objects as [object Object]");

assert.deepEqual(
  evaluatePinAudit({ rowCount: 3, reportedPinCount: 3, uiReportedPinCount: null, explicitNoMore: false }),
  { complete: false, endCondition: "missing_pin_end_signal" },
  "API row count alone must not prove the UI pin panel is complete",
);
assert.deepEqual(
  evaluatePinAudit({ rowCount: 4, reportedPinCount: 3, uiReportedPinCount: 4, explicitNoMore: false }),
  { complete: true, endCondition: "ui_pin_total_match" },
  "an exact UI pin total must prove the pin panel",
);
assert.deepEqual(
  evaluatePinAudit({ rowCount: -1, uiReportedPinCount: -1, explicitNoMore: true }),
  { complete: false, endCondition: "missing_pin_end_signal" },
  "invalid negative counts must never prove pin completeness",
);
assert.deepEqual(
  evaluatePinAudit({ rowCount: 3, reportedPinCount: 3, uiReportedPinCount: 4, explicitNoMore: true }),
  { complete: false, endCondition: "ui_pin_count_mismatch" },
  "a UI count mismatch must remain incomplete even when the API says there are no more pages",
);
assert.equal(
  pinWindowStatus("2026-07-14", "2026-07-16"),
  "pin_outside_message_window",
  "an older pinned record must remain visible as out-of-window provenance",
);
assert.equal(
  pinWindowStatus("2026-07-18", "2026-07-16"),
  "pin_in_message_window",
  "a pinned record inside the message window must be marked in-window",
);
assert.equal(
  pinWindowStatus(new Date(2026, 6, 16, 0, 0).getTime(), "2026-07-16"),
  "pin_in_message_window",
  "date-only boundaries must use the same local-midnight rule as message snapshots",
);
assert.match(source, /message_scope/, "pin rows must preserve independent message-window provenance");

console.log("pin_contracts=PASS");
