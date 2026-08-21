export function evaluatePinAudit({ rowCount, reportedPinCount = null, uiReportedPinCount = null, explicitNoMore = false }) {
  const nonNegativeCount = (value) => Number.isSafeInteger(value) && value >= 0 ? value : null;
  const rows = nonNegativeCount(rowCount);
  const uiCount = nonNegativeCount(uiReportedPinCount);
  const apiCount = nonNegativeCount(reportedPinCount);
  if (rows !== null && uiCount !== null && uiCount !== rows) return { complete: false, endCondition: "ui_pin_count_mismatch" };
  if (rows !== null && uiCount !== null && uiCount === rows) return { complete: true, endCondition: "ui_pin_total_match" };
  if (rows !== null && explicitNoMore && (apiCount === null || apiCount === rows)) {
    return { complete: true, endCondition: "explicit_no_more" };
  }
  return { complete: false, endCondition: "missing_pin_end_signal" };
}

const toEpoch = (value) => {
  const text = String(value ?? "").trim();
  if (!text) return null;
  if (/^\d+(?:\.\d+)?$/.test(text)) {
    const number = Number(text);
    if (!Number.isFinite(number)) return null;
    return number < 100_000_000_000 ? number * 1000 : number;
  }
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (dateOnly) {
    const [, year, month, day] = dateOnly.map(Number);
    const local = new Date(year, month - 1, day);
    if (local.getFullYear() !== year || local.getMonth() !== month - 1 || local.getDate() !== day) return null;
    return local.getTime();
  }
  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? null : parsed;
};

export function pinWindowStatus(timestamp, messageStartAt) {
  const messageTime = toEpoch(timestamp);
  const startTime = toEpoch(messageStartAt);
  if (startTime === null) return "pin_window_unbounded";
  if (messageTime === null) return "pin_window_unknown";
  return messageTime < startTime ? "pin_outside_message_window" : "pin_in_message_window";
}
