import fs from "node:fs";
import path from "node:path";
import { assertBrowserExpression, runtimeExceptionMessage } from "./browser_runtime.mjs";
import { compareMessageRows, timestampValue } from "./message_order.mjs";
import { isAllowedMediaUrl } from "./media_candidates.mjs";
import { waitForZaloPage } from "./zalo_cdp.mjs";

const required = (name) => {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`missing ${name}`);
  return value;
};

const port = Number(required("ZALO_CDP_PORT"));
if (!Number.isInteger(port) || port <= 0) throw new Error("invalid ZALO_CDP_PORT");
const groupName = required("ZALO_GROUP_NAME").normalize("NFC").toLocaleLowerCase();
const accountId = required("ZALO_ACCOUNT_ID");
const statePath = path.resolve(required("INCREMENTAL_STATE_PATH"));
const deltaPath = path.resolve(required("MESSAGES_DELTA_PATH"));
const candidatePath = process.env.MEDIA_CANDIDATES_PATH
  ? path.resolve(process.env.MEDIA_CANDIDATES_PATH)
  : "";
const batchSize = Math.min(9000, Math.max(1, Math.floor(Number(process.env.MESSAGE_BATCH_SIZE || 9000))));
const maxPages = Math.max(1, Math.floor(Number(process.env.MAX_MESSAGE_PAGES || 100)));
const initialCursor = String(process.env.ZALO_START_CURSOR || "9999999999999");

if (!fs.existsSync(statePath)) throw new Error(`incremental state not found: ${statePath}`);
let state;
try {
  state = JSON.parse(fs.readFileSync(statePath, "utf8"));
} catch (error) {
  throw new Error(`invalid incremental state: ${error.message}`);
}
if (!String(state.conversation_id || "").trim()) throw new Error("incremental state has no conversation_id");

const exportRoot = path.dirname(path.dirname(statePath));
const assertOutsideExport = (filePath, label) => {
  const relative = path.relative(exportRoot, filePath);
  if (!relative || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new Error(`${label} must be outside export root`);
  }
};
assertOutsideExport(deltaPath, "MESSAGES_DELTA_PATH");
if (candidatePath) assertOutsideExport(candidatePath, "MEDIA_CANDIDATES_PATH");

const watermark = state.watermark && state.watermark.message_id
  ? { timestamp: state.watermark.timestamp || "", message_id: String(state.watermark.message_id) }
  : null;
const watermarkTime = watermark ? timestampValue(watermark.timestamp) : null;
const isNewer = (row) => !watermark || compareMessageRows(row, watermark) > 0;

const internalSuffixes = [".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn"];
const internalTokens = ["stal", "ava-talk", "zpg-r", "photo-link-talk"];
const redactMediaQuery = (value) => String(value || "").replace(/https?:\/\/[^\s<>'"`]+/gi, (token) => {
  const trailing = token.match(/[.,;:!?)]*$/)?.[0] || "";
  const clean = trailing ? token.slice(0, -trailing.length) : token;
  try {
    const parsed = new URL(clean);
    const host = parsed.hostname.toLowerCase();
    if (parsed.search && internalSuffixes.some((suffix) => host.endsWith(suffix))
      && internalTokens.some((part) => host.includes(part))) {
      return `${parsed.origin}${parsed.pathname}${trailing}`;
    }
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
  assertBrowserExpression(expression);
  const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.result?.exceptionDetails) throw new Error(runtimeExceptionMessage(result.result.exceptionDetails));
  return result.result?.result?.value;
};

let data;
try {
  data = await evaluate(`(async () => {
    const groups = window.webpackJsonp.push([[Math.random()], {}, [['Gm1y']]]).default.getGroupsListSync();
    const target = groups.find((group) => String(group.displayName || '').trim().normalize('NFC').toLocaleLowerCase() === ${JSON.stringify(groupName)});
    if (!target) return { error: 'group-not-found' };
    const conversationId = String(target.userId || target.id || '');
    const ExportClass = window.webpackJsonp.push([[Math.random()], {}, [['AY7h']]]).a;
    const access = new ExportClass();
    access.setUserId(${JSON.stringify(accountId)});
    access.setUIN(${JSON.stringify(accountId)});
    const urlKeys = new Set(['oriUrl', 'hdUrl', 'normalUrl', 'thumbUrl', 'url', 'fileUrl', 'downloadUrl']);
    const collect = (value, key = '', depth = 0, seen = new WeakSet(), urls = []) => {
      if (depth > 5 || value == null) return urls;
      if (typeof value === 'string') {
        if (urlKeys.has(key) && /^https?:\\/\\//i.test(value)) urls.push({ key, url: value });
        return urls;
      }
      if (typeof value !== 'object' || seen.has(value)) return urls;
      seen.add(value);
      for (const [childKey, child] of Object.entries(value)) collect(child, childKey, depth + 1, seen, urls);
      return urls;
    };
    const bareTlds = new Set(['ai', 'app', 'biz', 'cc', 'co', 'com', 'dev', 'digital', 'fun', 'gg', 'io', 'me', 'net', 'online', 'org', 'site', 'tech', 'tv', 'vn', 'xyz']);
    const trimToken = (value) => String(value || '').trim().replace(/[.,;:!?]+$/, '').replace(/[)\]}]+$/, '');
    const isBareUrl = (value) => {
      const text = trimToken(value);
      if (!text || /^https?:\\/\\//i.test(text)) return false;
      const host = text.split(/[/?#]/, 1)[0].toLowerCase().replace(/^www\\./, '');
      const labels = host.split('.');
      return labels.length >= 2 && bareTlds.has(labels.at(-1)) && /[a-z]/i.test(labels[0]);
    };
    const urlsInText = (value) => {
      const urls = [];
      const text = typeof value === 'string' ? value : '';
      const explicit = [];
      for (const match of text.matchAll(/https?:\\/\\/[^\\s<>"'\\x60]+/gi)) {
        const url = trimToken(match[0]);
        if (url) { urls.push(url); explicit.push([match.index, match.index + match[0].length]); }
      }
      for (const match of text.matchAll(/(?<![@\\w])(?:www\\.)?(?:[a-z0-9-]+\\.)+[a-z]{2,}(?:\\/[^\\s<>"'\\x60)\\]]*)?/gi)) {
        const url = trimToken(match[0]);
        if (url && isBareUrl(url) && !explicit.some(([start, end]) => start <= match.index && match.index < end)) urls.push(url);
      }
      return [...new Set(urls)];
    };
    const collectPublicUrls = (value) => {
      if (value == null || typeof value !== 'object') return [];
      const titleUrls = urlsInText(value.title);
      return titleUrls.length ? titleUrls : urlsInText(value.href);
    };
    const collectText = (value, depth = 0, seen = new WeakSet()) => {
      if (depth > 3 || value == null) return '';
      if (typeof value === 'string') return value;
      if (typeof value !== 'object' || seen.has(value)) return '';
      seen.add(value);
      const parts = [];
      for (const key of ['text', 'messageText', 'msg', 'caption', 'description', 'body']) {
        if (typeof value[key] === 'string' && value[key].trim()) parts.push(value[key]);
        else if (value[key] && typeof value[key] === 'object') parts.push(collectText(value[key], depth + 1, seen));
      }
      return parts.filter(Boolean).join('\\n');
    };
    const scalar = (...values) => values.find((value) => value != null && String(value).trim()) ?? '';
    const stringValue = (...values) => values.find((value) => typeof value === 'string' && value.trim()) ?? '';
    const senderNames = new Map((target.topMember || []).filter((member) => member?.id && member?.dName).map((member) => [String(member.id), String(member.dName)]));
    const timeValue = (value) => {
      const number = Number(String(value || '').trim());
      if (Number.isFinite(number)) return Math.abs(number) < 100000000000 ? number * 1000 : number;
      const parsed = Date.parse(String(value || '').replace('Z', '+00:00'));
      return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
    };
    const idAtOrBefore = (left, right) => {
      if (/^\\d+$/.test(left) && /^\\d+$/.test(right)) return BigInt(left) <= BigInt(right);
      return left <= right;
    };
    const normalized = (row) => {
      const messageId = String(scalar(row.msgId, row.messageId, row.id));
      if (!messageId) return null;
      const photoUrls = String(row.originMsgType || '') === 'chat.photo'
        ? collect({ message: row.message, content: row.content, extra: row.extra, ev: row.ev, paramsExt: row.paramsExt, properties: row.properties })
        : [];
      const ranked = photoUrls.sort((a, b) => ({ hdUrl: 0, oriUrl: 1, normalUrl: 2, thumbUrl: 3 }[a.key] ?? 9) - ({ hdUrl: 0, oriUrl: 1, normalUrl: 2, thumbUrl: 3 }[b.key] ?? 9));
      const textParts = [row.text, row.message, row.content].map((value) => collectText(value)).filter(Boolean);
      const text = [...new Set(textParts)].join('\\n');
      const structuredLinks = String(row.originMsgType || '') === 'chat.recommended' ? collectPublicUrls(row.message).filter((url) => {
        try {
          const host = new URL(/^https?:\\/\\//i.test(url) ? url : 'https://' + url).hostname.toLowerCase();
          return !([".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn"].some((suffix) => host.endsWith(suffix))
            && ["stal", "ava-talk", "zpg-r", "photo-link-talk"].some((part) => host.includes(part)));
        } catch { return true; }
      }) : [];
      const senderId = String(scalar(row.fromUid, row.senderId, row.fromId, row.sender?.id));
      const sender = String(scalar(row.dName, row.senderName, row.fromName, row.sender?.displayName));
      if (senderId && sender) senderNames.set(senderId, sender);
      if (row.quote?.ownerId && row.quote?.fromD) senderNames.set(String(row.quote.ownerId), String(row.quote.fromD));
      return {
        timestamp: String(scalar(row.sendDttm, row.timestamp, row.sendTime)),
        message_id: messageId,
        conversation_id: conversationId,
        conversation_name: String(target.displayName || ''),
        sender,
        sender_id: senderId,
        msg_type: String(scalar(row.msgType, row.messageType, row.type)),
        origin_msg_type: String(row.originMsgType || ''),
        text,
        quote_text: collectText(row.quoteText || row.quote_text || row.quote),
        reference_text: collectText(row.referenceText || row.reference_text || row.reference),
        structured_links: structuredLinks.join('\\n'),
        attachment_name: stringValue(row.fileName, row.file_name, row.attachmentName, row.attachment?.name),
        media: ranked[0] ? { msgId: messageId, sendDttm: Number(row.sendDttm) || 0, url: ranked[0].url, urlKey: ranked[0].key } : null,
      };
    };
    const atOrBeforeWatermark = (row) => {
      if (!${watermark ? "true" : "false"}) return false;
      const time = timeValue(row.timestamp);
      if (Number.isFinite(time) && Number.isFinite(${watermarkTime}) && time !== ${watermarkTime}) {
        return time <= ${watermarkTime};
      }
      return idAtOrBefore(row.message_id, ${JSON.stringify(watermark?.message_id || "")});
    };
    let cursor = ${JSON.stringify(initialCursor)};
    let pages = 0;
    let scannedMessages = 0;
    let stoppedAtWatermark = false;
    let completed = false;
    let reachedWatermark = false;
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
        rows.push(row);
        if (row.media) media.push(row.media);
        if (atOrBeforeWatermark(row)) reachedWatermark = true;
      }
      if (reachedWatermark) { stoppedAtWatermark = true; break; }
      if (batch.length < ${batchSize}) { completed = true; break; }
      const lastId = String(batch.at(-1)?.msgId ?? batch.at(-1)?.messageId ?? '');
      if (!/^\\d+$/.test(lastId) || lastId === cursor) throw new Error('invalid_next_cursor:' + lastId);
      cursor = lastId;
    }
    if (pages >= ${maxPages} && !stoppedAtWatermark && !completed) throw new Error('message_page_cap_exceeded:' + ${maxPages});
    for (const row of rows) if (!row.sender) row.sender = senderNames.get(row.sender_id) || '';
    return { conversationId, rows, media, pages, scannedMessages, stoppedAtWatermark, completed };
  })()`);
} finally {
  ws.close();
}
if (data?.error) throw new Error(data.error);
if (String(data.conversationId || "") !== String(state.conversation_id)) {
  throw new Error("conversation_id_mismatch");
}

const newerRows = (data.rows || []).map((row) => ({
  timestamp: String(row.timestamp || ""),
  message_id: String(row.message_id || ""),
  conversation_id: String(row.conversation_id || ""),
  conversation_name: String(row.conversation_name || ""),
  sender: String(row.sender || ""),
  sender_id: String(row.sender_id || ""),
  msg_type: String(row.msg_type || ""),
  origin_msg_type: String(row.origin_msg_type || ""),
  text: redactMediaQuery(row.text),
  quote_text: redactMediaQuery(row.quote_text),
  reference_text: redactMediaQuery(row.reference_text),
  structured_links: redactMediaQuery(row.structured_links),
  attachment_name: String(row.attachment_name || ""),
})).filter((row) => row.message_id && isNewer(row));
const newerById = new Map();
for (const row of newerRows) if (!newerById.has(row.message_id)) newerById.set(row.message_id, row);
const normalizedRows = [...newerById.values()].sort(compareMessageRows);

const csvFields = ["timestamp", "message_id", "conversation_id", "conversation_name", "sender", "sender_id", "msg_type", "origin_msg_type", "text", "quote_text", "reference_text", "structured_links", "attachment_name"];
const csvEscape = (value) => {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const csv = [csvFields.join(","), ...normalizedRows.map((row) => csvFields.map((field) => csvEscape(row[field])).join(","))].join("\n") + "\n";
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
atomicWrite(deltaPath, csv);

const newMessageIds = new Set(normalizedRows.map((row) => row.message_id));
const mediaCandidates = (data.media || []).filter(
  (row) => newMessageIds.has(String(row.msgId)) && isAllowedMediaUrl(row.url),
);
if (candidatePath) {
  const jsonl = mediaCandidates.map((row) => JSON.stringify(row)).join("\n");
  atomicWrite(candidatePath, jsonl ? `${jsonl}\n` : "");
}

console.log(JSON.stringify({
  groupName,
  pages: data.pages,
  scannedMessages: data.scannedMessages,
  deltaMessages: normalizedRows.length,
  mediaCandidates: candidatePath ? mediaCandidates.length : 0,
  stoppedAtWatermark: Boolean(data.stoppedAtWatermark),
  watermarkPresent: Boolean(watermark),
}, null, 2));
