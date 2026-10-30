import { describe, expect, it } from "vitest";

import { EventTransport, type TransportOptions } from "../src/transport.js";


interface Recorded {
  urls: string[];
  headers: Record<string, string>[];
  bodies: { events: Record<string, unknown>[] }[];
  fetchImpl: typeof fetch;
}

function recordingFetch(statuses: number[] = []): Recorded {
  const recorded: Recorded = {
    urls: [],
    headers: [],
    bodies: [],
    fetchImpl: undefined as unknown as typeof fetch,
  };
  recorded.fetchImpl = (async (url: string | URL | Request, init?: RequestInit) => {
    recorded.urls.push(String(url));
    recorded.headers.push(init?.headers as Record<string, string>);
    recorded.bodies.push(JSON.parse(String(init?.body)));
    return new Response(null, { status: statuses.shift() ?? 202 });
  }) as typeof fetch;
  return recorded;
}

function transportWith(overrides: Partial<TransportOptions> = {}): EventTransport {
  return new EventTransport({
    endpoint: "http://logllama.test",
    apiKey: "llm_test",
    timeoutMs: 1000,
    batchSize: 2,
    flushIntervalMs: 60_000,
    maxQueueSize: 100,
    retryBackoffMs: 0,
    ...overrides,
  });
}

describe("EventTransport", () => {
  it("sends events in batches of the configured size", async () => {
    const recorded = recordingFetch();
    const transport = transportWith({ fetchImpl: recorded.fetchImpl });

    for (let index = 0; index < 5; index += 1) {
      expect(transport.submit({ n: index })).toBe(true);
    }

    expect(await transport.flush(5000)).toBe(true);
    expect(recorded.bodies.map((body) => body.events.length)).toEqual([2, 2, 1]);
    expect(transport.stats()).toMatchObject({ queued: 5, sent: 5, dropped: 0, failed: 0, pending: 0 });
    expect(await transport.shutdown(5000)).toBe(true);
  });

  it("posts to the batch endpoint with the API key header", async () => {
    const recorded = recordingFetch();
    const transport = transportWith({ fetchImpl: recorded.fetchImpl, batchSize: 1 });

    transport.submit({ external_id: "a" });
    await transport.flush(5000);

    expect(recorded.urls).toEqual(["http://logllama.test/v1/events/batch"]);
    expect(recorded.headers[0]["X-LogLlama-Api-Key"]).toBe("llm_test");
    expect(recorded.bodies[0]).toEqual({ events: [{ external_id: "a" }] });
    await transport.shutdown(5000);
  });

  it("flush delivers a partial batch without waiting for the interval", async () => {
    const recorded = recordingFetch();
    const transport = transportWith({ fetchImpl: recorded.fetchImpl, batchSize: 10 });

    transport.submit({ n: 1 });
    expect(await transport.flush(5000)).toBe(true);
    expect(recorded.bodies).toHaveLength(1);
    await transport.shutdown(5000);
  });

  it("drops new events when the queue is full and counts them", async () => {
    const recorded = recordingFetch();
    const transport = transportWith({ fetchImpl: recorded.fetchImpl, batchSize: 10, maxQueueSize: 2 });

    const accepted = [transport.submit({ n: 0 }), transport.submit({ n: 1 }), transport.submit({ n: 2 })];

    expect(accepted).toEqual([true, true, false]);
    expect(transport.stats().dropped).toBe(1);
    await transport.flush(5000);
    expect(transport.stats().sent).toBe(2);
    await transport.shutdown(5000);
  });

  it("retries server errors and delivers when a later attempt succeeds", async () => {
    const recorded = recordingFetch([503, 500, 202]);
    const transport = transportWith({ fetchImpl: recorded.fetchImpl, batchSize: 1 });

    transport.submit({ n: 1 });
    await transport.flush(5000);

    expect(recorded.bodies).toHaveLength(3);
    expect(transport.stats()).toMatchObject({ sent: 1, failed: 0 });
    await transport.shutdown(5000);
  });

  it("drops a batch rejected with a client error without retrying", async () => {
    const recorded = recordingFetch([422]);
    const transport = transportWith({ fetchImpl: recorded.fetchImpl, batchSize: 1 });

    transport.submit({ n: 1 });
    await transport.flush(5000);

    expect(recorded.bodies).toHaveLength(1);
    expect(transport.stats()).toMatchObject({ sent: 0, failed: 1 });
    await transport.shutdown(5000);
  });

  it("gives up after the retry limit when the backend stays unavailable", async () => {
    const recorded = recordingFetch([500, 500, 500]);
    const transport = transportWith({ fetchImpl: recorded.fetchImpl, batchSize: 1, maxAttempts: 3 });

    transport.submit({ n: 1 });
    await transport.flush(5000);

    expect(recorded.bodies).toHaveLength(3);
    expect(transport.stats()).toMatchObject({ sent: 0, failed: 1 });
    await transport.shutdown(5000);
  });

  it("retries network failures", async () => {
    const attempts: number[] = [];
    const transport = transportWith({
      batchSize: 1,
      fetchImpl: (async () => {
        attempts.push(1);
        throw new TypeError("fetch failed");
      }) as typeof fetch,
    });

    transport.submit({ n: 1 });
    await transport.flush(5000);

    expect(attempts).toHaveLength(3);
    expect(transport.stats().failed).toBe(1);
    await transport.shutdown(5000);
  });

  it("refuses events after shutdown", async () => {
    const transport = transportWith({ fetchImpl: recordingFetch().fetchImpl });

    expect(await transport.shutdown(5000)).toBe(true);
    expect(transport.submit({ n: 1 })).toBe(false);
  });
});
