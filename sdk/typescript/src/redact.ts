const MAX_DEPTH = 20;

export function redactValue(value: unknown, redactKeys: readonly string[], depth = 0): unknown {
  if (depth > MAX_DEPTH) return "[TRUNCATED_DEPTH]";
  if (Array.isArray(value)) {
    return value.map((item) => redactValue(item, redactKeys, depth + 1));
  }
  if (value !== null && typeof value === "object") {
    const redacted: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      redacted[key] = isSensitiveKey(key, redactKeys) ? "[REDACTED]" : redactValue(item, redactKeys, depth + 1);
    }
    return redacted;
  }
  return value;
}

function isSensitiveKey(key: string, redactKeys: readonly string[]): boolean {
  const lowered = key.toLowerCase();
  return redactKeys.some((candidate) => lowered.includes(candidate.toLowerCase()));
}

// Key-shaped values in free text, such as provider error messages. Kept in line with the Python SDK's redaction.py.
const SECRET_PATTERNS: RegExp[] = [
  /\bsk-[A-Za-z0-9_*-]{6,}/g,
  /\bAIza[0-9A-Za-z_*-]{8,}/g,
  /\b(?:llm|llrt)_[A-Za-z0-9_*-]{8,}/g,
  /\bBearer\s+[A-Za-z0-9._~+\/=*-]{8,}/gi,
];
const ASSIGNMENT_PATTERN = /\b(api[_-]?key|authorization|password|secret)(\s*[:=]\s*)(['"]?)[^\s'",;&]+/gi;

/** Removes key-shaped values from free text before it is recorded. Ordinary text is returned unchanged. */
export function redactText(value: string): string {
  let redacted = value;
  for (const pattern of SECRET_PATTERNS) {
    redacted = redacted.replace(pattern, "[REDACTED]");
  }
  return redacted.replace(ASSIGNMENT_PATTERN, "$1$2$3[REDACTED]");
}

/** Returns the value, a truncation marker for oversized payloads, or a disabled marker when capture is off. */
export function preparePayload(
  value: unknown,
  options: { enabled: boolean; maxSize: number | undefined; redactKeys: readonly string[] },
): unknown {
  if (!options.enabled) return { _logllama_capture: "disabled" };
  if (value === undefined) return null;

  const redacted = redactValue(value, options.redactKeys);
  const serialized = JSON.stringify(redacted) ?? "null";
  if (options.maxSize !== undefined && serialized.length > options.maxSize) {
    return {
      _logllama_capture: "truncated",
      original_length: serialized.length,
      preview: serialized.slice(0, options.maxSize),
    };
  }
  return redacted;
}
