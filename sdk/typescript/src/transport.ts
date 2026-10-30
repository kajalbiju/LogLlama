export type LogLlamaEvent = Record<string, unknown>;

export interface TransportOptions {
  endpoint: string;
  apiKey: string;
  timeoutMs: number;
  batchSize: number;
  flushIntervalMs: number;
  maxQueueSize: number;
  fetchImpl?: typeof fetch;
  maxAttempts?: number;
  retryBackoffMs?: number;
  onError?: (message: string) => void;
}

export interface TransportStats {
  queued: number;
  sent: number;
  dropped: number;
  failed: number;
  pending: number;
}

const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_RETRY_BACKOFF_MS = 250;

/**
 * Bounded in-memory queue. Events are sent in batches of `batchSize`, or after `flushIntervalMs`.
 * When the queue is full, new events are dropped and counted, so telemetry never blocks a model call.
 */
export class EventTransport {
  private queue: LogLlamaEvent[] = [];
  private inFlight = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private draining: Promise<void> | undefined;
  private closed = false;
  private counts = { queued: 0, sent: 0, dropped: 0, failed: 0 };
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly options: TransportOptions) {
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  submit(event: LogLlamaEvent): boolean {
    if (this.closed) return false;
    if (this.queue.length >= this.options.maxQueueSize) {
      this.counts.dropped += 1;
      return false;
    }
    this.queue.push(event);
    this.counts.queued += 1;
    if (this.queue.length >= this.options.batchSize) {
      this.schedule(0);
    } else {
      this.schedule(this.options.flushIntervalMs);
    }
    return true;
  }

  /** Resolves true when everything queued so far has been delivered or dropped, or false on timeout. */
  async flush(timeoutMs = 5000): Promise<boolean> {
    this.cancelTimer();
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const timedOut = new Promise<false>((resolve) => {
      timeout = setTimeout(() => resolve(false), timeoutMs);
      timeout.unref?.();
    });
    const drained = this.drain().then(() => true as const);
    try {
      const finished = await Promise.race([drained, timedOut]);
      return finished === true && this.queue.length === 0;
    } finally {
      clearTimeout(timeout);
    }
  }

  async shutdown(timeoutMs = 5000): Promise<boolean> {
    const delivered = await this.flush(timeoutMs);
    this.closed = true;
    return delivered;
  }

  stats(): TransportStats {
    return { ...this.counts, pending: this.queue.length + this.inFlight };
  }

  private schedule(delayMs: number): void {
    if (this.timer !== undefined) {
      if (delayMs > 0) return;
      this.cancelTimer();
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.drain();
    }, delayMs);
    this.timer.unref?.();
  }

  private cancelTimer(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }

  private drain(): Promise<void> {
    if (!this.draining) {
      this.draining = (async () => {
        try {
          while (this.queue.length > 0) {
            const batch = this.queue.splice(0, this.options.batchSize);
            this.inFlight = batch.length;
            const delivered = await this.sendWithRetries(batch);
            this.counts[delivered ? "sent" : "failed"] += batch.length;
            this.inFlight = 0;
          }
        } finally {
          this.draining = undefined;
        }
      })();
    }
    return this.draining;
  }

  private async sendWithRetries(batch: LogLlamaEvent[]): Promise<boolean> {
    const maxAttempts = this.options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    const backoffMs = this.options.retryBackoffMs ?? DEFAULT_RETRY_BACKOFF_MS;
    const url = `${this.options.endpoint}/v1/events/batch`;

    let body: string;
    try {
      body = JSON.stringify({ events: batch });
    } catch (error) {
      this.report(`dropped ${batch.length} events that could not be serialized: ${String(error)}`);
      return false;
    }

    let lastError = "";
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        // Call through a local binding so that global fetch is not invoked with the transport as `this`.
        const send = this.fetchImpl;
        const response = await send(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-LogLlama-Api-Key": this.options.apiKey,
            "User-Agent": "logllama-typescript/0.1.0",
          },
          body,
          signal: AbortSignal.timeout(this.options.timeoutMs),
        });
        await response.text().catch(() => undefined);
        if (response.ok) return true;
        if (response.status !== 429 && response.status < 500) {
          this.report(`could not deliver ${batch.length} events: HTTP ${response.status}`);
          return false;
        }
        lastError = `HTTP ${response.status}`;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }

      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, backoffMs * 2 ** (attempt - 1)));
      }
    }

    this.report(`could not deliver ${batch.length} events after ${maxAttempts} attempts: ${lastError}`);
    return false;
  }

  private report(message: string): void {
    this.options.onError?.(`LogLlama ${message}`);
  }
}
