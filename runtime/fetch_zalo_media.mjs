import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { loadMediaCandidates } from "./media_candidates.mjs";
import { sha256File, streamResponseToFile } from "./media_stream.mjs";
import { waitForZaloPage } from "./zalo_cdp.mjs";

const required = (name) => {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`missing ${name}`);
  return value;
};

const port = Number(required("ZALO_CDP_PORT"));
if (!Number.isInteger(port) || port <= 0) throw new Error("invalid ZALO_CDP_PORT");
const outputRoot = path.resolve(required("OUTPUT_ROOT"));
const groupName = required("ZALO_GROUP_NAME");
const candidatesPath = path.resolve(required("MEDIA_CANDIDATES_PATH"));
const candidateRelative = path.relative(outputRoot, candidatesPath);
if (candidateRelative === "" || (!candidateRelative.startsWith("..") && !path.isAbsolute(candidateRelative))) {
  throw new Error("MEDIA_CANDIDATES_PATH must be outside OUTPUT_ROOT");
}
const concurrencyValue = Number(process.env.MEDIA_CONCURRENCY || 4);
const timeoutValue = Number(process.env.MEDIA_TIMEOUT_MS || 30000);
if (!Number.isSafeInteger(concurrencyValue) || concurrencyValue < 1 || concurrencyValue > 16) throw new Error("invalid MEDIA_CONCURRENCY");
if (!Number.isSafeInteger(timeoutValue) || timeoutValue < 1000 || timeoutValue > 300000) throw new Error("invalid MEDIA_TIMEOUT_MS");
const mediaConcurrency = concurrencyValue;
const mediaTimeoutMs = timeoutValue;
const data = loadMediaCandidates(candidatesPath);
const outputDirectories = {
  image: "source/attachments/images",
  video: "source/attachments/videos",
  audio: "source/attachments/audio",
  file: "source/attachments/files",
  other: "source/attachments/other",
};
for (const directory of Object.values(outputDirectories)) fs.mkdirSync(path.join(outputRoot, directory), { recursive: true });
const temporaryDirectory = path.join(outputRoot, ".media-tmp");
fs.mkdirSync(temporaryDirectory, { recursive: true });

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
for (const url of [...new Set((data.rows || []).map((row) => row.url))]) {
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

const mimeExtensions = new Map([
  ["image/jpeg", ".jpg"], ["image/png", ".png"], ["image/webp", ".webp"], ["image/avif", ".avif"], ["image/jxl", ".jxl"],
  ["video/mp4", ".mp4"], ["video/quicktime", ".mov"], ["video/webm", ".webm"],
  ["audio/mpeg", ".mp3"], ["audio/wav", ".wav"], ["audio/x-wav", ".wav"], ["audio/ogg", ".ogg"], ["audio/flac", ".flac"],
  ["application/pdf", ".pdf"], ["application/zip", ".zip"], ["application/x-7z-compressed", ".7z"], ["application/x-rar-compressed", ".rar"],
  ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"],
  ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"],
  ["application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"],
]);
const magicExtension = (buffer, mime) => {
  const head = buffer.subarray(0, 16);
  if (head[0] === 0xff && head[1] === 0xd8) return ".jpg";
  if (head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47) return ".png";
  if (head.toString("ascii", 0, 4) === "GIF8") return ".gif";
  if (head.toString("ascii", 0, 4) === "RIFF" && head.toString("ascii", 8, 12) === "WEBP") return ".webp";
  if (head.toString("ascii", 4, 8) === "ftyp") return mime === "video/quicktime" ? ".mov" : ".mp4";
  if (head.toString("ascii", 0, 4) === "ID3" || (head[0] === 0xff && (head[1] & 0xe0) === 0xe0)) return ".mp3";
  if (head.toString("ascii", 0, 4) === "RIFF" && head.toString("ascii", 8, 12) === "WAVE") return ".wav";
  if (head.toString("ascii", 0, 4) === "%PDF") return ".pdf";
  if (head[0] === 0x50 && head[1] === 0x4b && (head[2] === 0x03 || head[2] === 0x05 || head[2] === 0x07)) return mimeExtensions.get(mime) || ".zip";
  if (head.toString("ascii", 0, 6) === "Rar!\x1a\x07") return ".rar";
  if (head[0] === 0x37 && head[1] === 0x7a && head[2] === 0xbc && head[3] === 0xaf) return ".7z";
  if (head.toString("ascii", 0, 4) === "OggS") return ".ogg";
  if (head.toString("ascii", 0, 4) === "fLaC") return ".flac";
  return "";
};
const mediaKind = (row, mime, extension) => {
  const hint = `${row.mediaType} ${row.originalName}`.toLowerCase();
  if (hint.includes("sticker") || mime === "image/gif" || extension === ".gif") return "policy_skip";
  if (mime.startsWith("image/") || [".jpg", ".png", ".webp", ".avif", ".jxl"].includes(extension)) return "image";
  if (mime.startsWith("video/") || [".mp4", ".mov", ".webm"].includes(extension)) return "video";
  if (mime.startsWith("audio/") || [".mp3", ".wav", ".ogg", ".flac"].includes(extension)) return "audio";
  return "file";
};
const safeName = (value, fallback) => {
  const name = String(value || "").normalize("NFC").replace(/[^\p{L}\p{N}._-]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 100);
  return name || fallback;
};
const urlHash = (url) => crypto.createHash("sha256").update(url).digest("hex").slice(0, 20);
const hostOf = (url) => { try { return new URL(url).host; } catch { return "invalid"; } };
const csvFields = ["sequence", "message_id", "message_ids", "timestamp", "sender", "type", "original_name", "relative_output_path", "size", "sha256", "source_kind", "source_url_fingerprint", "url_key", "status", "error"];
const csvEscape = (value) => {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const atomicWrite = (filePath, content) => {
  const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporary, content, { encoding: "utf8", flag: "wx" });
  fs.renameSync(temporary, filePath);
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const retryable = (error) => !Number(error?.status) || Number(error.status) === 429 || Number(error.status) >= 500;
const fetchOne = async (url) => {
  let lastError;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const response = await fetch(url, {
        headers: { Accept: "*/*", "User-Agent": "Mozilla/5.0", ...(cookieByHost.get(new URL(url).host) ? { Cookie: cookieByHost.get(new URL(url).host) } : {}) },
        signal: AbortSignal.timeout(mediaTimeoutMs),
      });
      if (!response.ok) { const error = new Error(`http_${response.status}`); error.status = response.status; throw error; }
      return response;
    } catch (error) {
      lastError = error;
      if (attempt === 2 || !retryable(error)) break;
      await sleep(250 * attempt);
    }
  }
  throw lastError;
};
const unique = new Map();
for (const row of data.rows || []) {
  const existing = unique.get(row.url);
  if (existing) {
    existing.messageIds.add(row.msgId);
  } else {
    unique.set(row.url, { ...row, messageIds: new Set([row.msgId].filter(Boolean)) });
  }
}
const results = new Array(unique.size);
const entries = [...unique.entries()];
const downloadOne = async ([url, row], index) => {
  const hash = urlHash(url);
  let temporary = "";
  const mimeHint = String(row.mime || "").split(";", 1)[0].toLowerCase();
  const extensionHint = path.extname(row.originalName || "").toLowerCase();
  const kindHint = mediaKind(row, mimeHint, extensionHint);
  const base = {
    sequence: "",
    message_id: row.msgId || "",
    message_ids: [...row.messageIds].join("|"),
    timestamp: row.sendDttm || "",
    sender: row.sender || "",
    type: row.mediaType || mimeHint || kindHint,
    original_name: row.originalName || "",
    relative_output_path: "",
    size: 0,
    sha256: "",
    source_kind: "zalo_runtime_url",
    source_url_fingerprint: hash,
    url_key: row.urlKey || "",
    status: "network_error",
    error: "",
  };
  if (kindHint === "policy_skip") return { ...base, status: "skipped_by_policy", error: "GIF/sticker excluded by policy" };
  try {
    const response = await fetchOne(url);
    temporary = path.join(temporaryDirectory, `${hash}-${process.pid}-${index}.part`);
    const streamed = await streamResponseToFile(response, temporary);
    const mime = String(response.headers.get("content-type") || mimeHint).split(";", 1)[0].toLowerCase();
    const extension = magicExtension(streamed.head, mime) || mimeExtensions.get(mime) || "";
    if (!extension || extension === ".gif") {
      fs.rmSync(temporary, { force: true });
      temporary = "";
      return { ...base, status: extension === ".gif" ? "skipped_by_policy" : "unreadable", error: extension === ".gif" ? "GIF excluded by policy" : `unknown_binary_${mime || "unknown"}` };
    }
    const kind = mediaKind(row, mime, extension);
    const fileName = `${safeName(row.msgId, "media")}-${String(row.ordinal || index + 1).padStart(2, "0")}-${hash}${extension}`;
    const relative = path.join(outputDirectories[kind] || outputDirectories.other, fileName);
    const target = path.join(outputRoot, relative);
    if (fs.existsSync(target)) {
      const existingHash = await sha256File(target);
      if (existingHash === streamed.sha256) fs.rmSync(temporary, { force: true });
      else fs.renameSync(temporary, target);
    } else {
      fs.renameSync(temporary, target);
    }
    temporary = "";
    return { ...base, type: row.mediaType || mime || kind, relative_output_path: relative, size: streamed.size, sha256: streamed.sha256, status: "downloaded", error: "" };
  } catch (error) {
    if (temporary) fs.rmSync(temporary, { force: true });
    const status = Number(error?.status || 0);
    return { ...base, status: status === 404 ? "failed_404" : status >= 500 ? "failed_500" : "network_error", error: String(error?.message || error).slice(0, 160) };
  }
};
let next = 0;
const worker = async () => {
  while (true) {
    const index = next++;
    if (index >= entries.length) return;
    results[index] = await downloadOne(entries[index], index);
  }
};
await Promise.all(Array.from({ length: Math.min(mediaConcurrency, entries.length) }, worker));
const rows = results.filter(Boolean);
rows.forEach((row, index) => { row.sequence = String(index + 1).padStart(6, "0"); });
const attachmentsPath = path.join(outputRoot, "source", "raw", "attachments.csv");
fs.mkdirSync(path.dirname(attachmentsPath), { recursive: true });
atomicWrite(attachmentsPath, [csvFields.join(","), ...rows.map((row) => csvFields.map((field) => csvEscape(row[field])).join(","))].join("\n") + "\n");
const status = Object.fromEntries([...new Set(rows.map((row) => row.status))].map((key) => [key, rows.filter((row) => row.status === key).length]));
console.log(JSON.stringify({ groupName, candidateSource: data.source || "snapshot", candidateRows: data.rows?.length || 0, uniqueUrls: entries.length, status, mediaConcurrency, mediaTimeoutMs, outputRoot, attachmentsPath }, null, 2));
