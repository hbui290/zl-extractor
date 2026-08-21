import fs from "node:fs";
import path from "node:path";
import { assertBrowserExpression, runtimeExceptionMessage } from "./browser_runtime.mjs";
import { normalizeLinkArchiveItems } from "./link_archive_normalize.mjs";
import { waitForZaloPage } from "./zalo_cdp.mjs";

const required = (name) => {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`missing ${name}`);
  return value;
};
const port = Number(required("ZALO_CDP_PORT"));
if (!Number.isInteger(port) || port <= 0) throw new Error("invalid ZALO_CDP_PORT");
const groupName = required("ZALO_GROUP_NAME").normalize("NFC").toLocaleLowerCase();
const outputRoot = path.resolve(required("OUTPUT_ROOT"));
const archivePath = path.resolve(required("LINK_ARCHIVE_PATH"));
const auditPath = path.resolve(required("LINK_ARCHIVE_AUDIT_PATH"));
const reportedCardCount = String(process.env.ZALO_REPORTED_LINK_COUNT || "").trim();
const expectedCards = reportedCardCount === "" ? null : Number(reportedCardCount);
if (expectedCards !== null && (!Number.isInteger(expectedCards) || expectedCards < 0)) throw new Error("invalid ZALO_REPORTED_LINK_COUNT");
if (!fs.existsSync(outputRoot) || fs.lstatSync(outputRoot).isSymbolicLink()) throw new Error("OUTPUT_ROOT must exist and must not be a symlink");
for (const [target, base, label] of [[archivePath, path.join(outputRoot, "source", "raw"), "LINK_ARCHIVE_PATH"], [auditPath, path.join(outputRoot, "source"), "LINK_ARCHIVE_AUDIT_PATH"]]) {
  if (!fs.existsSync(base) || fs.lstatSync(base).isSymbolicLink() || path.dirname(target) !== base) throw new Error(`${label} must be a direct file under a non-symlink ${path.basename(base)}/`);
}
const manifestPath = path.join(outputRoot, "source", "manifest.json");
const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, "utf8")) : {};
if (manifest.sourceWriteIssued === true) throw new Error("refusing derived write: sourceWriteIssued=true");
const expectedConversationId = String(manifest.source?.conversationId || manifest.conversationId || "");

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
const csv = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;

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
    if (matches.length !== 1) return { error: matches.length ? 'group-ambiguous' : 'group-not-found' };
    const conversationId = String(matches[0].userId || matches[0].id || '');
    const card = document.querySelector('.chat-info-link');
    if (!card) return { error: 'open-link-archive-first' };
    const reactKey = Object.keys(card).find((key) => key.startsWith('__reactInternalInstance$') || key.startsWith('__reactFiber$'));
    const fiber = reactKey ? card[reactKey] : null;
    const direct = fiber?.pendingProps?.children?.[1]?._owner?.ref?.current?.props?.viewModel;
    const findViewModel = (root) => {
      if (direct?.__data__) return direct;
      const queue = [[root, 0]];
      const seen = new WeakSet();
      while (queue.length) {
        const [value, depth] = queue.shift();
        if (!value || typeof value !== 'object' || seen.has(value) || depth > 9) continue;
        seen.add(value);
        if (Array.isArray(value.__data__)) return value;
        for (const key of ['pendingProps', 'memoizedProps', 'children', '_owner', 'ref', 'current', 'props', 'viewModel']) {
          const child = value[key];
          if (Array.isArray(child)) child.forEach((entry) => queue.push([entry, depth + 1]));
          else queue.push([child, depth + 1]);
        }
      }
      return null;
    };
    const viewModel = findViewModel(fiber);
    if (!viewModel) return { error: 'link-archive-view-model-not-found' };
    const scroll = document.querySelector('#innerScrollContainer');
    if (!scroll) return { error: 'link-archive-scroll-container-not-found' };
    let stable = 0;
    let previous = '';
    for (let attempt = 0; attempt < 40 && stable < 4; attempt += 1) {
      if (scroll) scroll.scrollTop = scroll.scrollHeight;
      await new Promise((resolve) => setTimeout(resolve, 250));
      const cards = viewModel.__data__.filter((item) => item?.data?.msgId && item?.data?.message).length;
      const state = [cards, scroll?.scrollHeight || 0, scroll ? Math.round(scroll.scrollTop) : 0].join(':');
      stable = state === previous ? stable + 1 : 0;
      previous = state;
    }
    return { conversationId, stable, items: viewModel.__data__.map((item) => ({ data: item?.data })) };
  })()`);
} finally {
  ws.close();
}
if (data?.error) throw new Error(data.error);
if (expectedConversationId && String(data?.conversationId || "") !== expectedConversationId) throw new Error("link archive conversation does not match manifest");
if (!data?.conversationId || data.stable < 4) throw new Error("link archive did not reach a stable end");
const rows = normalizeLinkArchiveItems(data.items, data.conversationId);
const rawCardCount = data.items.filter((item) => item?.data?.msgId && item?.data?.message).length;
if (rows.length !== rawCardCount) throw new Error("link archive contains duplicate or foreign-conversation cards");
if (!rows.length && expectedCards !== 0) throw new Error("link archive returned no cards");
if (expectedCards !== null && rows.length !== expectedCards) throw new Error(`link archive card mismatch: expected ${expectedCards}, got ${rows.length}`);

const fields = ["archive_index", "message_id", "timestamp", "sender_id", "title", "url", "source"];
atomicWrite(archivePath, `${fields.map(csv).join(",")}\n${rows.map((row) => fields.map((field) => csv(row[field])).join(",")).join("\n")}\n`);
atomicWrite(auditPath, `${JSON.stringify({
  status: "COMPLETE",
  conversationId: data.conversationId,
  enumeratedCardCount: rows.length,
  reportedCardCount: expectedCards,
  endCondition: "ui_scroll_bottom_stable_4_cycles",
  capturedAt: new Date().toISOString(),
}, null, 2)}\n`);
console.log(JSON.stringify({ status: "COMPLETE", cards: rows.length, archivePath, auditPath }));
