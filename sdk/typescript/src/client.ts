import { buildEvent, type CallRecord } from "./capture.js";
import { resolveConfig, type LogLlamaOptions, type ResolvedConfig } from "./config.js";
import { EventTransport, type TransportStats } from "./transport.js";

interface ClientState {
  config: ResolvedConfig;
  transport: EventTransport | undefined;
}

let state: ClientState | undefined;
let exitHookInstalled = false;

function createTransport(config: ResolvedConfig): EventTransport {
  return new EventTransport({
    endpoint: config.endpoint,
    apiKey: config.apiKey ?? "",
    timeoutMs: config.timeoutMs,
    batchSize: config.batchSize,
    flushIntervalMs: config.flushIntervalMs,
    maxQueueSize: config.maxQueueSize,
    onError: (message) => console.warn(message),
  });
}

function installExitHook(): void {
  if (exitHookInstalled || typeof process === "undefined") return;
  exitHookInstalled = true;
  process.once("beforeExit", () => {
    void flush(2000);
  });
}

/** Configure LogLlama once per process. Options override LOGLLAMA_* environment variables. */
export function init(options: LogLlamaOptions = {}): ResolvedConfig {
  const config = resolveConfig(options);
  const previous = state?.transport;
  state = {
    config,
    transport: config.enabled && config.apiKey ? createTransport(config) : undefined,
  };
  if (previous) void previous.shutdown(1000);
  installExitHook();
  return config;
}

function currentState(): ClientState {
  if (state === undefined) init();
  return state as ClientState;
}

export function getConfig(): ResolvedConfig {
  return currentState().config;
}

export function captureCall(record: CallRecord): void {
  const { config, transport } = currentState();
  if (!transport) return;
  // Errors are always captured, even when successful calls are sampled.
  if (record.status === "success" && Math.random() >= config.sampleRate) return;
  transport.submit(buildEvent(config, record, new Date()));
}

/** Resolves true when every queued event has been delivered or dropped. */
export async function flush(timeoutMs = 5000): Promise<boolean> {
  return (await currentState().transport?.flush(timeoutMs)) ?? true;
}

export async function shutdown(timeoutMs = 5000): Promise<boolean> {
  return (await currentState().transport?.shutdown(timeoutMs)) ?? true;
}

export function stats(): TransportStats {
  return currentState().transport?.stats() ?? { queued: 0, sent: 0, dropped: 0, failed: 0, pending: 0 };
}
