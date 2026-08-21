export const timestampValue = (value) => {
  const text = String(value ?? '').trim();
  if (!text) return null;
  const number = Number(text);
  if (Number.isFinite(number)) return Math.abs(number) < 100_000_000_000 ? number * 1000 : number;
  const parsed = Date.parse(text.replace('Z', '+00:00'));
  return Number.isFinite(parsed) ? parsed : null;
};

export const compareMessageIds = (left, right) => {
  const a = String(left ?? '');
  const b = String(right ?? '');
  if (/^\d+$/.test(a) && /^\d+$/.test(b)) {
    const leftNumber = BigInt(a);
    const rightNumber = BigInt(b);
    return leftNumber < rightNumber ? -1 : leftNumber > rightNumber ? 1 : 0;
  }
  return a.localeCompare(b);
};

export const compareMessageRows = (left, right) => {
  const leftTime = timestampValue(left?.timestamp);
  const rightTime = timestampValue(right?.timestamp);
  if (leftTime !== null && rightTime !== null && leftTime !== rightTime) return leftTime < rightTime ? -1 : 1;
  if (leftTime === null && rightTime !== null) return 1;
  if (leftTime !== null && rightTime === null) return -1;
  return compareMessageIds(left?.message_id, right?.message_id);
};
