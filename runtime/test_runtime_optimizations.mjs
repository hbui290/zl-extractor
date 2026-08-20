import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const media = fs.readFileSync(path.join(here, "fetch_zalo_photo_media_for_ocr.mjs"), "utf8");
const delta = fs.readFileSync(path.join(here, "fetch_zalo_message_delta.mjs"), "utf8");
const ocr = fs.readFileSync(path.join(here, "ocr_zalo_media.swift"), "utf8");
const { loadMediaCandidates } = await import("./media_candidates.mjs");

assert.match(media, /createWriteStream\(/, "media manifest writes should use a stream");
assert.doesNotMatch(media, /appendFileSync\(manifestPath/, "media workers must not block on sync manifest append");
assert.doesNotMatch(media, /tempManifestPath/, "media manifest should not be rewritten after every run");
assert.match(media, /MEDIA_PROGRESS_MS/, "media progress should be throttled");
assert.match(media, /MEDIA_CANDIDATES_PATH/, "media fetch should accept the shared candidate snapshot");
assert.match(media, /loadMediaCandidates/, "media fetch should load candidates without rescanning messages");
assert.match(media, /candidateSource/, "media fetch should report the candidate source");
assert.match(media, /missing MEDIA_CANDIDATES_PATH/, "media fetch must require the shared candidate snapshot");
assert.doesNotMatch(media, /loadMessagesForBackup/, "media fetch must not rescan message history");
assert.match(media, /MEDIA_CANDIDATES_PATH must be outside OUTPUT_ROOT/, "candidate staging must stay out of final output");
assert.match(media, /missing ZALO_GROUP_NAME/, "media fetch must not silently default to another group");
assert.match(media, /missing OUTPUT_ROOT/, "media fetch must not write to a host-specific default");
assert.match(delta, /INCREMENTAL_STATE_PATH/, "delta fetch must consume the saved state");
assert.match(delta, /MESSAGES_DELTA_PATH/, "delta fetch must write a normalized delta");
assert.match(delta, /loadMessagesForBackup/, "delta fetch must use the logged-in runtime");
assert.match(delta, /watermark/, "delta fetch must stop at the saved watermark");
assert.match(delta, /reachedWatermark/, "delta fetch should detect the watermark while reading the current batch");
assert.doesNotMatch(delta, /rows\.some\(/, "delta fetch must not rescan all accumulated rows after every page");
assert.match(delta, /repeated_cursor/, "delta fetch must guard cursor loops");
assert.match(delta, /completed/, "delta fetch must accept a short final page");
assert.match(delta, /quote_text/, "delta fetch must preserve quote context");
assert.match(delta, /attachment_name/, "delta fetch must preserve attachment metadata");

const candidateDir = fs.mkdtempSync(path.join(os.tmpdir(), "zl-candidates-"));
const candidatePath = path.join(candidateDir, "media-candidates.jsonl");
fs.writeFileSync(candidatePath, `${JSON.stringify({
  msgId: "m1",
  sendDttm: 123,
  url: "https://photo-stal-1.zdn.vn/image.jpg?token=temporary",
  urlKey: "oriUrl",
})}\n`);
const candidates = loadMediaCandidates(candidatePath);
assert.equal(candidates.source, "snapshot");
assert.equal(candidates.rows.length, 1);
assert.equal(candidates.rows[0].msgId, "m1");
const externalCandidatePath = path.join(candidateDir, "external.jsonl");
fs.writeFileSync(externalCandidatePath, `${JSON.stringify({
  msgId: "m-external",
  url: "https://cdn.example.test/image.jpg",
  urlKey: "oriUrl",
})}\n`);
assert.throws(
  () => loadMediaCandidates(externalCandidatePath),
  /unsupported media host/,
);
assert.throws(
  () => loadMediaCandidates(path.join(candidateDir, "missing.jsonl")),
  /media candidate snapshot not found/,
);
const invalidCandidatePath = path.join(candidateDir, "invalid.jsonl");
fs.writeFileSync(invalidCandidatePath, `${JSON.stringify({
  msgId: "m2",
  url: "https://photo-stal-1.zdn.vn/image.jpg",
  urlKey: "arbitraryField",
})}\n`);
assert.throws(
  () => loadMediaCandidates(invalidCandidatePath),
  /invalid media candidate urlKey/,
);

assert.match(ocr, /CryptoKit/, "OCR cache needs a content hash");
assert.match(ocr, /content_sha256/, "OCR output should record the content hash");
assert.match(ocr, /OCR_WORKERS/, "OCR should allow bounded concurrency");
assert.match(ocr, /OCR_RECOGNITION_LEVEL/, "OCR quality must be configurable");
assert.doesNotMatch(ocr, /Set\(\["jxl", "jpg", "jpeg", "png", "webp", "gif"\]\)/, "GIFs must not enter the OCR queue");

console.log("runtime_optimization_contracts=PASS");
