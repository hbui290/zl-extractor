import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "fetch_zalo_media.mjs"), "utf8");

assert.match(source, /MEDIA_CANDIDATES_PATH/, "generic media must consume the snapshot");
assert.match(source, /MEDIA_CANDIDATES_PATH must be outside OUTPUT_ROOT/, "candidate file must stay temporary");
assert.match(source, /attachments\/images/, "images must have a readable folder");
assert.match(source, /attachments\/videos/, "videos must have a readable folder");
assert.match(source, /attachments\/audio/, "audio must have a readable folder");
assert.match(source, /attachments\/files/, "files must have a readable folder");
assert.match(source, /raw.*attachments\.csv/, "media metadata must be exported");
assert.match(source, /skipped_by_policy/, "GIF/sticker policy must be explicit");
assert.match(source, /sha256/, "downloaded media must be hashed");
assert.match(source, /loadMediaCandidates/, "media must reuse candidates");
assert.doesNotMatch(source, /loadMessagesForBackup/, "media must not rescan message history");
assert.match(source, /AbortSignal\.timeout/, "media requests need a deadline");
assert.match(source, /mediaConcurrency/, "media concurrency must be bounded");

console.log("media_contracts=PASS");
