export const normalizeLinkArchiveItems = (items, conversationId) => {
  const seen = new Set();
  const rows = [];
  for (const item of Array.isArray(items) ? items : []) {
    const data = item?.data;
    const messageId = String(data?.msgId || "").trim();
    if (!messageId || String(data?.userId || "") !== String(conversationId) || !data?.message || seen.has(messageId)) continue;
    seen.add(messageId);
    rows.push({
      archive_index: String(rows.length + 1),
      message_id: messageId,
      timestamp: String(data.sendDttm || ""),
      sender_id: String(data.fromUid || ""),
      title: String(data.message.title || ""),
      url: String(data.message.href || ""),
      source: "link_archive",
    });
  }
  return rows;
};
