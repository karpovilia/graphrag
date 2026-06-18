import { describe, it, expect } from "vitest";
import { parseChat, parseDocuments } from "./project.js";

const SAMPLE = `2025-11-10 14:31:58 Максим Гуськов
text: сейчас на витрину идёт трафик около 1000 запросов в час

2025-11-14 16:31:25 Karpov Ilia
text: привет, заведи трекер
  и добавь меня`;

describe("parseChat", () => {
  it("splits messages with timestamp + author + multi-line text", () => {
    const msgs = parseChat("dm.txt", SAMPLE);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]).toMatchObject({ author: "Максим Гуськов", validFrom: "2025-11-10T14:31:58.000Z", uri: "dm.txt" });
    expect(msgs[0]!.text).toContain("трафик около 1000");
    expect(msgs[1]).toMatchObject({ author: "Karpov Ilia", validFrom: "2025-11-14T16:31:25.000Z" });
    expect(msgs[1]!.text).toContain("добавь меня"); // multi-line joined
    expect(msgs[1]!.text).not.toMatch(/^text:/); // "text:" prefix stripped
  });
});

describe("parseDocuments", () => {
  it("chat format → per-message documents", () => {
    const docs = parseDocuments([{ uri: "a.txt", text: SAMPLE }], { format: "chat", chunkSize: 1200, chunkOverlap: 0, perMessage: true });
    expect(docs).toHaveLength(2);
    expect(docs.every((d) => d.validFrom && d.author)).toBe(true);
  });
  it("plain format → one document per file", () => {
    const docs = parseDocuments([{ uri: "a.txt", text: "hello" }], { format: "plain", chunkSize: 1200, chunkOverlap: 0 });
    expect(docs).toEqual([{ id: "a.txt", uri: "a.txt", text: "hello" }]);
  });
  it("chat file with no headers falls back to one document", () => {
    const docs = parseDocuments([{ uri: "x.txt", text: "no timestamps here" }], { format: "chat", chunkSize: 1200, chunkOverlap: 0, perMessage: true });
    expect(docs).toHaveLength(1);
    expect(docs[0]!.text).toBe("no timestamps here");
  });
});
