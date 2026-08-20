import fs from "node:fs";
import path from "node:path";

const validUrl = (value) => typeof value === "string" && /^https?:\/\//i.test(value);
const urlKeys = new Set(["oriUrl", "hdUrl", "normalUrl", "thumbUrl", "url", "fileUrl", "downloadUrl"]);
const internalMediaSuffixes = [".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn"];
const internalMediaHostTokens = ["stal", "ava-talk", "zpg-r", "photo-link-talk"];

export const isAllowedMediaUrl = (value) => {
  if (!validUrl(value)) return false;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    return internalMediaSuffixes.some((suffix) => host.endsWith(suffix))
      && internalMediaHostTokens.some((token) => host.includes(token));
  } catch {
    return false;
  }
};

const normalize = (row, line) => {
  if (!row || typeof row !== "object" || Array.isArray(row)) {
    throw new Error(`invalid media candidate at line ${line}`);
  }
  if (typeof row.msgId !== "string" || !row.msgId) {
    throw new Error(`invalid media candidate msgId at line ${line}`);
  }
  if (!validUrl(row.url)) {
    throw new Error(`invalid media candidate url at line ${line}`);
  }
  if (!isAllowedMediaUrl(row.url)) {
    throw new Error(`unsupported media host at line ${line}`);
  }
  if (!urlKeys.has(row.urlKey)) {
    throw new Error(`invalid media candidate urlKey at line ${line}`);
  }
  return {
    msgId: row.msgId,
    ordinal: Number.isSafeInteger(Number(row.ordinal)) ? Number(row.ordinal) : 1,
    sendDttm: Number.isFinite(Number(row.sendDttm)) ? Number(row.sendDttm) : 0,
    url: row.url,
    urlKey: row.urlKey,
    mediaType: typeof row.mediaType === "string" ? row.mediaType.slice(0, 80) : "",
    mime: typeof row.mime === "string" ? row.mime.slice(0, 120).toLowerCase() : "",
    originalName: typeof row.originalName === "string" ? row.originalName.slice(0, 240) : "",
    sender: typeof row.sender === "string" ? row.sender.slice(0, 160) : "",
    senderId: typeof row.senderId === "string" ? row.senderId.slice(0, 120) : "",
  };
};

export const loadMediaCandidates = (candidatePath) => {
  const resolved = path.resolve(candidatePath);
  if (!fs.existsSync(resolved)) throw new Error(`media candidate snapshot not found: ${resolved}`);
  const content = fs.readFileSync(resolved, "utf8").trim();
  if (!content) return { source: "snapshot", pages: 0, rows: [] };
  const parsed = content.startsWith("[")
    ? JSON.parse(content).map((row, index) => normalize(row, index + 1))
    : content.split("\n").filter(Boolean).map((line, index) => normalize(JSON.parse(line), index + 1));
  return { source: "snapshot", pages: 0, rows: parsed };
};
