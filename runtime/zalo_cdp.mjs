const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const readyTimeout = () => {
  const raw = String(process.env.ZALO_READY_TIMEOUT_MS || "30000").trim();
  const milliseconds = Number(raw);
  if (!Number.isSafeInteger(milliseconds) || milliseconds < 1000 || milliseconds > 120000) {
    throw new Error("invalid ZALO_READY_TIMEOUT_MS");
  }
  return milliseconds;
};

export async function waitForZaloPage(port) {
  const timeoutMs = readyTimeout();
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (!response.ok) throw new Error(`CDP HTTP ${response.status}`);
      const targets = await response.json();
      const page = targets.find((item) => item.type === "page" && item.title === "Zalo");
      if (page) return page;
      if (targets.some((item) => item.type === "page" && String(item.title || "").includes("Đăng nhập"))) {
        lastError = "Zalo renderer is still on the login screen";
      } else {
        lastError = "Zalo renderer is still loading";
      }
    } catch (error) {
      lastError = error.message;
    }
    await sleep(500);
  }
  throw new Error(`Zalo renderer not ready after ${timeoutMs}ms: ${lastError}`);
}
