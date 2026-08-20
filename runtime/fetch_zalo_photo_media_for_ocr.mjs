import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { loadMediaCandidates } from "./media_candidates.mjs";
import { waitForZaloPage } from "./zalo_cdp.mjs";

const port = Number(process.env.ZALO_CDP_PORT || 0);
const outputRootValue = String(process.env.OUTPUT_ROOT || "").trim();
if (!outputRootValue) throw new Error("missing OUTPUT_ROOT");
const outputRoot = path.resolve(outputRootValue);
const groupNameValue = String(process.env.ZALO_GROUP_NAME || "").trim();
if (!groupNameValue) throw new Error("missing ZALO_GROUP_NAME");
const groupName = groupNameValue.normalize("NFC").toLocaleLowerCase();
const mediaConcurrency = Math.max(1, Number(process.env.MEDIA_CONCURRENCY || 4));
const mediaTimeoutMs = Math.max(1000, Number(process.env.MEDIA_TIMEOUT_MS || 30000));
const mediaProgressMs = Math.max(1000, Number(process.env.MEDIA_PROGRESS_MS || 10000));
const mediaProgressItems = Math.max(1, Number(process.env.MEDIA_PROGRESS_ITEMS || 25));
if (!port) throw new Error("missing ZALO_CDP_PORT");
fs.mkdirSync(outputRoot, { recursive: true });
const mediaCandidatesPath = process.env.MEDIA_CANDIDATES_PATH ? path.resolve(process.env.MEDIA_CANDIDATES_PATH) : "";
if (mediaCandidatesPath) {
  const relative = path.relative(outputRoot, mediaCandidatesPath);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new Error("MEDIA_CANDIDATES_PATH must be outside OUTPUT_ROOT");
  }
}
if (!mediaCandidatesPath) {
  throw new Error("missing MEDIA_CANDIDATES_PATH; run the message snapshot first");
}
const data = loadMediaCandidates(mediaCandidatesPath);

const page = await waitForZaloPage(port);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let requestId = 0;
const pending = new Map();
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  const resolve = pending.get(message.id);
  if (resolve) { pending.delete(message.id); resolve(message); }
};
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const command = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++requestId;
  pending.set(id, (message) => message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message));
  ws.send(JSON.stringify({ id, method, params }));
});
const cookieByHost = new Map();
await command("Network.enable");
for (const url of [...new Set((data?.rows || []).map((row) => row.url))]) {
  try {
    const host = new URL(url).host;
    if (cookieByHost.has(host)) continue;
    const cookies = (await command("Network.getCookies", { urls: [url] })).result?.cookies || [];
    cookieByHost.set(host, cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join("; "));
  } catch {
    cookieByHost.set(new URL(url).host, "");
  }
}
ws.close();

const imageExt = new Map([["image/jpeg", ".jpg"], ["image/png", ".png"], ["image/webp", ".webp"], ["image/gif", ".gif"], ["image/jxl", ".jxl"], ["image/avif", ".avif"]]);
const magicExt = (buffer) => {
  const head = buffer.subarray(0, 12);
  if (head[0] === 0xff && head[1] === 0xd8) return ".jpg";
  if (head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47) return ".png";
  if (head.toString("ascii", 0, 4) === "GIF8") return ".gif";
  if (head.toString("ascii", 4, 8) === "ftyp") return ".avif";
  if (head[0] === 0xff && head[1] === 0x0a) return ".jxl";
  return "";
};
const urlHash = (url) => crypto.createHash("sha256").update(url).digest("hex").slice(0, 20);
const hostOf = (url) => { try { return new URL(url).host; } catch { return "invalid"; } };
const manifestPath = path.join(outputRoot, "download_manifest.jsonl");
const previous = new Map();
if (fs.existsSync(manifestPath)) {
  for (const line of fs.readFileSync(manifestPath, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      if (row.media_hash) previous.set(row.media_hash, row);
    } catch {
      // Ignore a truncated final checkpoint; the next run will replace it.
    }
  }
}
const unique = new Map();
for (const row of data.rows || []) {
  const existing = unique.get(row.url);
  if (existing) {
    existing.message_ids = [...new Set([...existing.message_ids, row.msgId].filter(Boolean))];
  } else {
    unique.set(row.url, { ...row, message_ids: row.msgId ? [row.msgId] : [] });
  }
}
const urls = [...unique.entries()];
const results = new Array(urls.length);
const manifestStream = fs.createWriteStream(manifestPath, { flags: "a", encoding: "utf8" });
let manifestStreamError = null;
manifestStream.on("error", (error) => { manifestStreamError = error; });
let manifestWriteChain = Promise.resolve();
const appendManifest = (row) => {
  manifestWriteChain = manifestWriteChain.then(() => new Promise((resolve, reject) => {
    if (manifestStreamError) {
      reject(manifestStreamError);
      return;
    }
    const onError = (error) => {
      manifestStream.off("error", onError);
      reject(error);
    };
    manifestStream.once("error", onError);
    manifestStream.write(`${JSON.stringify(row)}\n`, "utf8", () => {
      manifestStream.off("error", onError);
      resolve();
    });
  }));
  return manifestWriteChain;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const retryable = (error) => {
  const status = Number(error?.status || 0);
  return !status || status === 429 || status >= 500;
};
const fetchImage = async (url) => {
  let lastError;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const response = await fetch(url, {
        headers: {
          Accept: "image/*,*/*;q=0.8",
          "User-Agent": "Mozilla/5.0",
          ...(cookieByHost.get(new URL(url).host) ? { Cookie: cookieByHost.get(new URL(url).host) } : {}),
        },
        signal: AbortSignal.timeout(mediaTimeoutMs),
      });
      if (!response.ok) {
        const error = new Error(`http_${response.status}`);
        error.status = response.status;
        throw error;
      }
      return response;
    } catch (error) {
      lastError = error;
      if (attempt === 2 || !retryable(error)) break;
      await sleep(250 * attempt);
    }
  }
  throw lastError;
};
const looksLikeGif = (url) => {
  try { return new URL(url).pathname.toLowerCase().endsWith(".gif"); } catch { return false; }
};
const downloadOne = async ([url, row]) => {
  const media_hash = urlHash(url);
  const base = {
    media_hash,
    source_host: hostOf(url),
    url_key: row.urlKey,
    msg_id: row.msgId,
    message_ids: row.message_ids,
    sent_ms: row.sendDttm,
    status: "network_error",
    output_file: "",
    bytes: 0,
    sha256: "",
    error: "",
  };
  if (looksLikeGif(url)) return { ...base, status: "skipped_by_policy", error: "GIF excluded by policy" };
  const prior = previous.get(media_hash);
  if (prior?.status === "skipped_by_policy") return { ...prior, message_ids: row.message_ids };
  if (prior?.status === "downloaded" && prior.output_file) {
    const priorPath = path.join(outputRoot, prior.output_file);
    if (fs.existsSync(priorPath) && fs.statSync(priorPath).size > 0) return { ...prior, message_ids: row.message_ids };
  }
  try {
    const response = await fetchImage(url);
    const buffer = Buffer.from(await response.arrayBuffer());
    const mime = String(response.headers.get("content-type") || "").split(";", 1)[0].toLowerCase();
    const ext = imageExt.get(mime) || magicExt(buffer);
    if (ext === ".gif") return { ...base, status: "skipped_by_policy", error: "GIF excluded by policy" };
    if (!ext) return { ...base, status: "unreadable", error: `not_image_${mime || "unknown"}` };
    const sha256 = crypto.createHash("sha256").update(buffer).digest("hex");
    const name = `${row.msgId || "media"}-${media_hash}${ext}`;
    const outputPath = path.join(outputRoot, name);
    if (!fs.existsSync(outputPath)) fs.writeFileSync(outputPath, buffer, { flag: "wx" });
    return { ...base, status: "downloaded", output_file: name, bytes: buffer.length, sha256 };
  } catch (error) {
    const status = Number(error?.status || 0);
    const category = status === 404 ? "failed_404" : status >= 500 ? "failed_500" : (String(error?.message || "").startsWith("not_image") ? "unreadable" : "network_error");
    return { ...base, status: category, error: String(error?.message || error).slice(0, 160) };
  }
};
let next = 0;
let done = 0;
let lastProgressAt = 0;
let lastProgressDone = 0;
const worker = async () => {
  while (true) {
    const index = next++;
    if (index >= urls.length) return;
    const result = await downloadOne(urls[index]);
    results[index] = result;
    await appendManifest(result);
    done++;
    const now = Date.now();
    if (
      done === urls.length
      || done - lastProgressDone >= mediaProgressItems
      || now - lastProgressAt >= mediaProgressMs
    ) {
      console.error(`media ${done}/${urls.length}`);
      lastProgressAt = now;
      lastProgressDone = done;
    }
  }
};
await Promise.all(Array.from({ length: Math.min(mediaConcurrency, urls.length) }, worker));
await manifestWriteChain;
await new Promise((resolve, reject) => {
  if (manifestStreamError) {
    reject(manifestStreamError);
    return;
  }
  manifestStream.once("error", reject);
  manifestStream.end(resolve);
});
const manifest = results.filter(Boolean);
const status = Object.fromEntries([...new Set(manifest.map((row) => row.status))].map((key) => [key, manifest.filter((row) => row.status === key).length]));
console.log(JSON.stringify({ groupName, candidateSource: data.source || "runtime", photoRows: data.rows?.length || 0, uniqueUrls: urls.length, status, mediaConcurrency, mediaTimeoutMs, outputRoot, manifestPath }, null, 2));
