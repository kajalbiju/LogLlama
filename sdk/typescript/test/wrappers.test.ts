import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { context, flush, init, shutdown, wrapAnthropic, wrapGemini, wrapOpenAI } from "../src/index.js";


interface Recorded {
  events: Record<string, unknown>[];
}

let recorded: Recorded;

beforeEach(() => {
  recorded = { events: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { events: Record<string, unknown>[] };
      recorded.events.push(...body.events);
      return new Response(null, { status: 202 });
    }),
  );
  init({ apiKey: "llm_test", endpoint: "http://logllama.test", flushIntervalMs: 60_000, batchSize: 100 });
});

afterEach(async () => {
  await shutdown(5000);
  vi.unstubAllGlobals();
});

function openAIClient(create: (params: Record<string, unknown>) => Promise<unknown>) {
  return { chat: { completions: { create } } };
}

describe("OpenAI wrapper", () => {
  it("captures a chat completion and strips logllama_metadata before the provider call", async () => {
    const received: Record<string, unknown>[] = [];
    const client = wrapOpenAI(
      openAIClient(async (params) => {
        received.push(params);
        return {
          id: "chatcmpl-1",
          model: "gpt-4o-mini-2024-07-18",
          choices: [{ message: { content: "hello there" } }],
          usage: { prompt_tokens: 3, completion_tokens: 2 },
        };
      }),
    );

    await client.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: "hi" }],
      logllama_metadata: { route: "/support", tenant_id: "tenant_acme" },
    } as never);
    await flush(5000);

    expect(received[0]).not.toHaveProperty("logllama_metadata");
    expect(recorded.events).toHaveLength(1);
    expect(recorded.events[0]).toMatchObject({
      provider: "openai",
      operation: "chat.completions.create",
      model: "gpt-4o-mini-2024-07-18",
      provider_request_id: "chatcmpl-1",
      status: "success",
      response: "hello there",
      route: "/support",
      tenant_id: "tenant_acme",
      usage: { input_tokens: 3, output_tokens: 2, total_tokens: 5 },
    });
  });

  it("captures errors and rethrows them", async () => {
    const client = wrapOpenAI(
      openAIClient(async () => {
        throw new RangeError("rate limited");
      }),
    );

    await expect(client.chat.completions.create({ model: "gpt-4o-mini", messages: [] } as never)).rejects.toThrow(
      "rate limited",
    );
    await flush(5000);

    expect(recorded.events[0]).toMatchObject({
      status: "error",
      response: null,
      error: { type: "RangeError", message: "rate limited" },
    });
  });

  it("passes streamed responses through without capturing them", async () => {
    const stream = { streamed: true };
    const client = wrapOpenAI(openAIClient(async () => stream));

    expect(await client.chat.completions.create({ model: "gpt-4o-mini", stream: true } as never)).toBe(stream);
    await flush(5000);
    expect(recorded.events).toHaveLength(0);
  });

  it("applies request context from AsyncLocalStorage", async () => {
    const client = wrapOpenAI(openAIClient(async () => ({ model: "gpt-4o-mini", choices: [] })));

    await context({ route: "/checkout", user_id: "user_42" }, () =>
      client.chat.completions.create({ model: "gpt-4o-mini", messages: [] } as never),
    );
    await flush(5000);

    expect(recorded.events[0]).toMatchObject({ route: "/checkout", user_id: "user_42" });
  });

  it("redacts sensitive keys in captured prompts", async () => {
    const client = wrapOpenAI(openAIClient(async () => ({ model: "gpt-4o-mini", choices: [] })));

    await client.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: "hi", api_key: "sk-secret-value" }],
    } as never);
    await flush(5000);

    expect(JSON.stringify(recorded.events[0].prompt)).not.toContain("sk-secret-value");
    expect(JSON.stringify(recorded.events[0].prompt)).toContain("[REDACTED]");
  });

  it("does not wrap the same client twice", async () => {
    const create = vi.fn(async () => ({ model: "gpt-4o-mini", choices: [] }));
    const client = openAIClient(create);
    wrapOpenAI(client);
    const once = client.chat.completions.create;
    wrapOpenAI(client);

    expect(client.chat.completions.create).toBe(once);
    await client.chat.completions.create({ model: "gpt-4o-mini" } as never);
    await flush(5000);
    expect(recorded.events).toHaveLength(1);
  });
});

describe("Anthropic wrapper", () => {
  it("captures text blocks, usage, and the system prompt", async () => {
    const client = wrapAnthropic({
      messages: {
        create: async () => ({
          id: "msg_01",
          model: "claude-sonnet-5-5",
          content: [{ type: "text", text: "ok" }],
          usage: { input_tokens: 1000, output_tokens: 500 },
        }),
      },
    });

    await client.messages.create({
      model: "claude-sonnet-5-5",
      max_tokens: 200,
      system: "Be brief.",
      messages: [{ role: "user", content: "Say ok" }],
    } as never);
    await flush(5000);

    expect(recorded.events[0]).toMatchObject({
      provider: "anthropic",
      operation: "messages.create",
      model: "claude-sonnet-5-5",
      response: "ok",
      model_parameters: { max_tokens: 200 },
      prompt: { system: "Be brief.", messages: [{ role: "user", content: "Say ok" }] },
      usage: { input_tokens: 1000, output_tokens: 500, total_tokens: 1500 },
    });
  });
});

describe("Gemini wrapper", () => {
  it("captures generateContent responses and usage metadata", async () => {
    const client = wrapGemini({
      models: {
        generateContent: async () => ({
          text: "ok",
          modelVersion: "gemini-2.5-flash",
          responseId: "resp_123",
          usageMetadata: { promptTokenCount: 4, candidatesTokenCount: 1 },
        }),
      },
    });

    await client.models.generateContent({
      model: "gemini-2.5-flash",
      contents: "Say ok",
      config: { temperature: 0, maxOutputTokens: 16 },
    } as never);
    await flush(5000);

    expect(recorded.events[0]).toMatchObject({
      provider: "gemini",
      operation: "models.generate_content",
      model: "gemini-2.5-flash",
      provider_request_id: "resp_123",
      response: "ok",
      model_parameters: { temperature: 0, maxOutputTokens: 16 },
      usage: { input_tokens: 4, output_tokens: 1, total_tokens: 5 },
    });
  });
});

describe("capture settings", () => {
  it("replaces prompts with a disabled marker when prompt capture is off", async () => {
    init({ apiKey: "llm_test", endpoint: "http://logllama.test", capturePrompts: false, flushIntervalMs: 60_000 });
    const client = wrapOpenAI(openAIClient(async () => ({ model: "gpt-4o-mini", choices: [] })));

    await client.chat.completions.create({ model: "gpt-4o-mini", messages: [{ role: "user", content: "secret" }] } as never);
    await flush(5000);

    expect(recorded.events[0].prompt).toEqual({ _logllama_capture: "disabled" });
    expect(JSON.stringify(recorded.events[0])).not.toContain("secret");
  });

  it("sends nothing when no API key is configured", async () => {
    init({ apiKey: "", endpoint: "http://logllama.test", flushIntervalMs: 60_000 });
    const client = wrapOpenAI(openAIClient(async () => ({ model: "gpt-4o-mini", choices: [] })));

    await client.chat.completions.create({ model: "gpt-4o-mini" } as never);
    await flush(5000);

    expect(recorded.events).toHaveLength(0);
  });
});
