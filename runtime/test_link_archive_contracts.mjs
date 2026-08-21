import assert from "node:assert/strict";
import fs from "node:fs";

let normalizeLinkArchiveItems;
try {
  ({ normalizeLinkArchiveItems } = await import("./link_archive_normalize.mjs"));
} catch {
  // The assertion below is the RED state before the adapter exists.
}

assert.equal(typeof normalizeLinkArchiveItems, "function", "link archive normalizer must exist");

const rows = normalizeLinkArchiveItems([
  { data: { msgId: "m1", userId: "g1", sendDttm: "100", fromUid: "u1", message: {
    title: "Two URLs https://a.example/1 https://b.example/2",
    href: "https://preview.example/ignore",
    thumb: "https://asset.example/ignore.jpg",
  } } },
  { data: { msgId: "m2", userId: "g1", sendDttm: "101", fromUid: "u2", message: {
    title: "No URL in this title",
    href: "https://fallback.example/item",
  } } },
  { data: { title: "date header" } },
  { data: { msgId: "wrong", userId: "another-group", message: { title: "https://wrong.example" } } },
], "g1");

assert.deepEqual(rows, [
  { archive_index: "1", message_id: "m1", timestamp: "100", sender_id: "u1", title: "Two URLs https://a.example/1 https://b.example/2", url: "https://preview.example/ignore", source: "link_archive" },
  { archive_index: "2", message_id: "m2", timestamp: "101", sender_id: "u2", title: "No URL in this title", url: "https://fallback.example/item", source: "link_archive" },
]);

const adapter = fs.readFileSync(new URL("./fetch_zalo_link_archive.mjs", import.meta.url), "utf8");
assert.match(adapter, /archivePath, path\.join\(outputRoot, "source", "raw"\), "LINK_ARCHIVE_PATH"/, "archive rows must stay under source/raw/");
assert.match(adapter, /auditPath, path\.join\(outputRoot, "source"\), "LINK_ARCHIVE_AUDIT_PATH"/, "archive audit must stay under source/");
assert.match(adapter, /stable < 4/, "archive enumeration must reach a stable UI end");
assert.match(adapter, /rawCardCount/, "archive enumeration must reject duplicate or foreign cards");
assert.match(adapter, /link-archive-scroll-container-not-found/, "archive enumeration must not claim a stable end without its scroll container");
assert.match(adapter, /conversation does not match manifest/, "archive enumeration must preserve export conversation identity");
assert.match(adapter, /isSymbolicLink/, "archive outputs must reject symlink escape paths");
assert.match(adapter, /reportedCardCount === ""/, "archive adapter must preserve an explicit zero card count");

console.log("link_archive_contracts=PASS");
