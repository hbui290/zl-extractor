import fs from "node:fs";
import path from "node:path";
import { assertBrowserExpression, runtimeExceptionMessage } from "./browser_runtime.mjs";
import { evaluatePinAudit, pinWindowStatus } from "./pin_audit_policy.mjs";
import { waitForZaloPage } from "./zalo_cdp.mjs";

const required = (name) => {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`missing ${name}`);
  return value;
};

const port = Number(required("ZALO_CDP_PORT"));
if (!Number.isInteger(port) || port <= 0) throw new Error("invalid ZALO_CDP_PORT");
const outputRoot = path.resolve(required("OUTPUT_ROOT"));
const groupName = required("ZALO_GROUP_NAME").normalize("NFC").toLocaleLowerCase();
const pinsPath = path.resolve(required("PINS_PATH"));
const auditPath = process.env.PIN_AUDIT_PATH ? path.resolve(process.env.PIN_AUDIT_PATH) : "";
const manifestPath = path.join(outputRoot, "source", "manifest.json");
const sourceManifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, "utf8")) : {};
const messageStartAt = String(sourceManifest.source?.startAt || "").trim();
const maxPinsValue = String(process.env.MAX_PIN_ROWS || "").trim();
const maxPins = maxPinsValue ? Number(maxPinsValue) : 1000;
if (!Number.isSafeInteger(maxPins) || maxPins < 1 || maxPins > 10000) throw new Error("invalid MAX_PIN_ROWS");

const outputRelativePins = path.relative(outputRoot, pinsPath);
if (outputRelativePins === "" || (!outputRelativePins.startsWith("..") && !path.isAbsolute(outputRelativePins))) {
  throw new Error("PINS_PATH must stay outside OUTPUT_ROOT until it is moved into raw");
}
if (auditPath) {
  const relativeAudit = path.relative(path.join(outputRoot, "source"), auditPath);
  if (relativeAudit === "" || relativeAudit.startsWith("..") || path.isAbsolute(relativeAudit)) {
    throw new Error("PIN_AUDIT_PATH must stay under OUTPUT_ROOT/source");
  }
}

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
  const matches = groups.filter((group) => String(group.displayName || '').trim().normalize('NFC').toLocaleLowerCase() === ${JSON.stringify(groupName)});
  if (matches.length === 0) return { error: 'group-not-found' };
  if (matches.length > 1) return { error: 'group-ambiguous' };
  const target = matches[0];
  const conversationId = String(target.userId || target.id || '');
  if (!conversationId) return { error: 'conversation-id-missing' };

  const runtimeModule = window.webpackJsonp.push([[Math.random()], {}, [['jDHv']]]);
  const container = runtimeModule?.ModuleContainer || runtimeModule?.default?.ModuleContainer;
  const tokens = ['pin-topic-one-on-one-controller', 'pin-topic-data-repository'];
  let adapter = null;
  let adapterToken = '';
  for (const token of tokens) {
    try {
      const candidate = container?.resolve({ service: token, token });
      if (candidate && typeof candidate.loadPinTopics === 'function') {
        adapter = candidate;
        adapterToken = token;
        break;
      }
    } catch {}
  }
  if (!adapter) return { error: 'pin-adapter-unavailable' };
  const response = await adapter.loadPinTopics(conversationId);
  if (!response || String(response.conversationId || '') !== conversationId) return { error: 'pin-conversation-mismatch' };
  if (!Array.isArray(response.topics)) return { error: 'pin-topics-not-array' };
  if (response.topics.length > ${maxPins}) return { error: 'pin_page_cap_exceeded:${maxPins}' };

  const parseObject = (value) => {
    if (!value || typeof value !== 'string') return value || {};
    try { const parsed = JSON.parse(value); return parsed && typeof parsed === 'object' ? parsed : {}; } catch { return {}; }
  };
  const objectValue = (topic) => [
    topic,
    parseObject(topic.params),
    topic.message,
    parseObject(topic.message?.params),
    parseObject(topic.message),
    topic.data,
    topic.payload,
  ];
  const pick = (objects, keys) => {
    for (const object of objects) {
      if (!object || typeof object !== 'object') continue;
      for (const key of keys) {
        const value = object[key];
        if (value != null && String(value).trim()) return String(value).trim();
      }
    }
    return '';
  };
  const collectText = (value, depth = 0, seen = new WeakSet()) => {
    if (depth > 6 || value == null) return '';
    if (typeof value === 'string') return value.trim();
    if (typeof value !== 'object' || seen.has(value)) return '';
    seen.add(value);
    const parts = [];
    for (const key of ['text', 'messageText', 'caption', 'description', 'body', 'content', 'title']) {
      if (typeof value[key] === 'string' && value[key].trim()) parts.push(value[key].trim());
      else if (value[key] && typeof value[key] === 'object') parts.push(collectText(value[key], depth + 1, seen));
    }
    return parts.filter(Boolean).join(' ');
  };
  const text = (objects, keys) => {
    for (const object of objects) {
      if (!object || typeof object !== 'object') continue;
      for (const key of keys) {
        const value = collectText(object[key]);
        if (value) return value.replace(/\\s+/g, ' ').slice(0, 2000);
      }
    }
    return '';
  };
  const bareTlds = new Set(['ai', 'app', 'biz', 'cc', 'co', 'com', 'dev', 'digital', 'fun', 'gg', 'io', 'me', 'net', 'online', 'org', 'site', 'tech', 'tv', 'vn', 'xyz']);
  const trimUrl = (value) => String(value || '').trim().replace(/[.,;:!?]+$/, '').replace(/[)\\]}]+$/, '');
  const isBareUrl = (value) => {
    const text = trimUrl(value);
    if (!text || /^https?:\\/\\//i.test(text)) return false;
    const host = text.split(/[/?#]/, 1)[0].toLowerCase().replace(/^www\\./, '');
    const labels = host.split('.');
    return labels.length >= 2 && bareTlds.has(labels.at(-1)) && /[a-z]/i.test(labels[0]);
  };
  const collectUrls = (value, depth = 0, seen = new WeakSet(), output = []) => {
    if (depth > 8 || value == null || output.length >= 200) return output;
    if (typeof value === 'string') {
      const explicit = [];
      for (const match of value.matchAll(/https?:\\/\\/[^\\s<>"'\\x60]+/gi)) {
        const url = trimUrl(match[0]);
        if (url) { output.push(url); explicit.push(match.index); }
      }
      for (const match of value.matchAll(/(?<![@\\w])(?:www\\.)?(?:[a-z0-9-]+\\.)+[a-z]{2,}(?:\\/[^\\s<>"'\\x60)\\]]*)?/gi)) {
        const url = trimUrl(match[0]);
        if (url && isBareUrl(url) && !explicit.some((start) => start <= match.index && match.index < start + url.length)) output.push(url);
      }
      return output;
    }
    if (typeof value !== 'object' || seen.has(value)) return output;
    seen.add(value);
    for (const child of Object.values(value)) collectUrls(child, depth + 1, seen, output);
    return output;
  };
  const rows = [];
  for (let index = 0; index < response.topics.length; index++) {
    const topic = response.topics[index] || {};
    let message = null;
    try { message = typeof adapter.getMessageFromTopic === 'function' ? adapter.getMessageFromTopic(topic) : null; } catch {}
    const objects = objectValue({ ...topic, message });
    const urls = [...new Set(collectUrls(objects))];
    rows.push({
      pin_id: String(topic.id ?? topic.topicId ?? String(index + 1)),
      message_id: pick(objects, ['msgId', 'messageId', 'global_msg_id', 'globalMsgId', 'client_msg_id', 'cliMsgId']),
      timestamp: pick(objects, ['sendDttm', 'timestamp', 'sendTime', 'send_time', 'createTime', 'create_time']),
      sender: pick(objects, ['senderName', 'fromName', 'senderUid', 'senderId', 'fromUid']),
      topic_type: String(topic.type ?? topic.topicType ?? ''),
      title: text(objects, ['linkCaption', 'title', 'subject', 'name']),
      text: text(objects, ['text', 'messageText', 'content', 'message', 'description', 'caption']),
      url: urls[0] || '',
      urls: urls.join('\\n'),
      source: 'pin',
      pin_index: String(index + 1),
    });
  }
  const reportedPinCount = pick([response], ['total', 'totalCount', 'topicCount', 'totalTopics', 'totalItems']);
  const normalizeLabel = (value) => String(value || '').replace(/\\s+/g, ' ').trim().normalize('NFC').toLocaleLowerCase();
  const visibleConversationMatches = normalizeLabel(document.querySelector('.header-title')?.textContent) === normalizeLabel(target.displayName);
  const visiblePin = document.querySelector('.chat-group-topic__item');
  const morePins = /\\+(\\d+)\\s*ghim/i.exec(document.querySelector('.show-details-btn')?.textContent || '');
  const uiReportedPinCount = visibleConversationMatches && visiblePin ? 1 + Number(morePins?.[1] || 0) : '';
  const explicitNoMore = response.noMore === true
    || response.hasMore === false
    || response.nextCursor === null
    || (response.nextCursor === undefined && response.hasMore === false);
  return {
    conversationId,
    conversationName: String(target.displayName || ''),
    adapterToken,
    rows,
    topicCount: response.topics.length,
    reportedPinCount,
    uiReportedPinCount,
    explicitNoMore,
  };
  })()`);
} finally {
  ws.close();
}
if (data?.error) throw new Error(data.error);

const redactInternalMediaUrl = (value) => String(value || "").replace(/https?:\/\/[^\s<>"'`]+/gi, (token) => {
  const trailing = token.match(/[.,;:!?)]*$/)?.[0] || "";
  const clean = trailing ? token.slice(0, -trailing.length) : token;
  try {
    const parsed = new URL(clean);
    const host = parsed.hostname.toLowerCase();
    const internal = [".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn"].some((suffix) => host.endsWith(suffix))
      && ["stal", "ava-talk", "zpg-r", "photo-link-talk"].some((part) => host.includes(part));
    return internal ? `${parsed.origin}${parsed.pathname}${trailing}` : token;
  } catch { return token; }
});

const fields = ["pin_id", "message_id", "timestamp", "sender", "topic_type", "title", "text", "url", "urls", "source", "pin_index", "message_scope"];
const csvEscape = (value) => {
  const text = redactInternalMediaUrl(String(value ?? ""));
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const rows = (data.rows || []).map((row) => Object.fromEntries(fields.map((field) => [field, field === "message_scope" ? pinWindowStatus(row.timestamp, messageStartAt) : (row[field] || "")])));
const csv = [fields.join(","), ...rows.map((row) => fields.map((field) => csvEscape(row[field])).join(","))].join("\n") + "\n";
atomicWrite(pinsPath, csv);
const reportedPinCountRaw = String(data.reportedPinCount ?? "").trim();
const reportedPinCount = /^\d+$/.test(reportedPinCountRaw) ? Number(reportedPinCountRaw) : null;
const pinAudit = evaluatePinAudit({
  rowCount: rows.length,
  reportedPinCount,
  uiReportedPinCount: Number.isSafeInteger(data.uiReportedPinCount) ? data.uiReportedPinCount : null,
  explicitNoMore: Boolean(data.explicitNoMore),
});
const audit = {
  conversationId: String(data.conversationId || ""),
  conversationName: String(data.conversationName || ""),
  pinAuditStatus: pinAudit.complete ? "complete" : "partial",
  pinAuditCompleteness: pinAudit.complete ? "complete" : "unknown",
  enumeratedPinCount: rows.length,
  uniquePinLinkCount: new Set(rows.flatMap((row) => String(row.urls || "").split("\n").filter(Boolean))).size,
  uniquePinExternalLinkCount: new Set(rows.flatMap((row) => String(row.urls || "").split("\n").filter((url) => url && !/\.(?:z|za)dn\.vn\//i.test(url)))).size,
  reportedPinCount,
  uiReportedPinCount: Number.isSafeInteger(data.uiReportedPinCount) ? data.uiReportedPinCount : null,
  endCondition: pinAudit.endCondition,
  adapterToken: String(data.adapterToken || ""),
};
if (auditPath) atomicWrite(auditPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify(audit, null, 2));
