import { AsyncLocalStorage } from "node:async_hooks";


export type LogLlamaContext = Record<string, unknown>;

const storage = new AsyncLocalStorage<LogLlamaContext>();

/** Attach correlation metadata to every event captured inside `fn`, including across awaits. */
export function context<T>(metadata: LogLlamaContext, fn: () => T): T {
  const merged: LogLlamaContext = { ...(storage.getStore() ?? {}) };
  for (const [key, value] of Object.entries(metadata)) {
    if (value !== undefined) merged[key] = value;
  }
  return storage.run(merged, fn);
}

export function currentContext(): LogLlamaContext {
  return storage.getStore() ?? {};
}
