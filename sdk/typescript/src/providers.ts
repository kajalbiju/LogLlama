import { captureCall } from "./client.js";
import type { CallRecord } from "./capture.js";
import { redactText } from "./redact.js";


type Args = unknown[];
type Invoke = (args: Args) => unknown;

interface CallSpec {
  provider: CallRecord["provider"];
  operation: string;
  request: (params: Record<string, unknown>) => {
    model: string | undefined;
    prompt: unknown;
    modelParameters: Record<string, unknown>;
  };
  response: (response: unknown) => {
    model: string | undefined;
    providerRequestId: string | null | undefined;
    response: unknown;
    inputTokens: number;
    outputTokens: number;
  };
}

const WRAPPED = Symbol.for("logllama.wrapped");
const METADATA_KEY = "logllama_metadata";

const OPENAI_CHAT_PARAMETERS = ["temperature", "top_p", "max_tokens", "max_completion_tokens", "reasoning_effort", "seed", "stop"];
const OPENAI_RESPONSES_PARAMETERS = ["temperature", "top_p", "max_output_tokens", "reasoning", "text"];
const ANTHROPIC_PARAMETERS = ["max_tokens", "temperature", "top_p", "top_k", "stop_sequences"];
const GEMINI_PARAMETERS = ["temperature", "topP", "topK", "maxOutputTokens", "candidateCount", "stopSequences", "thinkingConfig"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function pick(source: Record<string, unknown>, keys: readonly string[]): Record<string, unknown> {
  const picked: Record<string, unknown> = {};
  for (const key of keys) {
    if (source[key] !== undefined) picked[key] = source[key];
  }
  return picked;
}

function firstChoiceText(response: Record<string, unknown>): string | null {
  const choices = response.choices;
  if (!Array.isArray(choices)) return null;
  return asString(asRecord(asRecord(choices[0]).message).content) ?? null;
}

function textBlocks(content: unknown): string | null {
  if (!Array.isArray(content)) return null;
  return content
    .filter((block) => asRecord(block).type === "text")
    .map((block) => asString(asRecord(block).text) ?? "")
    .join("");
}

function splitMetadata(args: Args): { args: Args; metadata: Record<string, unknown> } {
  const [params, ...rest] = args;
  if (!isRecord(params)) return { args, metadata: {} };
  const { [METADATA_KEY]: metadata, ...providerParams } = params;
  return {
    args: [providerParams, ...rest],
    metadata: isRecord(metadata) ? metadata : {},
  };
}

function errorName(error: unknown): string {
  return error instanceof Error ? error.constructor.name : "Error";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function elapsedMs(start: number): number {
  return Math.max(0, Math.round(performance.now() - start));
}

/** Replaces `owner[name]` in place, the same way the Python SDK instruments provider clients. */
function wrapMethod(owner: unknown, name: string, handler: (args: Args, invoke: Invoke) => Promise<unknown>): void {
  if (!isRecord(owner)) return;
  const original = owner[name];
  if (typeof original !== "function" || (original as unknown as Record<symbol, unknown>)[WRAPPED]) return;

  const invoke: Invoke = (args) => (original as (...values: unknown[]) => unknown).apply(owner, args);
  const wrapped = function (...args: Args): Promise<unknown> {
    return handler(args, invoke);
  };
  Object.defineProperty(wrapped, WRAPPED, { value: true });
  owner[name] = wrapped;
}

async function instrumentCall(spec: CallSpec, args: Args, invoke: Invoke): Promise<unknown> {
  const split = splitMetadata(args);
  const params = asRecord(split.args[0]);

  // Streamed responses are returned untouched. Capturing them needs a stream-aware wrapper, which is not built yet.
  if (params.stream === true) return invoke(split.args);

  const request = spec.request(params);
  const start = performance.now();
  let response: unknown;
  try {
    response = await invoke(split.args);
  } catch (error) {
    captureCall({
      provider: spec.provider,
      operation: spec.operation,
      model: request.model,
      providerRequestId: null,
      modelParameters: request.modelParameters,
      prompt: request.prompt,
      response: null,
      inputTokens: 0,
      outputTokens: 0,
      latencyMs: elapsedMs(start),
      status: "error",
      error: { type: errorName(error), message: redactText(errorMessage(error)) },
      metadata: split.metadata,
    });
    throw error;
  }

  const result = spec.response(response);
  captureCall({
    provider: spec.provider,
    operation: spec.operation,
    model: result.model ?? request.model,
    providerRequestId: result.providerRequestId,
    modelParameters: request.modelParameters,
    prompt: request.prompt,
    response: result.response,
    inputTokens: result.inputTokens,
    outputTokens: result.outputTokens,
    latencyMs: elapsedMs(start),
    status: "success",
    error: undefined,
    metadata: split.metadata,
  });
  return response;
}

/** Instruments `chat.completions.create` and `responses.create` on an OpenAI client. */
export function wrapOpenAI<T extends object>(client: T): T {
  const root = client as Record<string, unknown>;
  wrapMethod(asRecord(root.chat).completions, "create", (args, invoke) =>
    instrumentCall(
      {
        provider: "openai",
        operation: "chat.completions.create",
        request: (params) => ({
          model: asString(params.model),
          prompt: params.messages,
          modelParameters: pick(params, OPENAI_CHAT_PARAMETERS),
        }),
        response: (response) => {
          const body = asRecord(response);
          const usage = asRecord(body.usage);
          return {
            model: asString(body.model),
            providerRequestId: asString(body.id) ?? null,
            response: firstChoiceText(body),
            inputTokens: asCount(usage.prompt_tokens),
            outputTokens: asCount(usage.completion_tokens),
          };
        },
      },
      args,
      invoke,
    ),
  );
  wrapMethod(root.responses, "create", (args, invoke) =>
    instrumentCall(
      {
        provider: "openai",
        operation: "responses.create",
        request: (params) => ({
          model: asString(params.model),
          prompt: params.input,
          modelParameters: pick(params, OPENAI_RESPONSES_PARAMETERS),
        }),
        response: (response) => {
          const body = asRecord(response);
          const usage = asRecord(body.usage);
          return {
            model: asString(body.model),
            providerRequestId: asString(body.id) ?? null,
            response: asString(body.output_text) ?? null,
            inputTokens: asCount(usage.input_tokens),
            outputTokens: asCount(usage.output_tokens),
          };
        },
      },
      args,
      invoke,
    ),
  );
  return client;
}

/** Instruments `messages.create` on an Anthropic client. */
export function wrapAnthropic<T extends object>(client: T): T {
  wrapMethod(asRecord(client).messages, "create", (args, invoke) =>
    instrumentCall(
      {
        provider: "anthropic",
        operation: "messages.create",
        request: (params) => ({
          model: asString(params.model),
          prompt: { system: params.system, messages: params.messages },
          modelParameters: pick(params, ANTHROPIC_PARAMETERS),
        }),
        response: (response) => {
          const body = asRecord(response);
          const usage = asRecord(body.usage);
          return {
            model: asString(body.model),
            providerRequestId: asString(body.id) ?? null,
            response: textBlocks(body.content),
            inputTokens: asCount(usage.input_tokens),
            outputTokens: asCount(usage.output_tokens),
          };
        },
      },
      args,
      invoke,
    ),
  );
  return client;
}

/** Instruments `models.generateContent` on a `@google/genai` client. */
export function wrapGemini<T extends object>(client: T): T {
  wrapMethod(asRecord(client).models, "generateContent", (args, invoke) =>
    instrumentCall(
      {
        provider: "gemini",
        operation: "models.generate_content",
        request: (params) => ({
          model: asString(params.model),
          prompt: params.contents,
          modelParameters: pick(asRecord(params.config), GEMINI_PARAMETERS),
        }),
        response: (response) => {
          const body = asRecord(response);
          const usage = asRecord(body.usageMetadata);
          return {
            model: asString(body.modelVersion),
            providerRequestId: asString(body.responseId) ?? null,
            // `text` is a getter on the SDK response object, so it is read through the record.
            response: asString(body.text) ?? null,
            inputTokens: asCount(usage.promptTokenCount),
            outputTokens: asCount(usage.candidatesTokenCount),
          };
        },
      },
      args,
      invoke,
    ),
  );
  return client;
}
