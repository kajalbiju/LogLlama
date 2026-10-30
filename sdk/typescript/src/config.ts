export interface LogLlamaOptions {
  apiKey?: string;
  endpoint?: string;
  serviceName?: string;
  environment?: string;
  version?: string;
  gitSha?: string;
  tags?: string[];
  capturePrompts?: boolean;
  captureResponses?: boolean;
  redactKeys?: string[];
  maxPromptSize?: number;
  maxResponseSize?: number;
  sampleRate?: number;
  enabled?: boolean;
  timeoutMs?: number;
  batchSize?: number;
  flushIntervalMs?: number;
  maxQueueSize?: number;
}

export interface ResolvedConfig {
  apiKey: string | undefined;
  endpoint: string;
  serviceName: string | undefined;
  environment: string | undefined;
  version: string | undefined;
  gitSha: string | undefined;
  tags: string[];
  capturePrompts: boolean;
  captureResponses: boolean;
  redactKeys: string[];
  maxPromptSize: number | undefined;
  maxResponseSize: number | undefined;
  sampleRate: number;
  enabled: boolean;
  timeoutMs: number;
  batchSize: number;
  flushIntervalMs: number;
  maxQueueSize: number;
}

export const DEFAULT_REDACT_KEYS = ["api_key", "authorization", "cookie", "password", "secret", "ssn", "token"];

type Env = Record<string, string | undefined>;

function readEnv(): Env {
  return typeof process !== "undefined" && process.env ? process.env : {};
}

function parseBoolean(raw: string): boolean {
  return !["0", "false", "no", "off"].includes(raw.trim().toLowerCase());
}

function parseNumber(raw: string): number | undefined {
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseList(raw: string): string[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function fromEnvironment<T>(
  env: Env,
  name: string,
  parse: (raw: string) => T | undefined,
): T | undefined {
  const raw = env[name];
  return raw !== undefined && raw.trim() !== "" ? parse(raw) : undefined;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Explicit options win over environment variables, which win over defaults. */
export function resolveConfig(options: LogLlamaOptions = {}, env: Env = readEnv()): ResolvedConfig {
  const sampleRate = options.sampleRate ?? fromEnvironment(env, "LOGLLAMA_SAMPLE_RATE", parseNumber) ?? 1;
  const batchSize = options.batchSize ?? fromEnvironment(env, "LOGLLAMA_BATCH_SIZE", parseNumber) ?? 50;
  const maxQueueSize = options.maxQueueSize ?? fromEnvironment(env, "LOGLLAMA_MAX_QUEUE_SIZE", parseNumber) ?? 10_000;

  return {
    apiKey: options.apiKey ?? (env.LOGLLAMA_API_KEY || undefined),
    endpoint: (options.endpoint ?? env.LOGLLAMA_ENDPOINT ?? "http://localhost:8000").replace(/\/+$/, ""),
    serviceName: options.serviceName ?? (env.LOGLLAMA_SERVICE_NAME || undefined),
    environment: options.environment ?? (env.LOGLLAMA_ENVIRONMENT || undefined),
    version: options.version ?? (env.LOGLLAMA_VERSION || undefined),
    gitSha: options.gitSha ?? (env.LOGLLAMA_GIT_SHA || undefined),
    tags: options.tags ?? fromEnvironment(env, "LOGLLAMA_TAGS", parseList) ?? [],
    capturePrompts: options.capturePrompts ?? fromEnvironment(env, "LOGLLAMA_CAPTURE_PROMPTS", parseBoolean) ?? true,
    captureResponses: options.captureResponses ?? fromEnvironment(env, "LOGLLAMA_CAPTURE_RESPONSES", parseBoolean) ?? true,
    redactKeys: options.redactKeys ?? fromEnvironment(env, "LOGLLAMA_REDACT_KEYS", parseList) ?? DEFAULT_REDACT_KEYS,
    maxPromptSize: options.maxPromptSize ?? fromEnvironment(env, "LOGLLAMA_MAX_PROMPT_SIZE", parseNumber),
    maxResponseSize: options.maxResponseSize ?? fromEnvironment(env, "LOGLLAMA_MAX_RESPONSE_SIZE", parseNumber),
    sampleRate: clamp(sampleRate, 0, 1),
    enabled: options.enabled ?? fromEnvironment(env, "LOGLLAMA_ENABLED", parseBoolean) ?? true,
    timeoutMs: options.timeoutMs ?? 2000,
    batchSize: Math.max(1, Math.floor(batchSize)),
    flushIntervalMs: options.flushIntervalMs ?? 1000,
    maxQueueSize: Math.max(1, Math.floor(maxQueueSize)),
  };
}
