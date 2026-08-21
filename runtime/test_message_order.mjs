import assert from "node:assert/strict";

let messageOrder;
try {
  messageOrder = await import("./message_order.mjs");
} catch {
  // The assertions below are the RED state before the shared helper exists.
}

assert.ok(messageOrder, "message ordering helper must exist");
const { compareMessageRows, compareMessageIds, timestampValue } = messageOrder;
assert.equal(timestampValue("1700000000000"), timestampValue("2023-11-14T22:13:20Z"));
assert.equal(timestampValue("1700000000"), timestampValue("2023-11-14T22:13:20Z"));
assert.ok(timestampValue("2027-01-15T08:00:00Z") > timestampValue("1700000000000"));
assert.ok(compareMessageIds("10", "9") > 0);
assert.ok(compareMessageRows(
  { timestamp: "2027-01-15T08:00:00Z", message_id: "11" },
  { timestamp: "1700000000000", message_id: "99" },
) > 0);
assert.ok(compareMessageRows(
  { timestamp: "1700000000000", message_id: "10" },
  { timestamp: "1700000000000", message_id: "9" },
) > 0);

console.log("message_order_tests=PASS");
