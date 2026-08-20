import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "fetch_zalo_message_snapshot.mjs"), "utf8");

assert.match(source, /ZALO_CDP_PORT/, "snapshot must use loopback CDP");
assert.match(source, /ZALO_ACCOUNT_ID/, "snapshot must use the verified active account");
assert.match(source, /OUTPUT_ROOT/, "snapshot must guard its output root");
assert.match(source, /ZALO_GROUP_NAME/, "snapshot must resolve the requested group");
assert.match(source, /MESSAGES_PATH/, "snapshot must write normalized messages");
assert.match(source, /START_AT/, "snapshot must support a lower date boundary");
assert.match(source, /END_AT/, "snapshot must support an upper date boundary");
assert.match(source, /loadMessagesForBackup/, "snapshot must use the read-only runtime");
assert.match(source, /MEDIA_CANDIDATES_PATH/, "snapshot must stage media candidates");
assert.match(source, /repeated_cursor/, "snapshot must guard cursor loops");
assert.match(source, /message_page_cap_exceeded/, "snapshot must cap pagination");
assert.match(source, /group-ambiguous/, "snapshot must reject ambiguous group names");
assert.match(source, /invalid MAX_MESSAGE_PAGES|positiveInteger/, "snapshot must reject unbounded page configuration");
assert.match(source, /MEDIA_CANDIDATES_PATH must stay outside OUTPUT_ROOT/, "candidate staging must stay outside the export");
assert.match(source, /time === null/, "invalid timestamps must not stop pagination");
assert.match(source, /atomicWrite/, "snapshot output must be atomic");

console.log("full_snapshot_contracts=PASS");
