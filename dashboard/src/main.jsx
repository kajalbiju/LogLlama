import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Ban,
  Braces,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  Coins,
  Copy,
  Database,
  Fingerprint,
  FlaskConical,
  KeyRound,
  ListTree,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const DEFAULT_RANGE = { amount: 24, unit: "hours" };
function formatMoney(value) {
  const number = Number(value || 0);
  if (number > 0 && number < 0.0001) return `$${number.toFixed(6)}`;
  return number < 0.01 ? `$${number.toFixed(4)}` : `$${number.toFixed(2)}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function compactNumber(value) {
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(Number(value || 0));
}

function display(value, fallback = "unknown") {
  return value || fallback;
}

function toMinutes(range) {
  const amount = Number(range.amount) || 1;
  if (range.unit === "minutes") return amount;
  if (range.unit === "hours") return amount * 60;
  return amount * 24 * 60;
}

function formatRangeLabel(minutes) {
  if (minutes === 1440) return "Last 24h";
  if (minutes < 60) return `Last ${minutes} min`;
  if (minutes % (24 * 60) === 0) {
    const days = minutes / (24 * 60);
    return `Last ${days} ${days === 1 ? "day" : "days"}`;
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `Last ${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  return `Last ${minutes} min`;
}

function toDateTimeInputValue(date) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60 * 1000);
  return localDate.toISOString().slice(0, 16);
}

function createDefaultAbsoluteRange() {
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  return {
    start: toDateTimeInputValue(start),
    end: toDateTimeInputValue(end),
  };
}

function formatAbsoluteRangeLabel(range) {
  const start = new Date(range.start);
  const end = new Date(range.end);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Custom range";
  const formatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${formatter.format(start)} to ${formatter.format(end)}`;
}

function privacyState(payload) {
  if (!payload) return "not captured";
  if (payload._logllama_capture === "disabled") return "disabled";
  if (payload._logllama_capture === "truncated") return "truncated";
  return "captured";
}

function BrandMark() {
  return (
    <div className="brandMark" aria-hidden="true">
      <span>LL</span>
    </div>
  );
}

function StatusPill({ status }) {
  const Icon = status === "error" || status === "rejected"
    ? XCircle
    : status === "pending"
      ? CircleDot
      : CheckCircle2;
  return (
    <span className={`status ${status}`}>
      <Icon size={12} />
      {status}
    </span>
  );
}

function MetricCard({ icon: Icon, label, value, detail, tone }) {
  return (
    <section className={`metric ${tone || ""}`}>
      <div className="metricLabel">
        <span>{label}</span>
        <Icon size={14} />
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </section>
  );
}

function SelectFilter({ label, value, options, onChange }) {
  return (
    <label className={`filterSelect ${value ? "active" : ""}`}>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function DurationControl({ value, onChange }) {
  const [draftAmount, setDraftAmount] = React.useState(String(value.amount));

  React.useEffect(() => {
    setDraftAmount(String(value.amount));
  }, [value.amount]);

  const clampAmount = (amount, unit) => {
    const max = unit === "days" ? 30 : unit === "hours" ? 720 : 43200;
    return Math.min(max, Math.max(1, Number(amount) || 1));
  };
  const commitAmount = (unit = value.unit) => {
    const amount = clampAmount(draftAmount, unit);
    setDraftAmount(String(amount));
    if (amount !== value.amount || unit !== value.unit) onChange({ amount, unit });
  };

  return (
    <div className="durationControl" aria-label="Custom time range">
      <CalendarDays size={15} />
      <span>Last</span>
      <input
        aria-label="Time range amount"
        inputMode="numeric"
        min="1"
        type="number"
        value={draftAmount}
        onBlur={() => commitAmount()}
        onChange={(event) => setDraftAmount(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      <select
        aria-label="Time range unit"
        value={value.unit}
        onChange={(event) => commitAmount(event.target.value)}
      >
        <option value="minutes">minutes</option>
        <option value="hours">hours</option>
        <option value="days">days</option>
      </select>
      <ChevronDown size={14} />
    </div>
  );
}

function TimeRangeControl({ mode, onModeChange, relativeRange, onRelativeChange, absoluteRange, onAbsoluteChange }) {
  return (
    <div className={`timeRangeControl ${mode}`}>
      <div className="rangeMode" aria-label="Time range mode">
        <button
          aria-pressed={mode === "relative"}
          className={mode === "relative" ? "active" : ""}
          type="button"
          onClick={() => onModeChange("relative")}
        >
          Last
        </button>
        <button
          aria-pressed={mode === "between"}
          className={mode === "between" ? "active" : ""}
          type="button"
          onClick={() => onModeChange("between")}
        >
          Between
        </button>
      </div>
      {mode === "relative" ? (
        <DurationControl value={relativeRange} onChange={onRelativeChange} />
      ) : (
        <div className="betweenControl" aria-label="Exact date and time range">
          <CalendarDays size={15} />
          <label>
            <span>From</span>
            <input
              aria-label="Range start"
              max={absoluteRange.end}
              type="datetime-local"
              value={absoluteRange.start}
              onChange={(event) => onAbsoluteChange({ ...absoluteRange, start: event.target.value })}
            />
          </label>
          <span className="rangeSeparator">to</span>
          <label>
            <span>To</span>
            <input
              aria-label="Range end"
              min={absoluteRange.start}
              type="datetime-local"
              value={absoluteRange.end}
              onChange={(event) => onAbsoluteChange({ ...absoluteRange, end: event.target.value })}
            />
          </label>
        </div>
      )}
    </div>
  );
}

function RequestRow({ request, selected, onSelect }) {
  const traceId = request.trace_id || request.request_id || request.external_id || request.id;
  const isError = request.status === "error" || request.status === "rejected";
  return (
    <tr
      className={`${request.status} ${selected ? "selected" : ""}`}
      onClick={() => onSelect(request)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect(request);
      }}
      tabIndex="0"
      aria-selected={selected}
    >
      <td><StatusPill status={request.status} /></td>
      <td className="timeCell" title={new Date(request.captured_at).toLocaleString()}>{formatDate(request.captured_at)}</td>
      <td>
        <div className="providerCell">
          <span className={`providerMark ${request.provider}`}>{display(request.provider, "?").slice(0, 1).toUpperCase()}</span>
          <span>
            <strong>{display(request.model)}</strong>
            <small>{display(request.provider)}</small>
          </span>
        </div>
      </td>
      <td>
        <div className="routeServiceCell">
          <code>{display(request.route || request.operation)}</code>
          <small>
            <span>{display(request.service_name, "unassigned service")}</span>
            {isError && request.error_type && <strong>{request.error_type}</strong>}
          </small>
        </div>
      </td>
      <td className="truncateCell" title={request.tenant_id}>{display(request.tenant_id, "—")}</td>
      <td className="numericCell">{Number(request.latency_ms || 0).toLocaleString()} ms</td>
      <td className="numericCell">{formatMoney(request.cost_usd)}</td>
      <td className="numericCell">{compactNumber(request.total_tokens)}</td>
      <td className="traceCell" title={traceId}>
        <div className="traceValue">
          <code>{traceId}</code>
          <CopyButton className="tableCopy" value={traceId} label="trace ID" />
        </div>
      </td>
    </tr>
  );
}

function JsonBlock({ title, value, defaultOpen = false }) {
  return (
    <details className="jsonBlock" open={defaultOpen}>
      <summary className="jsonTitle">
        <ChevronDown size={14} />
        <h3>{title}</h3>
      </summary>
      <pre>{typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}</pre>
    </details>
  );
}

function FieldGrid({ items }) {
  return (
    <dl className="fieldGrid">
      {items.map(({ label, value, mono }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className={mono ? "monoValue" : ""}>{display(value, "not set")}</dd>
        </div>
      ))}
    </dl>
  );
}

function TagList({ tags }) {
  if (!tags?.length) return <span className="mutedText">No tags</span>;
  return (
    <div className="tagList">
      {tags.map((tag) => (
        <span key={tag}>{tag}</span>
      ))}
    </div>
  );
}

function CopyButton({ value, label, className = "" }) {
  const [copied, setCopied] = React.useState(false);

  const copy = async (event) => {
    event.stopPropagation();
    await navigator.clipboard.writeText(String(value || ""));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <button
      className={`iconButton ${className}`.trim()}
      type="button"
      onClick={copy}
      disabled={!value}
      aria-label={`Copy ${label}`}
      title={copied ? `${label} copied` : `Copy ${label}`}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

function diagnosisFor(request) {
  if (request.status !== "error" && request.status !== "rejected") {
    return {
      title: "Request completed",
      hint: null,
    };
  }

  const errorText = `${request.error_type || ""} ${request.error_message || ""}`.toLowerCase();
  if (errorText.includes("model") && (errorText.includes("invalid") || errorText.includes("not found"))) {
    return {
      title: "Invalid model requested",
      hint: "Check the model name or provider routing configuration.",
    };
  }
  if (errorText.includes("api key") || errorText.includes("auth") || errorText.includes("401")) {
    return {
      title: "Provider authentication failed",
      hint: "Check the provider credential configured for this environment.",
    };
  }
  if (errorText.includes("rate") || errorText.includes("429")) {
    return {
      title: "Provider rate limit reached",
      hint: "Reduce request concurrency or review the provider account limits.",
    };
  }
  if (errorText.includes("timeout") || errorText.includes("timed out")) {
    return {
      title: "Provider request timed out",
      hint: "Review timeout settings and provider latency before retrying.",
    };
  }
  return {
    title: request.error_type || "Provider request failed",
    hint: "Review the provider error and captured request context.",
  };
}


function requestExplanations(request) {
  const inputTokens = Number(request.input_tokens || 0);
  const outputTokens = Number(request.output_tokens || 0);
  const totalTokens = Number(request.total_tokens || inputTokens + outputTokens);
  const cost = Number(request.cost_usd || 0);
  const retries = Number(request.retry_count || 0);
  const attempts = retries + 1;
  const latency = Number(request.latency_ms || 0);
  const parameters = request.model_parameters || {};
  const diagnosis = diagnosisFor(request);
  const reasoningEnabled = Boolean(
    parameters.reasoning
      || parameters.reasoning_effort
      || parameters.thinking_config
  );

  let costText;
  if (cost > 0) {
    costText = `${compactNumber(inputTokens)} input and ${compactNumber(outputTokens)} output tokens were priced for ${display(request.model)}.`;
  } else if (totalTokens > 0) {
    costText = `${compactNumber(totalTokens)} tokens were captured, but no matching model price produced an estimate.`;
  } else if (request.status === "error") {
    costText = "No billable token usage was reported before this request failed.";
  } else {
    costText = "The provider returned no token usage, so cost could not be estimated.";
  }

  const failureText = request.status === "error" || request.status === "rejected"
    ? `${diagnosis.title}. ${request.error_type ? `Provider error: ${request.error_type}.` : "No provider error type was supplied."}`
    : retries > 0
      ? `The request succeeded after ${attempts} observed attempts.`
      : "The request completed without a captured provider error or retry.";

  const latencyDrivers = [];
  if (retries > 0) latencyDrivers.push(`${attempts} attempts added repeated provider round trips`);
  if (reasoningEnabled) latencyDrivers.push("reasoning or thinking was enabled");
  if (outputTokens >= 500) latencyDrivers.push(`${compactNumber(outputTokens)} output tokens increased generation time`);
  if (!latencyDrivers.length) {
    latencyDrivers.push("no retry, reasoning, or large-output signal was captured");
  }
  const latencyText = `${latency.toLocaleString()} ms total; ${latencyDrivers.join("; ")}.`;

  return [
    { key: "cost", icon: Coins, label: "Why it cost", value: costText },
    { key: "failure", icon: AlertTriangle, label: "Why it failed", value: failureText },
    { key: "latency", icon: Clock3, label: "Why it was slow", value: latencyText },
  ];
}

function CaptureBlock({ title, value, privacy }) {
  const state = privacyState(value);
  const captureKey = title === "Prompt" ? "capture_prompts" : "capture_responses";
  const legacyCaptureKey = title === "Prompt" ? "capture_prompt" : "capture_response";
  const captureEnabled = privacy?.[captureKey] ?? privacy?.[legacyCaptureKey];
  const disabled = state === "disabled" || captureEnabled === false;
  const message = disabled
    ? `${title} capture disabled by SDK privacy settings`
    : `No ${title.toLowerCase()} captured`;

  return (
    <section className="captureSection">
      <div className="sectionTitle">
        <Braces size={15} />
        <h3>{title}</h3>
        {state === "truncated" && <span className="truncatedBadge">Truncated</span>}
      </div>
      {value && !disabled ? (
        <pre className="captureContent">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>
      ) : (
        <div className="captureDisabled">
          <ShieldCheck size={15} />
          <span>{message}</span>
        </div>
      )}
    </section>
  );
}

function RequestDetail({ request }) {
  if (!request) {
    return (
      <aside className="detailPane empty">
        <div className="emptyIcon"><ListTree size={20} /></div>
        <h2>Select a request</h2>
        <p>Choose a row to inspect its prompt, response, correlation data, and privacy settings.</p>
      </aside>
    );
  }

  const requestId = request.request_id || request.external_id || request.id;
  const traceId = request.trace_id || requestId;
  const privacy = request.privacy || {};
  const diagnosis = diagnosisFor(request);
  const explanations = requestExplanations(request);
  const isError = request.status === "error" || request.status === "rejected";

  return (
    <aside className="detailPane">
      <div className="detailHeader">
        <div>
          <span className="eyebrow">Request inspector</span>
        </div>
        <StatusPill status={request.status} />
      </div>

      <section className={`diagnosticSummary ${isError ? "error" : ""}`}>
        <span className="summaryLabel">Summary</span>
        <h2>{diagnosis.title}</h2>
        <p className="summaryModel">
          <strong>{display(request.provider)}</strong>
          <span>·</span>
          {display(request.model)}
        </p>
        <p className="summaryMetrics">
          <span>{Number(request.latency_ms || 0).toLocaleString()} ms</span>
          <span>{formatMoney(request.cost_usd)}</span>
          <span>{Number(request.total_tokens || 0).toLocaleString()} tokens</span>
        </p>
        <dl className="summaryContext">
          <div><dt>Route</dt><dd><code>{display(request.route || request.operation)}</code></dd></div>
          <div><dt>Service</dt><dd>{display(request.service_name, "not set")}</dd></div>
          <div>
            <dt>Trace</dt>
            <dd>
              <code title={traceId}>{traceId}</code>
              <CopyButton value={traceId} label="trace ID" />
            </dd>
          </div>
        </dl>
        {diagnosis.hint && (
          <div className="debugHint">
            <AlertTriangle size={14} />
            <span><strong>Debug hint</strong>{diagnosis.hint}</span>
          </div>
        )}
      </section>

      <section className="whySection">
        <div className="sectionTitle">
          <Zap size={15} />
          <h3>Why this request</h3>
        </div>
        <div className="whyList">
          {explanations.map(({ key, icon: Icon, label, value }) => (
            <div className={`whyRow ${key}`} key={key}>
              <Icon size={15} />
              <div>
                <strong>{label}</strong>
                <p>{value}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="detailSection">
        <div className="sectionTitle">
          <CircleDot size={15} />
          <h3>Request</h3>
        </div>
        <FieldGrid
          items={[
            { label: "Operation", value: request.operation },
            { label: "Provider request", value: request.provider_request_id, mono: true },
            { label: "Attempts", value: Number(request.retry_count || 0) + 1 },
            { label: "Captured", value: new Date(request.captured_at).toLocaleString() },
            { label: "Request ID", value: requestId, mono: true },
            { label: "Input / output", value: `${compactNumber(request.input_tokens)} / ${compactNumber(request.output_tokens)}` },
          ]}
        />
        {request.error_message && (
          <div className="errorBox">
            <div><AlertTriangle size={15} /><strong>{request.error_type || "Request failed"}</strong></div>
            <p>{request.error_message}</p>
          </div>
        )}
      </section>

      <section className="detailSection">
        <div className="sectionTitle">
          <Fingerprint size={15} />
          <h3>Correlation</h3>
        </div>
        <FieldGrid
          items={[
            { label: "Service", value: request.service_name },
            { label: "Environment", value: request.environment },
            { label: "Version", value: request.version },
            { label: "Git SHA", value: request.git_sha, mono: true },
            { label: "Route", value: request.route, mono: true },
            { label: "User", value: request.user_id },
            { label: "Tenant", value: request.tenant_id },
            { label: "Session", value: request.session_id, mono: true },
            { label: "Conversation", value: request.conversation_id, mono: true },
            { label: "Span", value: request.span_id, mono: true },
          ]}
        />
      </section>

      <CaptureBlock title="Prompt" value={request.prompt} privacy={privacy} />
      <CaptureBlock title="Response" value={request.response} privacy={privacy} />

      <section className="metadataSection">
        <div className="sectionTitle">
          <Database size={15} />
          <h3>Metadata</h3>
        </div>
        <div className="tagsBlock">
          <span>Tags</span>
          <TagList tags={request.tags} />
        </div>
        <JsonBlock title="Custom metadata" value={request.custom_metadata || {}} />
        <JsonBlock title="Model parameters" value={request.model_parameters || {}} />
        <JsonBlock title="Raw request metadata" value={request.request_metadata || {}} />
      </section>

      <section className="detailSection">
        <div className="sectionTitle">
          <ShieldCheck size={15} />
          <h3>Privacy</h3>
        </div>
        <div className="privacyGrid">
          <div><span>Prompt capture</span><strong>{(privacy.capture_prompts ?? privacy.capture_prompt) === false ? "Disabled" : "Enabled"}</strong></div>
          <div><span>Response capture</span><strong>{(privacy.capture_responses ?? privacy.capture_response) === false ? "Disabled" : "Enabled"}</strong></div>
          <div><span>Sample rate</span><strong>{privacy.sample_rate ?? 1}</strong></div>
          <div><span>Prompt limit</span><strong>{privacy.max_prompt_size ? `${privacy.max_prompt_size} B` : "Default"}</strong></div>
          <div><span>Response limit</span><strong>{privacy.max_response_size ? `${privacy.max_response_size} B` : "Default"}</strong></div>
          <div><span>Redacted keys</span><strong>{(privacy.redact_keys ?? privacy.redacted_keys)?.length ?? 0}</strong></div>
        </div>
      </section>
    </aside>
  );
}

async function adminFetch(path, adminKey, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-LogLlama-Admin-Key": adminKey,
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.detail || `Admin API returned ${response.status}`);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

function AdminAccessForm({ onUnlock, initialError }) {
  const [candidate, setCandidate] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(initialError || "");

  const unlock = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onUnlock(candidate);
    } catch (err) {
      setError(err.message || "Unable to verify administrator access");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="adminUnlock">
      <div>
        <span className="eyebrow">Restricted</span>
        <h2>Administrator access</h2>
        <p>Enter the administrator key for this session.</p>
      </div>
      <form onSubmit={unlock}>
        <label>
          <span>Administrator key</span>
          <input
            type="password"
            value={candidate}
            onChange={(event) => setCandidate(event.target.value)}
            minLength="32"
            autoComplete="current-password"
            autoFocus
            required
          />
        </label>
        <button className="primaryCommand" type="submit" disabled={busy || candidate.length < 32}>
          <LockKeyhole size={16} />
          <span>{busy ? "Verifying" : "Unlock"}</span>
        </button>
      </form>
      {error && <div className="banner">{error}</div>}
    </section>
  );
}

function AdminHeaderActions({ onRefresh, onLock }) {
  return (
    <div className="adminHeaderActions">
      <button className="iconCommand" type="button" onClick={onRefresh} aria-label="Refresh" title="Refresh">
        <RefreshCw size={16} />
      </button>
      <button className="iconCommand" type="button" onClick={onLock} aria-label="Lock admin session" title="Lock admin session">
        <LockKeyhole size={16} />
      </button>
    </div>
  );
}

function ProviderCredentialsAdmin({ adminKey, onUnauthorized, onLock }) {
  const [credentials, setCredentials] = React.useState([]);
  const [backend, setBackend] = React.useState("");
  const [provider, setProvider] = React.useState("openai");
  const [name, setName] = React.useState("default");
  const [apiKey, setApiKey] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const payload = await adminFetch("/api/admin/provider-credentials", adminKey);
      setCredentials(payload.credentials || []);
      setBackend(payload.secret_backend || "");
      setError("");
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err.message || "Unable to load provider credentials");
    }
  }, [adminKey, onUnauthorized]);

  React.useEffect(() => {
    load();
  }, [load]);

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await adminFetch("/api/admin/provider-credentials", adminKey, {
        method: "POST",
        body: JSON.stringify({ provider, name, api_key: apiKey }),
      });
      setApiKey("");
      await load();
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err.message || "Unable to save credential");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (credential) => {
    if (!window.confirm(`Remove the ${credential.provider} credential "${credential.name}"?`)) return;
    setBusy(true);
    try {
      await adminFetch(`/api/admin/provider-credentials/${credential.id}`, adminKey, { method: "DELETE" });
      await load();
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err.message || "Unable to remove credential");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="adminWorkspace">
      {error && <div className="banner">{error}</div>}
      <div className="adminIntro">
        <div>
          <span className="eyebrow">Secret backend: {backend || "loading"}</span>
          <h2>Provider credentials</h2>
          <p>Keys are write-only here. The database keeps a reference and fingerprint, not the key value.</p>
        </div>
        <AdminHeaderActions onRefresh={load} onLock={onLock} />
      </div>

      <form className="credentialForm" onSubmit={save}>
        <label>
          <span>Provider</span>
          <select value={provider} onChange={(event) => setProvider(event.target.value)}>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="gemini">Gemini</option>
            <option value="cursor">Cursor SDK</option>
          </select>
        </label>
        <label>
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength="120" required />
        </label>
        <label className="secretInput">
          <span>API key / PAT</span>
          <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} minLength="8" autoComplete="new-password" required />
        </label>
        <button className="primaryCommand" type="submit" disabled={busy || apiKey.length < 8}>
          <KeyRound size={16} />
          <span>{busy ? "Saving" : "Store key"}</span>
        </button>
      </form>

      <div className="adminTable">
        <div className="adminTableHeader credentialColumns">
          <span>Provider</span><span>Name</span><span>Fingerprint</span><span>Version</span><span>Status</span><span />
        </div>
        {credentials.map((credential) => (
          <div className="adminTableRow credentialColumns" key={credential.id}>
            <strong>{credential.provider}</strong>
            <span>{credential.name}</span>
            <code>{credential.fingerprint}</code>
            <span>v{credential.version}</span>
            <StatusPill status={credential.status} />
            <button className="dangerIcon" type="button" onClick={() => remove(credential)} disabled={busy} aria-label={`Remove ${credential.provider} credential`} title="Remove credential">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        {!credentials.length && <div className="emptyList">No managed provider credentials</div>}
      </div>
    </section>
  );
}

function TestPlansAdmin({ adminKey, onUnauthorized, onLock }) {
  const [plans, setPlans] = React.useState([]);
  const [busyId, setBusyId] = React.useState("");
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const payload = await adminFetch("/api/admin/test-plans", adminKey);
      setPlans(payload.test_plans || []);
      setError("");
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err.message || "Unable to load test plans");
    }
  }, [adminKey, onUnauthorized]);

  React.useEffect(() => {
    load();
  }, [load]);

  const decide = async (plan, decision) => {
    setBusyId(plan.id);
    try {
      await adminFetch(`/api/admin/test-plans/${plan.id}/${decision}`, adminKey, {
        method: "POST",
        body: JSON.stringify({
          expires_in_hours: 24,
          reason: decision === "reject" ? "Rejected by administrator" : null,
        }),
      });
      await load();
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err.message || `Unable to ${decision} test plan`);
    } finally {
      setBusyId("");
    }
  };

  return (
    <section className="adminWorkspace">
      {error && <div className="banner">{error}</div>}
      <div className="adminIntro">
        <div>
          <span className="eyebrow">Cost control</span>
          <h2>Provider comparison approvals</h2>
          <p>Approval applies to the exact prompt, provider/model targets, and output limit shown below.</p>
        </div>
        <AdminHeaderActions onRefresh={load} onLock={onLock} />
      </div>

      <div className="testPlanList">
        {plans.map((plan) => (
          <article className="testPlan" key={plan.id}>
            <header>
              <div>
                <span className="eyebrow">{formatDate(plan.created_at)}</span>
                <h3>{plan.targets.map((target) => target.provider).join(" vs ")}</h3>
              </div>
              <StatusPill status={plan.status} />
            </header>
            <pre className="promptPreview">{plan.prompt}</pre>
            <div className="targetList">
              {plan.targets.map((target) => (
                <span key={`${target.provider}:${target.model}`}>
                  <strong>{target.provider}</strong>
                  <code>{target.model}</code>
                </span>
              ))}
            </div>
            <footer>
              <span>Maximum output: {plan.max_output_tokens} tokens per provider / runs: {plan.run_count} of {plan.max_runs}</span>
              {plan.status === "pending" && (
                <div className="decisionActions">
                  <button className="rejectCommand" type="button" onClick={() => decide(plan, "reject")} disabled={busyId === plan.id}>
                    <Ban size={15} /><span>Reject</span>
                  </button>
                  <button className="approveCommand" type="button" onClick={() => decide(plan, "approve")} disabled={busyId === plan.id}>
                    <Check size={15} /><span>Approve 24h</span>
                  </button>
                </div>
              )}
            </footer>
          </article>
        ))}
        {!plans.length && <div className="emptyList">No comparison requests awaiting review</div>}
      </div>
    </section>
  );
}

function App() {
  const [view, setView] = React.useState("traces");
  const [adminKey, setAdminKey] = React.useState("");
  const [adminError, setAdminError] = React.useState("");
  const [summary, setSummary] = React.useState(null);
  const [requests, setRequests] = React.useState([]);
  const [facets, setFacets] = React.useState({});
  const [selected, setSelected] = React.useState(null);
  const [query, setQuery] = React.useState("");
  const deferredQuery = React.useDeferredValue(query.trim());
  const [timeMode, setTimeMode] = React.useState("relative");
  const [timeRange, setTimeRange] = React.useState(DEFAULT_RANGE);
  const [absoluteRange, setAbsoluteRange] = React.useState(createDefaultAbsoluteRange);
  const [filters, setFilters] = React.useState({
    provider: "",
    environment: "",
    service_name: "",
    tenant_id: "",
    route: "",
    model: "",
    status: "",
  });
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (timeMode === "between") {
        const start = new Date(absoluteRange.start);
        const end = new Date(absoluteRange.end);
        if (!absoluteRange.start || !absoluteRange.end || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
          throw new Error("Choose both a start and end date");
        }
        if (start >= end) throw new Error("Start must be earlier than end");
        params.set("start", start.toISOString());
        params.set("end", end.toISOString());
      } else {
        params.set("minutes", String(toMinutes(timeRange)));
      }
      Object.entries(filters).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      if (deferredQuery) params.set("q", deferredQuery);

      const summaryParams = new URLSearchParams(params);
      summaryParams.delete("limit");

      const facetParams = new URLSearchParams(params);
      facetParams.delete("limit");

      const [summaryResponse, requestResponse, facetsResponse] = await Promise.all([
        fetch(`${API_BASE}/api/metrics/summary?${summaryParams.toString()}`),
        fetch(`${API_BASE}/api/requests?${params.toString()}`),
        fetch(`${API_BASE}/api/metadata/facets?${facetParams.toString()}`),
      ]);
      if (!summaryResponse.ok || !requestResponse.ok || !facetsResponse.ok) {
        throw new Error("Backend returned an error");
      }
      const summaryJson = await summaryResponse.json();
      const requestJson = await requestResponse.json();
      const facetsJson = await facetsResponse.json();
      const nextRequests = requestJson.requests || [];
      setSummary(summaryJson);
      setRequests(nextRequests);
      setFacets(facetsJson);
      setSelected((current) => nextRequests.find((request) => request.id === current?.id) || nextRequests[0] || null);
    } catch (err) {
      setError(err.message || "Unable to load LogLlama data");
    } finally {
      setLoading(false);
    }
  }, [absoluteRange, deferredQuery, filters, timeMode, timeRange]);

  React.useEffect(() => {
    if (view !== "traces") return undefined;
    load();
    if (timeMode === "between") return undefined;
    const interval = window.setInterval(load, 10000);
    return () => window.clearInterval(interval);
  }, [load, timeMode, view]);

  React.useEffect(() => {
    const focusSearch = (event) => {
      if (event.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
        event.preventDefault();
        document.getElementById("requestSearch")?.focus();
      }
      if (event.key === "Escape" && document.activeElement?.id === "requestSearch") {
        document.activeElement.blur();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  const filtered = requests;
  const activeFilterCount = Object.values(filters).filter(Boolean).length + (deferredQuery ? 1 : 0);
  const setFilter = (key, value) => setFilters((current) => ({ ...current, [key]: value }));
  const resetFilters = () => {
    setQuery("");
    setTimeMode("relative");
    setTimeRange(DEFAULT_RANGE);
    setFilters({
      provider: "",
      environment: "",
      service_name: "",
      tenant_id: "",
      route: "",
      model: "",
      status: "",
    });
  };
  const rangeMinutes = toMinutes(timeRange);
  const rangeLabel = timeMode === "between"
    ? formatAbsoluteRangeLabel(absoluteRange)
    : formatRangeLabel(rangeMinutes);
  const scopeRangeLabel = timeMode === "between"
    ? rangeLabel
    : rangeLabel.replace("Last ", "").toLowerCase();
  const failureCount = Math.round((summary?.error_rate || 0) * (summary?.total_requests || 0));
  const unlockAdmin = React.useCallback(async (candidate) => {
    await adminFetch("/api/admin/provider-credentials", candidate);
    setAdminKey(candidate);
    setAdminError("");
  }, []);
  const lockAdmin = React.useCallback(() => {
    setAdminKey("");
    setAdminError("");
  }, []);
  const rejectAdminSession = React.useCallback(() => {
    setAdminKey("");
    setAdminError("Administrator access was rejected. Enter the current key.");
  }, []);
  const activeChips = [
    ...Object.entries(filters)
      .filter(([, value]) => value)
      .map(([key, value]) => ({
        key,
        label: key === "service_name" ? "service" : key === "tenant_id" ? "tenant" : key,
        value,
      })),
    ...(deferredQuery ? [{ key: "query", label: "search", value: deferredQuery }] : []),
  ];

  return (
    <main className="appShell">
      <header className="appTopbar">
        <div className="topbarPrimary">
          <a className="brand compact" href="#" aria-label="LogLlama home">
            <BrandMark />
            <strong>LogLlama</strong>
          </a>
          <div className="topbarDivider" />
          <div className="projectSwitcher">
            <span className="projectIcon">D</span>
            <strong>Default project <span>/ production</span></strong>
          </div>
          <nav className="viewTabs" aria-label="Console views">
            <button className={view === "traces" ? "active" : ""} type="button" onClick={() => setView("traces")}>
              <ListTree size={15} /><span>Requests</span>
            </button>
            <button className={view === "credentials" ? "active" : ""} type="button" onClick={() => setView("credentials")}>
              <KeyRound size={15} /><span>Providers</span>
            </button>
            <button className={view === "tests" ? "active" : ""} type="button" onClick={() => setView("tests")}>
              <FlaskConical size={15} /><span>Tests</span>
            </button>
          </nav>
        </div>
        <div className="topbarUtility">
          {view === "traces" && (
            <>
              <span className={`liveIndicator ${timeMode === "between" ? "fixed" : ""}`}>
                <span /> {timeMode === "between" ? "Fixed" : "Live"} · {rangeLabel}
              </span>
              <button className="refreshCommand" type="button" onClick={load} aria-label="Refresh data" title="Refresh data">
                <RefreshCw className={loading ? "spinning" : ""} size={15} />
                <span>Refresh</span>
              </button>
            </>
          )}
        </div>
      </header>

      <section className="content">
        <div className="pageHeading">
          <div>
            <h1>{view === "traces" ? "Requests" : view === "credentials" ? "Provider credentials" : "Test approvals"}</h1>
            <p>
              {view === "traces"
                ? `${summary?.total_requests ?? 0} requests · ${failureCount} failures · ${rangeLabel}`
                : view === "credentials"
                  ? "Manage write-only provider credentials."
                  : "Review provider comparison runs before they spend."}
            </p>
          </div>
        </div>

        {view === "traces" && (
          <>
            <section className="queryPanel" aria-label="Request filters">
              <div className="queryPrimary">
                <label className="search">
                  <Search size={16} />
                  <input
                    id="requestSearch"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search trace, tenant, route, model, request ID…"
                    aria-label="Search requests"
                  />
                  <kbd>/</kbd>
                </label>
                <TimeRangeControl
                  mode={timeMode}
                  onModeChange={setTimeMode}
                  relativeRange={timeRange}
                  onRelativeChange={setTimeRange}
                  absoluteRange={absoluteRange}
                  onAbsoluteChange={setAbsoluteRange}
                />
              </div>
              <div className="filterBar">
                <SelectFilter label="Provider" value={filters.provider} options={facets.providers || []} onChange={(value) => setFilter("provider", value)} />
                <SelectFilter label="Model" value={filters.model} options={facets.models || []} onChange={(value) => setFilter("model", value)} />
                <SelectFilter label="Status" value={filters.status} options={facets.statuses || []} onChange={(value) => setFilter("status", value)} />
                <SelectFilter label="Environment" value={filters.environment} options={facets.environments || []} onChange={(value) => setFilter("environment", value)} />
                <SelectFilter label="Service" value={filters.service_name} options={facets.service_names || []} onChange={(value) => setFilter("service_name", value)} />
                <SelectFilter label="Route" value={filters.route} options={facets.routes || []} onChange={(value) => setFilter("route", value)} />
                <SelectFilter label="Tenant" value={filters.tenant_id} options={facets.tenant_ids || []} onChange={(value) => setFilter("tenant_id", value)} />
              </div>
              <div className="activeFilters">
                <span className="scopeReadout"><Clock3 size={12} /><strong>time:</strong> {scopeRangeLabel}</span>
                <span className="scopeReadout"><strong>model:</strong> {filters.model || "all"}</span>
                <span className="scopeReadout"><strong>status:</strong> {filters.status || "all"}</span>
                {activeChips.map((chip) => (
                  <span className="filterChip" key={chip.key}>
                    <span>{chip.label}:</span> {chip.value}
                    <button
                      type="button"
                      aria-label={`Remove ${chip.label} filter`}
                      onClick={() => chip.key === "query" ? setQuery("") : setFilter(chip.key, "")}
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
                {activeFilterCount > 0 && (
                  <button className="clearFilters" type="button" onClick={resetFilters}>Clear filters</button>
                )}
              </div>
            </section>

            <section className="metricsGrid">
              <MetricCard icon={Activity} label="Requests" value={(summary?.total_requests ?? 0).toLocaleString()} detail={`${rangeLabel} · current scope`} />
              <MetricCard icon={Coins} label="Total cost" value={formatMoney(summary?.total_cost_usd)} detail="Estimated from captured usage" />
              <MetricCard icon={Zap} label="Average latency" value={`${Math.round(summary?.avg_latency_ms || 0).toLocaleString()} ms`} detail="End-to-end model call" />
              <MetricCard
                icon={AlertTriangle}
                label="Error rate"
                value={`${Math.round((summary?.error_rate || 0) * 100)}%`}
                detail={`${Math.round((summary?.error_rate || 0) * (summary?.total_requests || 0))} failed requests`}
                tone={summary?.error_rate ? "warning" : ""}
              />
              <MetricCard icon={Database} label="Total tokens" value={compactNumber(summary?.total_tokens)} detail="Input and output combined" />
            </section>

            <section className="workspace">
              <div className="requestPanel">
                <div className="panelHeader">
                  <div>
                    <h2>Request stream</h2>
                    <p>{loading ? "Refreshing requests…" : `Filtered to ${filtered.length} request${filtered.length === 1 ? "" : "s"}`}</p>
                  </div>
                  <span className="resultLimit">Newest 100</span>
                </div>
                <div className="tableScroll">
                  <table className="requestTable">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Time</th>
                        <th>Provider / model</th>
                        <th>Route / service</th>
                        <th>Tenant</th>
                        <th className="numericCell">Latency</th>
                        <th className="numericCell">Cost</th>
                        <th className="numericCell">Tokens</th>
                        <th>Trace ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((request) => (
                        <RequestRow key={request.id} request={request} selected={selected?.id === request.id} onSelect={setSelected} />
                      ))}
                    </tbody>
                  </table>
                  {loading && !filtered.length && (
                    <div className="tableState loadingState" aria-live="polite">
                      {[0, 1, 2, 3, 4].map((item) => <span className="skeletonRow" key={item} />)}
                    </div>
                  )}
                  {!loading && error && !filtered.length && (
                    <div className="tableState">
                      <div className="stateIcon error"><AlertTriangle size={18} /></div>
                      <h3>Couldn’t load requests</h3>
                      <p>{error}. Check the API connection and try again.</p>
                      <button className="retryButton" type="button" onClick={load}><RefreshCw size={14} /> Retry</button>
                    </div>
                  )}
                  {!loading && !error && !filtered.length && (
                    <div className="tableState">
                      <div className="stateIcon"><Search size={18} /></div>
                      <h3>No requests found</h3>
                      <p>No LLM calls match this query in the selected time range.</p>
                      <div className="stateActions">
                        {activeFilterCount > 0 && <button className="retryButton" type="button" onClick={resetFilters}>Clear filters</button>}
                        <button
                          className="retryButton"
                          type="button"
                          onClick={() => {
                            setTimeMode("relative");
                            setTimeRange(DEFAULT_RANGE);
                          }}
                        >
                          Last 24h
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <RequestDetail request={selected} />
            </section>
          </>
        )}
        {view === "credentials" && (
          adminKey
            ? <ProviderCredentialsAdmin adminKey={adminKey} onUnauthorized={rejectAdminSession} onLock={lockAdmin} />
            : <AdminAccessForm onUnlock={unlockAdmin} initialError={adminError} />
        )}
        {view === "tests" && (
          adminKey
            ? <TestPlansAdmin adminKey={adminKey} onUnauthorized={rejectAdminSession} onLock={lockAdmin} />
            : <AdminAccessForm onUnlock={unlockAdmin} initialError={adminError} />
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
