import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "zalo_cdp.mjs"), "utf8");

assert.match(source, /json\/list/, "CDP helper must inspect target pages");
assert.match(source, /Đăng nhập/, "CDP helper must recognize the login state");
assert.match(source, /ZALO_READY_TIMEOUT_MS/, "CDP helper must use a bounded readiness timeout");
assert.match(source, /Zalo renderer not ready after/, "CDP helper must fail with an actionable timeout");
assert.match(source, /setTimeout/, "CDP helper must wait between readiness polls");

process.env.ZALO_READY_TIMEOUT_MS = "3000";
const { waitForZaloPage } = await import("./zalo_cdp.mjs");
let calls = 0;
const server = http.createServer((_request, response) => {
  calls += 1;
  const targets = calls === 1
    ? [{ type: "page", title: "Zalo - Đăng nhập Zalo" }]
    : [{ type: "page", title: "Zalo", webSocketDebuggerUrl: "ws://127.0.0.1/ready" }];
  response.setHeader("content-type", "application/json");
  response.end(JSON.stringify(targets));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const page = await waitForZaloPage(port);
server.close();
assert.equal(page.title, "Zalo");
assert.ok(calls >= 2, "CDP helper must wait past the login/loading state");

console.log("zalo_cdp_contracts=PASS");
