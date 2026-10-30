import { describe, expect, it } from "vitest";

import { preparePayload, redactValue } from "../src/redact.js";


describe("redactValue", () => {
  it("masks sensitive keys at any depth without touching other values", () => {
    const redacted = redactValue(
      { user: { name: "Ada", Authorization: "Bearer x", nested: [{ password: "p" }] }, count: 2 },
      ["authorization", "password"],
    );

    expect(redacted).toEqual({
      user: { name: "Ada", Authorization: "[REDACTED]", nested: [{ password: "[REDACTED]" }] },
      count: 2,
    });
  });
});

describe("preparePayload", () => {
  it("truncates payloads larger than the configured size", () => {
    const prepared = preparePayload("x".repeat(100), { enabled: true, maxSize: 20, redactKeys: [] });

    expect(prepared).toMatchObject({ _logllama_capture: "truncated", original_length: 102 });
  });

  it("returns a disabled marker when capture is off", () => {
    expect(preparePayload({ anything: true }, { enabled: false, maxSize: undefined, redactKeys: [] })).toEqual({
      _logllama_capture: "disabled",
    });
  });

  it("returns null for missing values", () => {
    expect(preparePayload(undefined, { enabled: true, maxSize: undefined, redactKeys: [] })).toBeNull();
  });
});
