import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { flush, init, shutdown, wrapOpenAI } from "../src/index.js";
import { redactText } from "../src/redact.js";


describe("redactText", () => {
  it.each([
    ["Incorrect API key provided: =sk-proj*****************************xpkA. You can find", "sk-proj"],
    ["rejected sk-ant-api03-abcdefghijklmnop", "abcdefghijklmnop"],
    ["google said AIzaSyD-1234567890abcdef", "AIzaSyD"],
    ["LogLlama rejected llm_ABCDEFGH12345678", "llm_ABCDEFGH"],
    ["runtime llrt_ZYXWVUTS98765432 is invalid", "llrt_ZYXW"],
    ["Authorization: Bearer abc.def.ghi-123456", "abc.def"],
    ["api_key=supersecret123", "supersecret123"],
    ["password: hunter2-long", "hunter2-long"],
  ])("removes the secret from: %s", (raw, leaked) => {
    const redacted = redactText(raw);

    expect(redacted).not.toContain(leaked);
    expect(redacted).toContain("[REDACTED]");
  });

  it.each(["task-manager requires review", "tokens used: 13", "rate limit exceeded, retry after 20 seconds"])(
    "leaves ordinary text unchanged: %s",
    (text) => {
      expect(redactText(text)).toBe(text);
    },
  );
});

describe("provider error capture", () => {
  let recorded: Record<string, unknown>[] = [];

  beforeEach(() => {
    recorded = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL | Request, requestInit?: RequestInit) => {
        const body = JSON.parse(String(requestInit?.body)) as { events: Record<string, unknown>[] };
        recorded.push(...body.events);
        return new Response(null, { status: 202 });
      }),
    );
    init({ apiKey: "llm_test", endpoint: "http://logllama.test", flushIntervalMs: 60_000, batchSize: 100 });
  });

  afterEach(async () => {
    await shutdown(5000);
    vi.unstubAllGlobals();
  });

  it("redacts the provider error message before it is captured", async () => {
    const client = wrapOpenAI({
      chat: {
        completions: {
          create: async () => {
            throw new Error("Incorrect API key provided: =sk-proj-abcdef1234567890wxyz. Check yours.");
          },
        },
      },
    });

    await expect(client.chat.completions.create({ model: "gpt-4o-mini", messages: [] } as never)).rejects.toThrow();
    await flush(5000);

    const error = recorded[0].error as { message: string };
    expect(error.message).not.toContain("abcdef1234567890");
    expect(error.message).toContain("[REDACTED]");
  });
});
