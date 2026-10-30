import { randomUUID } from "node:crypto";

import type { ResolvedConfig } from "./config.js";
import { currentContext } from "./context.js";
import { preparePayload } from "./redact.js";
import type { LogLlamaEvent } from "./transport.js";

export const CORRELATION_FIELDS = [
  "service_name",
  "environment",
  "version",
  "git_sha",
  "route",
  "user_id",
  "tenant_id",
  "session_id",
  "conversation_id",
  "request_id",
  "trace_id",
  "span_id",
  "prompt_template",
  "prompt_version",
] as const;

export interface CallRecord {
  provider: "openai" | "anthropic" | "gemini";
  operation: string;
  model: string | undefined;
  providerRequestId: string | null | undefined;
  modelParameters: Record<string, unknown>;
  prompt: unknown;
  response: unknown;
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
  status: "success" | "error";
  error: { type: string; message: string } | undefined;
  metadata: Record<string, unknown>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Builds the wire format the backend expects. Field names match the Python SDK. */
export function buildEvent(config: ResolvedConfig, record: CallRecord, now: Date): LogLlamaEvent {
  const merged: Record<string, unknown> = { ...currentContext(), ...record.metadata };
  const defaults: Record<string, unknown> = {
    service_name: config.serviceName,
    environment: config.environment,
    version: config.version,
    git_sha: config.gitSha,
  };

  const correlation: Record<string, unknown> = {};
  for (const field of CORRELATION_FIELDS) {
    correlation[field] = merged[field] ?? defaults[field] ?? null;
  }

  const customMetadata: Record<string, unknown> = {
    ...(isRecord(merged.custom_metadata) ? merged.custom_metadata : {}),
  };
  for (const [key, value] of Object.entries(merged)) {
    if (key === "tags" || key === "custom_metadata" || (CORRELATION_FIELDS as readonly string[]).includes(key)) continue;
    customMetadata[key] ??= value;
  }

  const redactKeys = config.redactKeys;
  const inputTokens = record.inputTokens;
  const outputTokens = record.outputTokens;

  return {
    external_id: `llreq_${randomUUID().replaceAll("-", "")}`,
    provider: record.provider,
    operation: record.operation,
    model: record.model ?? null,
    provider_request_id: record.providerRequestId ?? null,
    retry_count: 0,
    model_parameters: record.modelParameters,
    status: record.status,
    prompt: preparePayload(record.prompt, {
      enabled: config.capturePrompts,
      maxSize: config.maxPromptSize,
      redactKeys,
    }),
    response:
      record.status === "success"
        ? preparePayload(record.response, {
            enabled: config.captureResponses,
            maxSize: config.maxResponseSize,
            redactKeys,
          })
        : null,
    usage: {
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
    },
    latency_ms: record.latencyMs,
    error: record.error ?? null,
    ...correlation,
    tags: [...config.tags, ...(Array.isArray(merged.tags) ? merged.tags : [])],
    custom_metadata: customMetadata,
    privacy: {
      sample_rate: config.sampleRate,
      capture_prompts: config.capturePrompts,
      capture_responses: config.captureResponses,
    },
    captured_at: now.toISOString(),
  };
}
