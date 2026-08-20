import fs from "node:fs";
import path from "node:path";
import { isAllowedMediaUrl } from "./media_candidates.mjs";
import { waitForZaloPage } from "./zalo_cdp.mjs";

const required = (name) => {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`missing ${name}`);
  return value;
};

const port = Number(required("ZALO_CDP_PORT"));
if (!Number.isInteger(port) || port <= 0) throw new Error("invalid ZALO_CDP_PORT");
const outputRoot = path.resolve(required("OUTPUT_ROOT"));
const requestedGroupName = required("ZALO_GROUP_NAME").normalize("NFC");
const groupName = requestedGroupName.toLocaleLowerCase();
const accountId = required("ZALO_ACCOUNT_ID");
const messagesPath = path.resolve(required("MESSAGES_PATH"));
const candidatePath = process.env.MEDIA_CANDIDATES_PATH
  ? path.resolve(process.env.MEDIA_CANDIDATES_PATH)
  : "";
const positiveInteger = (name, fallback, maximum) => {
  const raw = String(process.env[name] || "").trim();
  if (!raw) return fallback;
  const number = Number(raw);
  if (!Number.isSafeInteger(number) || number < 1 || number > maximum) throw new Error(`invalid ${name}`);
  return number;
};
const batchSize = positiveInteger("MESSAGE_BATCH_SIZE", 9000, 9000);
const maxPages = positiveInteger("MAX_MESSAGE_PAGES", 100, 1000);
const initialCursor = String(process.env.ZALO_START_CURSOR || "9999999999999");

const rawRelativeMessages = path.relative(path.join(outputRoot, "raw"), messagesPath);
if (rawRelativeMessages === "" || rawRelativeMessages.startsWith("..") || path.isAbsolute(rawRelativeMessages)) {
  throw new Error("MESSAGES_PATH must stay under OUTPUT_ROOT/raw");
}
if (candidatePath) {
  const relativeCandidate = path.relative(outputRoot, candidatePath);
  if (relativeCandidate === "" || (!relativeCandidate.startsWith("..") && !path.isAbsolute(relativeCandidate))) {
    throw new Error("MEDIA_CANDIDATES_PATH must stay outside OUTPUT_ROOT");
  }
  if (candidatePath === messagesPath) throw new Error("MEDIA_CANDIDATES_PATH must differ from MESSAGES_PATH");
}

const parseBoundary = (name) => {
  const value = String(process.env[name] || "").trim();
  if (!value) return null;
  const number = Number(value);
  if (Number.isFinite(number)) return Math.abs(number) < 100_000_000_000 ? number * 1000 : number;
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const dateValue = dateOnly
    ? `${value}T${name === "END_AT" ? "23:59:59.999" : "00:00:00"}`
    : value;
  const parsed = Date.parse(dateValue);
  if (!Number.isFinite(parsed)) throw new Error(`invalid ${name}; use ISO-8601, YYYY-MM-DD, or epoch milliseconds`);
  return parsed;
};
const startAt = parseBoundary("START_AT");
const endAt = parseBoundary("END_AT");
if (startAt !== null && endAt !== null && startAt > endAt) throw new Error("START_AT must be <= END_AT");

const atomicWrite = (filePath, content) => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`);
  try {
    fs.writeFileSync(temporary, content, { encoding: "utf8", flag: "wx" });
    fs.renameSync(temporary, filePath);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
};

const numberValue = (value) => {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const number = Number(text);
  if (Number.isFinite(number)) return Math.abs(number) < 100_000_000_000 ? number * 1000 : number;
  const date = Date.parse(text.replace("Z", "+00:00"));
  return Number.isFinite(date) ? date : null;
};
const compareIds = (left, right) => {
  const a = String(left ?? "");
  const b = String(right ?? "");
  if (/^\d+$/.test(a) && /^\d+$/.test(b)) {
    const leftNumber = BigInt(a);
    const rightNumber = BigInt(b);
    return leftNumber < rightNumber ? -1 : leftNumber > rightNumber ? 1 : 0;
  }
  return a.localeCompare(b);
};
const compareRows = (left, right) => {
  const leftTime = numberValue(left.timestamp);
  const rightTime = numberValue(right.timestamp);
  if (leftTime !== null && rightTime !== null && leftTime !== rightTime) return leftTime < rightTime ? -1 : 1;
  if (leftTime === null && rightTime !== null) return 1;
  if (leftTime !== null && rightTime === null) return -1;
  return compareIds(left.message_id, right.message_id);
};
const inRange = (row) => {
  const time = numberValue(row.timestamp);
  if (time === null) return startAt === null && endAt === null;
  return (startAt === null || time >= startAt) && (endAt === null || time <= endAt);
};

const redactMediaQuery = (value) => String(value || "").replace(/https?:\/\/[^\s<>'"`]+/gi, (token) => {
  const trailing = token.match(/[.,;:!?)]*$/)?.[0] || "";
  const clean = trailing ? token.slice(0, -trailing.length) : token;
  try {
    const parsed = new URL(clean);
    const host = parsed.hostname.toLowerCase();
    const internal = [".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn"].some((suffix) => host.endsWith(suffix))
      && ["stal", "ava-talk", "zpg-r", "photo-link-talk"].some((part) => host.includes(part));
    if (parsed.search && internal) return `${parsed.origin}${parsed.pathname}${trailing}`;
  } catch {
    // Keep ordinary text unchanged.
  }
  return token;
});

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
const evaluate = async (expression) => {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.result?.exceptionDetails) throw new Error(result.result.exceptionDetails.text || "runtime evaluation failed");
  return result.result?.result?.value;
};

let data;
try {
  data = await evaluate(`(async () => {
    const groups = window.webpackJsonp.push([[Math.random()], {}, [['Gm1y']]]).default.getGroupsListSync();
    const matches = groups.filter((group) => String(group.displayName || '').trim().normalize('NFC').toLocaleLowerCase() === ${JSON.stringify(groupName)});
    if (matches.length === 0) return { error: 'group-not-found' };
    if (matches.length > 1) return { error: 'group-ambiguous' };
    const target = matches[0];
    const conversationId = String(target.userId || target.id || '');
    const ExportClass = window.webpackJsonp.push([[Math.random()], {}, [['AY7h']]]).a;
    const access = new ExportClass();
    access.setUserId(${JSON.stringify(accountId)});
    access.setUIN(${JSON.stringify(accountId)});
    const urlKeys = new Set(['oriUrl', 'hdUrl', 'normalUrl', 'thumbUrl', 'url', 'fileUrl', 'downloadUrl']);
    const mediaSuffixes = ['.zdn.vn', '.zadn.vn', '.dlmd.me', '.dlfl.vn'];
    const mediaTokens = ['stal', 'ava-talk', 'zpg-r', 'photo-link-talk'];
    const isMediaUrl = (value) => {
      if (typeof value !== 'string' || !/^https?:\\/\\//i.test(value)) return false;
      try {
        const host = new URL(value).hostname.toLowerCase();
        return mediaSuffixes.some((suffix) => host.endsWith(suffix)) && mediaTokens.some((token) => host.includes(token));
      } catch { return false; }
    };
    const collect = (value, key = '', depth = 0, seen = new WeakSet(), urls = []) => {
      if (depth > 5 || value == null) return urls;
      if (typeof value === 'string') {
        if (urlKeys.has(key) && isMediaUrl(value)) urls.push({ key, url: value });
        return urls;
      }
      if (typeof value !== 'object' || seen.has(value)) return urls;
      seen.add(value);
      for (const [childKey, child] of Object.entries(value)) collect(child, childKey, depth + 1, seen, urls);
      return urls;
    };
    const collectText = (value, depth = 0, seen = new WeakSet()) => {
      if (depth > 3 || value == null) return '';
      if (typeof value === 'string') return value;
      if (typeof value !== 'object' || seen.has(value)) return '';
      seen.add(value);
      const parts = [];
      for (const key of ['text', 'messageText', 'caption', 'description', 'body']) {
        if (typeof value[key] === 'string' && value[key].trim()) parts.push(value[key]);
        else if (value[key] && typeof value[key] === 'object') parts.push(collectText(value[key], depth + 1, seen));
      }
      return parts.filter(Boolean).join('\\n');
    };
    const scalar = (...values) => values.find((value) => value != null && String(value).trim()) ?? '';
    const stringValue = (...values) => values.find((value) => typeof value === 'string' && value.trim()) ?? '';
    const timeValue = (value) => {
      const number = Number(String(value || '').trim());
      if (Number.isFinite(number)) return Math.abs(number) < 100000000000 ? number * 1000 : number;
      const parsed = Date.parse(String(value || '').replace('Z', '+00:00'));
      return Number.isFinite(parsed) ? parsed : null;
    };
    const normalized = (row) => {
      const messageId = String(scalar(row.msgId, row.messageId, row.id));
      if (!messageId) return null;
      const candidateUrls = ${candidatePath ? "collect({ message: row.message, content: row.content, extra: row.extra, ev: row.ev, paramsExt: row.paramsExt, properties: row.properties })" : "[]"};
      const ranked = [...new Map(
        candidateUrls
          .sort((a, b) => ({ hdUrl: 0, oriUrl: 1, normalUrl: 2, thumbUrl: 3 }[a.key] ?? 9) - ({ hdUrl: 0, oriUrl: 1, normalUrl: 2, thumbUrl: 3 }[b.key] ?? 9))
          .map((candidate) => [candidate.url, candidate]),
      ).values()];
      const sender = String(scalar(row.senderName, row.fromName, row.sender?.displayName));
      const senderId = String(scalar(row.senderId, row.fromId, row.sender?.id));
      const attachmentName = stringValue(row.fileName, row.file_name, row.attachmentName, row.attachment?.name, row.file?.name);
      const attachmentMime = stringValue(row.mimeType, row.mime_type, row.contentType, row.attachment?.mimeType, row.file?.mimeType);
      return {
        timestamp: String(scalar(row.sendDttm, row.timestamp, row.sendTime)),
        message_id: messageId,
        conversation_id: conversationId,
        conversation_name: String(target.displayName || ''),
        sender,
        sender_id: senderId,
        msg_type: String(scalar(row.msgType, row.messageType, row.type)),
        origin_msg_type: String(row.originMsgType || ''),
        text: collectText(row.text || row.message || row.content || ''),
        quote_text: stringValue(row.quoteText, row.quote_text, row.quote?.text),
        reference_text: stringValue(row.referenceText, row.reference_text, row.reference?.text),
        attachment_name: attachmentName,
        media: ranked.map((candidate, index) => ({
          msgId: messageId,
          ordinal: index + 1,
          sendDttm: Number(row.sendDttm) || 0,
          url: candidate.url,
          urlKey: candidate.key,
          mediaType: String(scalar(row.msgType, row.messageType, row.type)),
          mime: attachmentMime,
          originalName: attachmentName,
          sender,
          senderId,
        })),
      };
    };
    const startAt = ${startAt === null ? "null" : startAt};
    const endAt = ${endAt === null ? "null" : endAt};
    const inRange = (row) => {
      const time = timeValue(row.timestamp);
      if (time === null) return startAt === null && endAt === null;
      return (startAt === null || time >= startAt) && (endAt === null || time <= endAt);
    };
    const beforeStart = (row) => {
      const time = timeValue(row.timestamp);
      return startAt !== null && time !== null && time < startAt;
    };
    let cursor = ${JSON.stringify(initialCursor)};
    let pages = 0;
    let scannedMessages = 0;
    let stoppedAtStart = false;
    let completed = false;
    const rows = [];
    const media = [];
    const seenCursors = new Set();
    while (pages < ${maxPages}) {
      if (seenCursors.has(cursor)) throw new Error('repeated_cursor:' + cursor);
      seenCursors.add(cursor);
      pages++;
      const batch = await access.DataAccess.loadMessagesForBackup(target.userId, cursor, ${batchSize});
      if (!Array.isArray(batch)) throw new Error('runtime_message_batch_not_array');
      scannedMessages += batch.length;
      for (const item of batch) {
        const row = normalized(item);
        if (!row) continue;
        if (inRange(row)) {
          rows.push(row);
          if (row.media?.length) media.push(...row.media);
        }
        if (beforeStart(row)) stoppedAtStart = true;
      }
      if (stoppedAtStart) break;
      if (batch.length < ${batchSize}) { completed = true; break; }
      const lastId = String(batch.at(-1)?.msgId ?? batch.at(-1)?.messageId ?? batch.at(-1)?.id ?? '');
      if (!/^\\d+$/.test(lastId) || lastId === cursor) throw new Error('invalid_next_cursor:' + lastId);
      cursor = lastId;
    }
    if (pages >= ${maxPages} && !stoppedAtStart && !completed) throw new Error('message_page_cap_exceeded:' + ${maxPages});
    return { conversationId, rows, media, pages, scannedMessages, stoppedAtStart, completed };
  })()`);
} finally {
  ws.close();
}
if (data?.error) throw new Error(data.error);

const normalizedRows = (data.rows || []).map((row) => ({
  timestamp: String(row.timestamp || ""),
  message_id: String(row.message_id || ""),
  conversation_id: String(row.conversation_id || ""),
  conversation_name: redactMediaQuery(row.conversation_name),
  sender: redactMediaQuery(row.sender),
  sender_id: String(row.sender_id || ""),
  msg_type: String(row.msg_type || ""),
  origin_msg_type: String(row.origin_msg_type || ""),
  text: redactMediaQuery(row.text),
  quote_text: redactMediaQuery(row.quote_text),
  reference_text: redactMediaQuery(row.reference_text),
  attachment_name: redactMediaQuery(row.attachment_name),
})).filter((row) => row.message_id && inRange(row));
const uniqueRows = new Map();
for (const row of normalizedRows) if (!uniqueRows.has(row.message_id)) uniqueRows.set(row.message_id, row);
const rows = [...uniqueRows.values()].sort(compareRows);
const csvFields = ["timestamp", "message_id", "conversation_id", "conversation_name", "sender", "sender_id", "msg_type", "origin_msg_type", "text", "quote_text", "reference_text", "attachment_name"];
const csvEscape = (value) => {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const csv = [csvFields.join(","), ...rows.map((row) => csvFields.map((field) => csvEscape(row[field])).join(","))].join("\n") + "\n";
atomicWrite(messagesPath, csv);

const exportedMessageIds = new Set(rows.map((row) => row.message_id));
if (candidatePath) {
  const candidates = (data.media || []).filter((row) => exportedMessageIds.has(String(row.msgId)) && isAllowedMediaUrl(row.url));
  const jsonl = candidates.map((row) => JSON.stringify(row)).join("\n");
  atomicWrite(candidatePath, jsonl ? `${jsonl}\n` : "");
}

const mediaCandidateCount = candidatePath
  ? (data.media || []).filter((row) => exportedMessageIds.has(String(row.msgId)) && isAllowedMediaUrl(row.url)).length
  : 0;

const manifestPath = path.join(outputRoot, "source", "manifest.json");
let manifest = {};
if (fs.existsSync(manifestPath)) {
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`invalid manifest: ${error.message}`);
  }
}
if (manifest.sourceWriteIssued === true) throw new Error("source_write_guard: manifest says sourceWriteIssued=true");
manifest.schema_version = manifest.schema_version || 1;
manifest.exportStatus = manifest.exportStatus || "PARTIAL";
manifest.sourceWriteIssued = false;
manifest.source = {
  ...(manifest.source || {}),
  kind: "zalo_logged_in_runtime",
  readOnly: true,
  accountId,
  conversationId: String(data.conversationId || ""),
  conversationName: requestedGroupName,
  startAt: process.env.START_AT || "",
  endAt: process.env.END_AT || "",
};
manifest.counts = {
  ...(manifest.counts || {}),
  snapshotRecords: rows.length,
  exportedMessages: rows.length,
};
atomicWrite(manifestPath, JSON.stringify(manifest, null, 2) + "\n");

console.log(JSON.stringify({
  groupName: requestedGroupName,
  conversationId: data.conversationId,
  pages: data.pages,
  scannedMessages: data.scannedMessages,
  exportedMessages: rows.length,
  mediaCandidates: mediaCandidateCount,
  stoppedAtStart: Boolean(data.stoppedAtStart),
  completed: Boolean(data.completed),
}, null, 2));
