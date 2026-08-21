import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const streamResponseToFile = async (response, filePath) => {
  if (!response?.body) throw new Error("media_response_body_missing");
  const target = path.resolve(filePath);
  await fs.promises.mkdir(path.dirname(target), { recursive: true });
  const handle = await fs.promises.open(target, "wx");
  const hash = crypto.createHash("sha256");
  let head = Buffer.alloc(0);
  let size = 0;
  try {
    for await (const chunk of response.body) {
      const buffer = Buffer.from(chunk);
      if (head.length < 16) head = Buffer.concat([head, buffer]).subarray(0, 16);
      hash.update(buffer);
      size += buffer.length;
      await handle.write(buffer);
    }
    await handle.close();
    return { size, sha256: hash.digest("hex"), head };
  } catch (error) {
    await handle.close().catch(() => {});
    await fs.promises.rm(target, { force: true });
    throw error;
  }
};

export const sha256File = async (filePath) => {
  const hash = crypto.createHash("sha256");
  for await (const chunk of fs.createReadStream(filePath)) hash.update(chunk);
  return hash.digest("hex");
};
