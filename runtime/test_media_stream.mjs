import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

let mediaStream;
try {
  mediaStream = await import("./media_stream.mjs");
} catch {
  // The assertions below are the RED state before streaming support exists.
}
assert.ok(mediaStream, "media stream helper must exist");

const payload = Buffer.alloc(1024 * 1024 + 17, 0xab);
const server = http.createServer((_request, response) => {
  response.writeHead(200, { "content-type": "application/octet-stream", "content-length": payload.length });
  response.end(payload);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "zl-media-stream-"));
const target = path.join(tempDir, "payload.part");
try {
  const response = await fetch(`http://127.0.0.1:${server.address().port}/payload`);
  const result = await mediaStream.streamResponseToFile(response, target);
  assert.equal(result.size, payload.length);
  assert.deepEqual(result.head, payload.subarray(0, 16));
  assert.equal(result.sha256, crypto.createHash("sha256").update(payload).digest("hex"));
  assert.deepEqual(fs.readFileSync(target), payload);
} finally {
  server.close();
  fs.rmSync(tempDir, { recursive: true, force: true });
}

console.log("media_stream_tests=PASS");
