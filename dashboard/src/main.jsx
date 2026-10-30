import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Ban,
  Braces,
  CalendarDays,
  Check,
  Clock3,
  Coins,
  Copy,
  Fingerprint,
  FlaskConical,
  GitCommit,
  KeyRound,
  ListTree,
  LockKeyhole,
  LogOut,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from "lucide-react";
import "./styles.css";

// Empty means same origin, which the Vite dev server (and any reverse proxy in production) forwards to the API.
// Set VITE_API_BASE_URL only when the API is served from a different origin, and then include the CORS origin.
const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const CSRF_HEADERS = { "X-LogLlama-Request": "1" };
const DEFAULT_RANGE = { amount: 24, unit: "hours" };
const RANGE_PRESETS = [
  { label: "5m", minutes: 5 },
  { label: "30m", minutes: 30 },
  { label: "1h", minutes: 60 },
  { label: "6h", minutes: 360 },
  { label: "24h", minutes: 1440 },
  { label: "7d", minutes: 10080 },
];
const EMPTY_FILTERS = {
  environment: "",
  service_name: "",
  tenant_id: "",
  route: "",
  model: "",
  status: "",
};

// Mirrors ROLE_PERMISSIONS in backend/app/deps.py. The UI uses it only to show or hide controls;
// the backend enforces every permission.
const ROLE_PERMISSIONS = {
  viewer: ["data:read"],
  developer: ["data:read", "keys:manage", "projects:manage"],
  test_approver: ["data:read", "tests:approve"],
  credential_admin: ["data:read", "credentials:manage"],
  owner: ["data:read", "keys:manage", "projects:manage", "tests:approve", "credentials:manage", "members:manage"],
};
const ROLE_LABELS = {
  owner: "Owner",
  credential_admin: "Credential admin",
  test_approver: "Test approver",
  developer: "Developer",
  viewer: "Viewer",
};

function can(role, permission) {
  return (ROLE_PERMISSIONS[role] || []).includes(permission);
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function apiFetch(path, { method = "GET", body, params } = {}) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  });

  const init = { method, credentials: "include", headers: method === "GET" ? {} : { ...CSRF_HEADERS } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const response = await fetch(url, init);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg).join("; ")
      : payload.detail;
    throw new ApiError(detail || `Request failed with HTTP ${response.status}`, response.status);
  }
  return payload;
}

// Two decimals for totals; small per-request costs keep four so they do not round to $0.00.
function formatMoney(value) {
  if (value === null || value === undefined) return "unknown";
  const amount = Number(value);
  return amount >= 1 ? `$${amount.toFixed(2)}` : `$${amount.toFixed(4)}`;
}

// Built once: constructing Intl formatters per table row is one of the main costs of re-rendering the list.
const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const COMPACT_FORMAT = new Intl.NumberFormat(undefined, { notation: "compact" });

function formatDate(value) {
  return DATE_FORMAT.format(new Date(value));
}

function compactNumber(value) {
  return COMPACT_FORMAT.format(Number(value || 0));
}

// True when a refresh brought back the same rows, so the list can keep its current objects and skip rendering.
function sameRequests(a, b) {
  return (
    a.length === b.length &&
    a.every(
      (item, index) =>
        item.id === b[index].id &&
        item.status === b[index].status &&
        item.latency_ms === b[index].latency_ms &&
        item.captured_at === b[index].captured_at
    )
  );
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
  if (minutes < 60) return `Last ${minutes} min`;
  // Whole days read as days only from two days up, so the 24-hour preset says "Last 24 hours" like its control.
  if (minutes % (24 * 60) === 0 && minutes >= 2 * 24 * 60) {
    const days = minutes / (24 * 60);
    return `Last ${days} ${days === 1 ? "day" : "days"}`;
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `Last ${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  return `Last ${minutes} min`;
}

function minutesToRange(minutes) {
  if (minutes % (24 * 60) === 0) return { amount: minutes / (24 * 60), unit: "days" };
  if (minutes % 60 === 0) return { amount: minutes / 60, unit: "hours" };
  return { amount: minutes, unit: "minutes" };
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

const TENTACLES = Array.from({ length: 7 }, (_, index) => {
  const x = 84 + index * 12;
  const sway = index % 2 ? 9 : -9;
  const length = 150 + (index % 3) * 22;
  return `M${x} 150 C${x - sway} ${150 + length * 0.35} ${x + sway} ${150 + length * 0.7} ${x + sway / 2} ${150 + length}`;
});

// Line-art jellyfish for the console's empty and sign-in states. Gradient ids are per instance so several can share a page.
function JellyfishArt({ className = "" }) {
  const id = React.useId().replace(/:/g, "");
  return (
    <svg className={`jellyfishArt ${className}`.trim()} viewBox="0 0 240 360" aria-hidden="true">
      <defs>
        <radialGradient id={`${id}-body`} cx="50%" cy="30%" r="70%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="50%" stopColor="#8fb9c2" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#0f5c6e" stopOpacity="0.08" />
        </radialGradient>
        <linearGradient id={`${id}-tentacle`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#0f5c6e" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#0f5c6e" stopOpacity="0" />
        </linearGradient>
        <filter id={`${id}-glow`} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="1" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g fill="none" strokeLinecap="round" filter={`url(#${id}-glow)`}>
        {TENTACLES.map((path, index) => (
          <path key={path} d={path} stroke={`url(#${id}-tentacle)`} strokeWidth="1.3" opacity={0.6 + (index % 3) * 0.1} />
        ))}
      </g>
      <g filter={`url(#${id}-glow)`}>
        <path
          d="M70 150 C66 56 174 56 170 150 C160 164 80 164 70 150 Z"
          fill={`url(#${id}-body)`}
          stroke="#1d1b17"
          strokeOpacity="0.5"
          strokeWidth="1"
        />
        <path
          d="M96 150 Q90 104 120 72 M120 152 Q120 110 120 74 M144 150 Q150 104 120 72"
          fill="none"
          stroke="#1d1b17"
          strokeOpacity="0.25"
          strokeWidth="0.8"
        />
      </g>
      {[
        [34, 72, 1.8],
        [208, 56, 1.4],
        [214, 214, 2],
        [26, 240, 1.2],
        [190, 300, 1.6],
      ].map(([cx, cy, r]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} fill="#0f5c6e" opacity="0.6" />
      ))}
    </svg>
  );
}

function AuthHero() {
  return (
    <div className="authHero">
      <div className="brand">
        <BrandMark />
        <div className="brandText">
          <strong>LogLlama</strong>
          <span>AI correlation console</span>
        </div>
      </div>
      <JellyfishArt />
      <div>
        <h1>Trace every model call, end to end.</h1>
        <p>Correlate prompts, latency, cost and errors across your AI providers, from one console.</p>
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  return <span className={`status ${status}`}>{status}</span>;
}

function MetricCard({ icon: Icon, label, value, detail, tone }) {
  return (
    <section className={`metric ${tone || ""}`}>
      <div className="metricLabel">
        <Icon size={16} />
        <span>{label}</span>
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
  const minutes = toMinutes(value);
  const maxFor = (unit) => (unit === "days" ? 30 : unit === "hours" ? 24 * 30 : 60 * 24 * 30);
  const setAmount = (nextValue) => {
    const parsed = Number(nextValue);
    if (Number.isNaN(parsed)) return;
    onChange({ ...value, amount: Math.min(maxFor(value.unit), Math.max(1, parsed)) });
  };
  const setUnit = (unit) => {
    onChange({ amount: Math.min(maxFor(unit), Math.max(1, Number(value.amount) || 1)), unit });
  };

  return (
    <div className="durationControl" aria-label="Time range">
      <label htmlFor="timeRangeAmount">
        <CalendarDays size={15} />
        <span>Last</span>
        <input id="timeRangeAmount" min="1" type="number" value={value.amount} onChange={(event) => setAmount(event.target.value)} />
        <select aria-label="Time unit" value={value.unit} onChange={(event) => setUnit(event.target.value)}>
          <option value="minutes">min</option>
          <option value="hours">hours</option>
          <option value="days">days</option>
        </select>
      </label>
      <div className="durationPresets" aria-label="Quick ranges">
        {RANGE_PRESETS.map((preset) => (
          <button
            key={preset.label}
            className={minutes === preset.minutes ? "active" : ""}
            type="button"
            onClick={() => onChange(minutesToRange(preset.minutes))}
          >
            {preset.label}
          </button>
        ))}
      </div>
    </div>
  );
}

const RequestRow = React.memo(function RequestRow({ request, selected, onSelect }) {
  return (
    <button className={`requestRow ${selected ? "selected" : ""}`} type="button" aria-pressed={selected} onClick={() => onSelect(request)}>
      <span>
        <StatusPill status={request.status} />
      </span>
      <span className="modelCell">
        <span className="modelName">{display(request.model)}</span>
        <span className="serviceName">{display(request.service_name, "service n/a")}</span>
      </span>
      <span className="routeCell">{display(request.route || request.operation)}</span>
      <span>{display(request.environment, "env n/a")}</span>
      <span>{display(request.tenant_id, "tenant n/a")}</span>
      <span>{request.latency_ms} ms</span>
      <span>{formatDate(request.captured_at)}</span>
    </button>
  );
});

function JsonBlock({ title, value, defaultOpen = false }) {
  return (
    <details className="jsonBlock" open={defaultOpen}>
      <summary className="jsonTitle">
        <Braces size={14} />
        <h3>{title}</h3>
      </summary>
      {value === null || value === undefined ? (
        <p className="jsonEmpty">Not captured for this request.</p>
      ) : (
        <pre>{JSON.stringify(value, null, 2)}</pre>
      )}
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

function RequestDetail({ request, onClose }) {
  return (
    <aside className="drawer" aria-label="Request details">
      <header className="drawerHeader">
        <div className="drawerTitle">
          <span className="eyebrow">{display(request.service_name, "service n/a")}</span>
          <h2>{display(request.route || request.operation)}</h2>
          <div className="drawerMeta">
            <StatusPill status={request.status} />
            <span>{display(request.model)}</span>
            <span>{formatDate(request.captured_at)}</span>
          </div>
        </div>
        <button className="iconCommand" type="button" onClick={onClose} aria-label="Close details" title="Close (Esc)">
          <X size={16} />
        </button>
      </header>

      <dl className="details">
        <div>
          <dt>Latency</dt>
          <dd>{request.latency_ms} ms</dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd>{compactNumber(request.total_tokens)}</dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd title={request.cost_usd === null ? "No published price for this model" : undefined}>
            {formatMoney(request.cost_usd)}
          </dd>
        </div>
      </dl>

      {request.error_message && (
        <section className="errorBox">
          <strong>{request.error_type || "Error"}</strong>
          <p>{request.error_message}</p>
        </section>
      )}

      <JsonBlock title="Prompt" value={request.prompt} defaultOpen />
      <JsonBlock title="Response" value={request.response} defaultOpen />

      <details className="moreDetails">
        <summary>More details</summary>

        <section className="detailSection">
          <div className="sectionTitle">
            <Fingerprint size={15} />
            <h3>Correlation</h3>
          </div>
          <FieldGrid
            items={[
              { label: "Tenant", value: request.tenant_id },
              { label: "User", value: request.user_id },
              { label: "Session", value: request.session_id, mono: true },
              { label: "Conversation", value: request.conversation_id, mono: true },
              { label: "Request", value: request.request_id, mono: true },
              { label: "Trace", value: request.trace_id, mono: true },
              { label: "Span", value: request.span_id, mono: true },
            ]}
          />
        </section>

        <section className="detailSection">
          <div className="sectionTitle">
            <GitCommit size={15} />
            <h3>Runtime</h3>
          </div>
          <FieldGrid
            items={[
              { label: "Service", value: request.service_name },
              { label: "Environment", value: request.environment },
              { label: "Version", value: request.version },
              { label: "Git SHA", value: request.git_sha, mono: true },
              { label: "Provider request", value: request.provider_request_id, mono: true },
              { label: "Attempts", value: Number(request.retry_count || 0) + 1 },
              { label: "Prompt", value: request.prompt_template },
              { label: "Prompt version", value: request.prompt_version },
            ]}
          />
          <div className="tagsBlock">
            <span>Tags</span>
            <TagList tags={request.tags} />
          </div>
        </section>

        <section className="detailSection">
          <div className="sectionTitle">
            <ShieldCheck size={15} />
            <h3>Privacy</h3>
          </div>
          <div className="privacyGrid">
            <span>Prompt: {privacyState(request.prompt)}</span>
            <span>Response: {privacyState(request.response)}</span>
            <span>Sampling: {request.privacy?.sample_rate ?? 1}</span>
          </div>
        </section>

        <JsonBlock title="Model Parameters" value={request.model_parameters || {}} />
        <JsonBlock title="Custom Metadata" value={request.custom_metadata || {}} />
      </details>
    </aside>
  );
}

function AuthScreen({ onSignedIn }) {
  const [mode, setMode] = React.useState("login");
  const [form, setForm] = React.useState({ email: "", password: "", name: "", organization_name: "" });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const update = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body =
        mode === "login"
          ? { email: form.email, password: form.password }
          : {
              email: form.email,
              password: form.password,
              name: form.name,
              organization_name: form.organization_name,
            };
      const session = await apiFetch(mode === "login" ? "/api/auth/login" : "/api/auth/signup", { method: "POST", body });
      onSignedIn(session);
    } catch (err) {
      setError(err.message || "Unable to sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="adminUnlock">
      <div>
        <span className="eyebrow">LogLlama</span>
        <h2>{mode === "login" ? "Sign in" : "Create your workspace"}</h2>
        <p>
          {mode === "login"
            ? "Use the email and password for your account."
            : "Your account becomes the owner of a new organization. You can invite teammates afterwards."}
        </p>
      </div>
      <form onSubmit={submit}>
        <label>
          <span>Email</span>
          <input type="email" value={form.email} onChange={update("email")} autoComplete="email" required />
        </label>
        {mode === "signup" && (
          <>
            <label>
              <span>Name</span>
              <input value={form.name} onChange={update("name")} maxLength="120" autoComplete="name" />
            </label>
            <label>
              <span>Organization</span>
              <input value={form.organization_name} onChange={update("organization_name")} maxLength="120" required />
            </label>
          </>
        )}
        <label>
          <span>Password</span>
          <input
            type="password"
            value={form.password}
            onChange={update("password")}
            minLength={mode === "signup" ? 12 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </label>
        <button className="primaryCommand" type="submit" disabled={busy}>
          <LockKeyhole size={16} />
          <span>{busy ? "Working" : mode === "login" ? "Sign in" : "Create account"}</span>
        </button>
      </form>
      <button
        className="linkCommand"
        type="button"
        onClick={() => {
          setMode(mode === "login" ? "signup" : "login");
          setError("");
        }}
      >
        {mode === "login" ? "Create an account" : "Already have an account? Sign in"}
      </button>
      {error && <div className="banner">{error}</div>}
    </section>
  );
}

function TracesView({ projectId, onSessionExpired }) {
  const [summary, setSummary] = React.useState(null);
  const [requests, setRequests] = React.useState([]);
  const [facets, setFacets] = React.useState({});
  const [selected, setSelected] = React.useState(null);
  const [query, setQuery] = React.useState("");
  const deferredQuery = React.useDeferredValue(query.trim());
  const [timeRange, setTimeRange] = React.useState(DEFAULT_RANGE);
  const [filters, setFilters] = React.useState(EMPTY_FILTERS);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setError("");
    try {
      const shared = { project_id: projectId, minutes: toMinutes(timeRange), q: deferredQuery, ...filters };
      const [summaryJson, requestJson, facetsJson] = await Promise.all([
        apiFetch("/api/metrics/summary", { params: shared }),
        apiFetch("/api/requests", { params: { ...shared, limit: 100 } }),
        apiFetch("/api/metadata/facets", { params: shared }),
      ]);
      const nextRequests = requestJson.requests || [];
      setSummary(summaryJson);
      setRequests((current) => (sameRequests(current, nextRequests) ? current : nextRequests));
      setFacets(facetsJson);
      setSelected((current) => (current ? nextRequests.find((request) => request.id === current.id) || null : null));
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Unable to load LogLlama data");
    }
  }, [deferredQuery, filters, timeRange, projectId, onSessionExpired]);

  React.useEffect(() => {
    load();
    // Skip the poll while the tab is hidden so a background console does no work.
    const interval = window.setInterval(() => {
      if (!document.hidden) load();
    }, 10000);
    return () => window.clearInterval(interval);
  }, [load]);

  const hasSelection = Boolean(selected);
  const closeDetail = React.useCallback(() => setSelected(null), []);
  React.useEffect(() => {
    if (!hasSelection) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") closeDetail();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [hasSelection, closeDetail]);

  const activeFilterCount = Object.values(filters).filter(Boolean).length + (deferredQuery ? 1 : 0);
  const setFilter = (key, value) => setFilters((current) => ({ ...current, [key]: value }));
  const resetFilters = () => {
    setQuery("");
    setTimeRange(DEFAULT_RANGE);
    setFilters(EMPTY_FILTERS);
  };
  const rangeMinutes = toMinutes(timeRange);
  const rangeLabel = formatRangeLabel(rangeMinutes);

  return (
    <>
      <div className="traceToolbar">
        <DurationControl value={timeRange} onChange={setTimeRange} />
        <div className="toolbarActions">
          <span className="livePill" title="Refreshes every 10 seconds">
            Live
          </span>
          <button className="refreshButton" onClick={load} aria-label="Refresh data">
            <RefreshCw size={15} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && <div className="banner">{error}</div>}

      <section className="metricsGrid">
        <MetricCard icon={Activity} label="Requests" value={summary?.total_requests ?? 0} detail={rangeLabel} />
        <MetricCard icon={Coins} label="Spend" value={formatMoney(summary?.total_cost_usd ?? 0)} detail={`${rangeLabel} estimated cost`} />
        <MetricCard icon={Clock3} label="Latency" value={`${Math.round(summary?.avg_latency_ms || 0)} ms`} detail={`${rangeLabel} average`} />
        <MetricCard
          icon={AlertTriangle}
          label="Error rate"
          value={`${Math.round((summary?.error_rate || 0) * 100)}%`}
          detail={`${rangeLabel} failures`}
          tone={summary?.error_rate ? "warning" : ""}
        />
      </section>

      <section className="requestPanel">
        <div className="panelHeader">
          <div>
            <h2>Requests</h2>
            <p>
              {requests.length} shown, {rangeLabel.toLowerCase()}
            </p>
          </div>
          <label className="search">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search trace, tenant, route, model" />
          </label>
        </div>

        <div className="filterBar">
          <SelectFilter label="Env" value={filters.environment} options={facets.environments || []} onChange={(value) => setFilter("environment", value)} />
          <SelectFilter label="Service" value={filters.service_name} options={facets.service_names || []} onChange={(value) => setFilter("service_name", value)} />
          <SelectFilter label="Tenant" value={filters.tenant_id} options={facets.tenant_ids || []} onChange={(value) => setFilter("tenant_id", value)} />
          <SelectFilter label="Route" value={filters.route} options={facets.routes || []} onChange={(value) => setFilter("route", value)} />
          <SelectFilter label="Model" value={filters.model} options={facets.models || []} onChange={(value) => setFilter("model", value)} />
          <SelectFilter label="Status" value={filters.status} options={facets.statuses || []} onChange={(value) => setFilter("status", value)} />
          {(activeFilterCount > 0 || rangeMinutes !== toMinutes(DEFAULT_RANGE)) && (
            <button className="clearFilters" type="button" onClick={resetFilters}>
              <X size={13} />
              <span>Clear</span>
            </button>
          )}
        </div>

        <div className="requestHeader">
          <span>Status</span>
          <span>Service / Model</span>
          <span>Route</span>
          <span>Env</span>
          <span>Tenant</span>
          <span>Latency</span>
          <span>Captured</span>
        </div>
        <div className="requestList">
          {requests.map((request) => (
            <RequestRow key={request.id} request={request} selected={selected?.id === request.id} onSelect={setSelected} />
          ))}
          {!requests.length && <div className="emptyList">No matching traces</div>}
        </div>
      </section>

      {selected && (
        <>
          <div className="drawerScrim" onClick={closeDetail} aria-hidden="true" />
          <RequestDetail request={selected} onClose={closeDetail} />
        </>
      )}
    </>
  );
}

function ApiKeysView({ project, onSessionExpired }) {
  const [keys, setKeys] = React.useState([]);
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState("ingest");
  const [expiresInDays, setExpiresInDays] = React.useState("");
  const [created, setCreated] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setKeys(await apiFetch(`/api/projects/${project.id}/api-keys`));
      setError("");
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Unable to load API keys");
    }
  }, [project.id, onSessionExpired]);

  React.useEffect(() => {
    setCreated(null);
    load();
  }, [load]);

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const create = (event) => {
    event.preventDefault();
    run(async () => {
      const result = await apiFetch(`/api/projects/${project.id}/api-keys`, {
        method: "POST",
        body: { name: name.trim(), kind, expires_in_days: expiresInDays ? Number(expiresInDays) : null },
      });
      setCreated(result);
      setName("");
      setExpiresInDays("");
    });
  };

  const revoke = (key) => {
    if (!window.confirm(`Revoke "${key.name}"? Anything using it stops working immediately.`)) return;
    run(() => apiFetch(`/api/projects/${project.id}/api-keys/${key.id}`, { method: "DELETE" }));
  };

  return (
    <section className="adminWorkspace">
      {error && <div className="banner">{error}</div>}
      <div className="adminIntro">
        <div>
          <p>
            Ingest keys send traces from your apps. Runtime keys let your servers fetch managed provider credentials. A key is
            shown once, and LogLlama stores only a hash of it.
          </p>
        </div>
        <button className="iconCommand" type="button" onClick={load} aria-label="Refresh" title="Refresh">
          <RefreshCw size={16} />
        </button>
      </div>

      {created && (
        <section className="keyReveal">
          <strong>Copy this key now. It will not be shown again.</strong>
          <code>{created.key}</code>
          <button className="primaryCommand" type="button" onClick={() => navigator.clipboard?.writeText(created.key)}>
            <Copy size={15} />
            <span>Copy</span>
          </button>
          <button className="iconCommand" type="button" onClick={() => setCreated(null)} aria-label="Dismiss key" title="Dismiss">
            <X size={15} />
          </button>
        </section>
      )}

      <form className="credentialForm" onSubmit={create}>
        <label>
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength="120" required />
        </label>
        <label>
          <span>Type</span>
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="ingest">Ingest (send traces)</option>
            <option value="runtime">Runtime (fetch provider keys)</option>
          </select>
        </label>
        <label>
          <span>Expires in days</span>
          <input type="number" min="1" max="3650" value={expiresInDays} onChange={(event) => setExpiresInDays(event.target.value)} placeholder="Never" />
        </label>
        <button className="primaryCommand" type="submit" disabled={busy || !name.trim()}>
          <KeyRound size={16} />
          <span>{busy ? "Working" : "Create key"}</span>
        </button>
      </form>

      <div className="adminTable">
        <div className="adminTableHeader keyColumns">
          <span>Name</span>
          <span>Type</span>
          <span>Prefix</span>
          <span>Last used</span>
          <span>Status</span>
          <span />
        </div>
        {keys.map((key) => (
          <div className="adminTableRow keyColumns" key={key.id}>
            <strong>{key.name}</strong>
            <span>{key.kind}</span>
            <code>{key.key_prefix}…</code>
            <span>{key.last_used_at ? formatDate(key.last_used_at) : "never"}</span>
            <StatusPill status={key.revoked_at ? "revoked" : "active"} />
            {!key.revoked_at ? (
              <button className="dangerIcon" type="button" onClick={() => revoke(key)} disabled={busy} aria-label={`Revoke ${key.name}`} title="Revoke key">
                <Trash2 size={15} />
              </button>
            ) : (
              <span />
            )}
          </div>
        ))}
        {!keys.length && <div className="emptyList">No API keys yet</div>}
      </div>
    </section>
  );
}

function TeamView({ organization, role, onProjectsChanged, projects, onSessionExpired }) {
  const [members, setMembers] = React.useState([]);
  const [invite, setInvite] = React.useState({ email: "", role: "viewer" });
  const [projectName, setProjectName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const canManageMembers = can(role, "members:manage");
  const canManageProjects = can(role, "projects:manage");

  const load = React.useCallback(async () => {
    try {
      setMembers(await apiFetch(`/api/organizations/${organization.id}/members`));
      setError("");
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Unable to load members");
    }
  }, [organization.id, onSessionExpired]);

  React.useEffect(() => {
    load();
  }, [load]);

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const addMember = (event) => {
    event.preventDefault();
    run(async () => {
      await apiFetch(`/api/organizations/${organization.id}/members`, { method: "POST", body: invite });
      setInvite({ email: "", role: invite.role });
    });
  };

  const changeRole = (member, nextRole) =>
    run(() =>
      apiFetch(`/api/organizations/${organization.id}/members`, {
        method: "POST",
        body: { email: member.email, role: nextRole },
      })
    );

  const removeMember = (member) => {
    if (!window.confirm(`Remove ${member.email} from ${organization.name}?`)) return;
    run(() => apiFetch(`/api/organizations/${organization.id}/members/${member.user_id}`, { method: "DELETE" }));
  };

  const createProject = (event) => {
    event.preventDefault();
    run(async () => {
      await apiFetch("/api/projects", { method: "POST", body: { organization_id: organization.id, name: projectName.trim() } });
      setProjectName("");
      onProjectsChanged();
    });
  };

  return (
    <section className="adminWorkspace">
      {error && <div className="banner">{error}</div>}
      <div className="adminIntro">
        <div>
          <p>Projects hold traces, API keys, and provider credentials. Roles apply across the organization.</p>
          <p className="roleNote">
            Your role <span className="status">{ROLE_LABELS[role] || role}</span>
          </p>
        </div>
      </div>

      <h3>Projects</h3>
      {canManageProjects && (
        <form className="credentialForm" onSubmit={createProject}>
          <label>
            <span>New project</span>
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} maxLength="120" required />
          </label>
          <button className="primaryCommand" type="submit" disabled={busy || !projectName.trim()}>
            <Check size={16} />
            <span>Create project</span>
          </button>
        </form>
      )}
      <div className="adminTable">
        <div className="adminTableHeader projectColumns">
          <span>Name</span>
          <span>Created</span>
        </div>
        {projects.map((project) => (
          <div className="adminTableRow projectColumns" key={project.id}>
            <strong>{project.name}</strong>
            <span>{formatDate(project.created_at)}</span>
          </div>
        ))}
        {!projects.length && <div className="emptyList">No projects yet</div>}
      </div>

      <h3>Members</h3>
      {canManageMembers && (
        <form className="credentialForm" onSubmit={addMember}>
          <label>
            <span>Email</span>
            <input type="email" value={invite.email} onChange={(event) => setInvite({ ...invite, email: event.target.value })} required />
          </label>
          <label>
            <span>Role</span>
            <select value={invite.role} onChange={(event) => setInvite({ ...invite, role: event.target.value })}>
              {Object.entries(ROLE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button className="primaryCommand" type="submit" disabled={busy || !invite.email}>
            <Users size={16} />
            <span>Add member</span>
          </button>
        </form>
      )}
      <div className="adminTable">
        <div className="adminTableHeader memberColumns">
          <span>Email</span>
          <span>Name</span>
          <span>Role</span>
          <span />
        </div>
        {members.map((member) => (
          <div className="adminTableRow memberColumns" key={member.user_id}>
            <strong>{member.email}</strong>
            <span>{member.name || "—"}</span>
            {canManageMembers ? (
              <select value={member.role} onChange={(event) => changeRole(member, event.target.value)} disabled={busy} aria-label={`Role for ${member.email}`}>
                {Object.entries(ROLE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            ) : (
              <span>{ROLE_LABELS[member.role] || member.role}</span>
            )}
            {canManageMembers ? (
              <button className="dangerIcon" type="button" onClick={() => removeMember(member)} disabled={busy} aria-label={`Remove ${member.email}`} title="Remove member">
                <Trash2 size={15} />
              </button>
            ) : (
              <span />
            )}
          </div>
        ))}
        {!members.length && <div className="emptyList">No members</div>}
      </div>
    </section>
  );
}

function ProviderCredentialsView({ project, onSessionExpired, role }) {
  const [credentials, setCredentials] = React.useState([]);
  const [backend, setBackend] = React.useState("");
  const [provider, setProvider] = React.useState("openai");
  const [name, setName] = React.useState("default");
  const [apiKey, setApiKey] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const canManage = can(role, "credentials:manage");

  const load = React.useCallback(async () => {
    try {
      const payload = await apiFetch("/api/admin/provider-credentials", { params: { project_id: project.id } });
      setCredentials(payload.credentials || []);
      setBackend(payload.secret_backend || "");
      setError("");
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Unable to load provider credentials");
    }
  }, [project.id, onSessionExpired]);

  React.useEffect(() => {
    load();
  }, [load]);

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const save = (event) => {
    event.preventDefault();
    run(async () => {
      await apiFetch("/api/admin/provider-credentials", {
        method: "POST",
        params: { project_id: project.id },
        body: { provider, name, api_key: apiKey },
      });
      setApiKey("");
    });
  };

  const remove = (credential) => {
    if (!window.confirm(`Remove the ${credential.provider} credential "${credential.name}"?`)) return;
    run(() =>
      apiFetch(`/api/admin/provider-credentials/${credential.id}`, {
        method: "DELETE",
        params: { project_id: project.id },
      })
    );
  };

  return (
    <section className="adminWorkspace">
      {error && <div className="banner">{error}</div>}
      <div className="adminIntro">
        <div>
          <span className="eyebrow">Secret backend: {backend || "loading"}</span>
          <p>Keys are write-only here. The database keeps a reference and fingerprint, not the key value.</p>
        </div>
        <button className="iconCommand" type="button" onClick={load} aria-label="Refresh" title="Refresh">
          <RefreshCw size={16} />
        </button>
      </div>

      {canManage && (
        <form className="credentialForm" onSubmit={save}>
          <label>
            <span>Provider</span>
            <select value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Gemini</option>
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
      )}

      <div className="adminTable">
        <div className="adminTableHeader credentialColumns">
          <span>Provider</span>
          <span>Name</span>
          <span>Fingerprint</span>
          <span>Version</span>
          <span>Status</span>
          <span />
        </div>
        {credentials.map((credential) => (
          <div className="adminTableRow credentialColumns" key={credential.id}>
            <strong>{credential.provider}</strong>
            <span>{credential.name}</span>
            <code>{credential.fingerprint}</code>
            <span>v{credential.version}</span>
            <StatusPill status={credential.status} />
            {canManage ? (
              <button className="dangerIcon" type="button" onClick={() => remove(credential)} disabled={busy} aria-label={`Remove ${credential.provider} credential`} title="Remove credential">
                <Trash2 size={15} />
              </button>
            ) : (
              <span />
            )}
          </div>
        ))}
        {!credentials.length && <div className="emptyList">No managed provider credentials</div>}
      </div>
    </section>
  );
}

function TestPlansView({ project, role, onSessionExpired }) {
  const [plans, setPlans] = React.useState([]);
  const [busyId, setBusyId] = React.useState("");
  const [error, setError] = React.useState("");
  const canApprove = can(role, "tests:approve");

  const load = React.useCallback(async () => {
    try {
      const payload = await apiFetch("/api/admin/test-plans", { params: { project_id: project.id } });
      setPlans(payload.test_plans || []);
      setError("");
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
      setError(err.message || "Unable to load test plans");
    }
  }, [project.id, onSessionExpired]);

  React.useEffect(() => {
    load();
  }, [load]);

  const decide = async (plan, decision) => {
    setBusyId(plan.id);
    setError("");
    try {
      await apiFetch(`/api/admin/test-plans/${plan.id}/${decision}`, {
        method: "POST",
        body: {
          expires_in_hours: 24,
          reason: decision === "reject" ? "Rejected by approver" : null,
        },
      });
      await load();
    } catch (err) {
      if (err.status === 401) return onSessionExpired();
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
        <button className="iconCommand" type="button" onClick={load} aria-label="Refresh" title="Refresh">
          <RefreshCw size={16} />
        </button>
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
              <span>
                Maximum output: {plan.max_output_tokens} tokens per provider / runs: {plan.run_count} of {plan.max_runs}
                {plan.approved_by ? ` / decided by ${plan.approved_by}` : ""}
              </span>
              {plan.status === "pending" && canApprove && (
                <div className="decisionActions">
                  <button className="rejectCommand" type="button" onClick={() => decide(plan, "reject")} disabled={busyId === plan.id}>
                    <Ban size={15} />
                    <span>Reject</span>
                  </button>
                  <button className="approveCommand" type="button" onClick={() => decide(plan, "approve")} disabled={busyId === plan.id}>
                    <Check size={15} />
                    <span>Approve 24h</span>
                  </button>
                </div>
              )}
            </footer>
          </article>
        ))}
        {!plans.length && <div className="emptyList">No comparison requests for this project</div>}
      </div>
    </section>
  );
}

function App() {
  const [auth, setAuth] = React.useState({ status: "loading", session: null });
  const [organizationId, setOrganizationId] = React.useState("");
  const [projects, setProjects] = React.useState([]);
  const [projectId, setProjectId] = React.useState("");
  const [view, setView] = React.useState("traces");
  const [workspaceError, setWorkspaceError] = React.useState("");

  const signedOut = React.useCallback(() => {
    setAuth({ status: "signedOut", session: null });
    setProjects([]);
    setProjectId("");
    setView("traces");
  }, []);

  const applySession = React.useCallback((session) => {
    setAuth({ status: "signedIn", session });
    setOrganizationId((current) =>
      session.organizations.some((organization) => organization.id === current) ? current : session.organizations[0]?.id || ""
    );
  }, []);

  React.useEffect(() => {
    apiFetch("/api/auth/me")
      .then(applySession)
      .catch(() => setAuth({ status: "signedOut", session: null }));
  }, [applySession]);

  const organizations = auth.session?.organizations || [];
  const organization = organizations.find((item) => item.id === organizationId) || organizations[0] || null;
  const role = organization?.role || "";
  const organizationKey = organization?.id || "";

  const loadProjects = React.useCallback(
    async (targetOrganizationId) => {
      if (!targetOrganizationId) {
        setProjects([]);
        setProjectId("");
        return;
      }
      try {
        const list = await apiFetch("/api/projects", { params: { organization_id: targetOrganizationId } });
        setProjects(list);
        setProjectId((current) => (list.some((item) => item.id === current) ? current : list[0]?.id || ""));
        setWorkspaceError("");
      } catch (err) {
        if (err.status === 401) return signedOut();
        setWorkspaceError(err.message || "Unable to load projects");
      }
    },
    [signedOut]
  );

  React.useEffect(() => {
    if (auth.status === "signedIn") loadProjects(organizationKey);
  }, [auth.status, organizationKey, loadProjects]);

  const project = projects.find((item) => item.id === projectId) || null;

  const signOut = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // The session cookie is cleared locally even if the server call fails.
    }
    signedOut();
  };

  if (auth.status === "loading") {
    return (
      <main className="authShell">
        <p className="mutedText">Loading LogLlama…</p>
      </main>
    );
  }
  if (auth.status === "signedOut") {
    return (
      <main className="authShell">
        <div className="authLayout">
          <AuthHero />
          <AuthScreen onSignedIn={applySession} />
        </div>
      </main>
    );
  }

  const tabs = [
    { id: "traces", label: "Traces", icon: ListTree, visible: true },
    { id: "keys", label: "API keys", icon: KeyRound, visible: can(role, "keys:manage") },
    { id: "team", label: "Team", icon: Users, visible: true },
    { id: "providers", label: "Providers", icon: Server, visible: can(role, "credentials:manage") },
    { id: "tests", label: "Tests", icon: FlaskConical, visible: true },
  ].filter((tab) => tab.visible);
  const activeView = tabs.some((tab) => tab.id === view) ? view : "traces";
  const activeTab = tabs.find((tab) => tab.id === activeView);

  const noProject = (
    <section className="adminWorkspace">
      <div className="emptyList">
        {organization && can(role, "projects:manage")
          ? "This organization has no projects yet. Create one in Team."
          : "This organization has no projects yet. Ask an owner or developer to create one."}
      </div>
    </section>
  );

  let content = null;
  if (!organization) {
    content = <div className="emptyList">You are not a member of any organization yet.</div>;
  } else if (activeView === "team") {
    content = (
      <TeamView
        key={organization.id}
        organization={organization}
        role={role}
        projects={projects}
        onProjectsChanged={() => loadProjects(organization.id)}
        onSessionExpired={signedOut}
      />
    );
  } else if (!project) {
    content = noProject;
  } else if (activeView === "traces") {
    content = <TracesView key={project.id} projectId={project.id} onSessionExpired={signedOut} />;
  } else if (activeView === "keys") {
    content = <ApiKeysView key={project.id} project={project} onSessionExpired={signedOut} />;
  } else if (activeView === "providers") {
    content = <ProviderCredentialsView key={project.id} project={project} role={role} onSessionExpired={signedOut} />;
  } else if (activeView === "tests") {
    content = <TestPlansView key={project.id} project={project} role={role} onSessionExpired={signedOut} />;
  }

  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <BrandMark />
          <div className="brandText">
            <strong>LogLlama</strong>
            <span>AI correlation console</span>
          </div>
        </div>

        <div className="sidebarSection">
          <span className="sidebarLabel">Workspace</span>
          <div className="switchers">
            <label className="switcher">
              <span>Organization</span>
              <select value={organizationKey} onChange={(event) => setOrganizationId(event.target.value)}>
                {organizations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="switcher">
              <span>Project</span>
              <select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={!projects.length}>
                {projects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="sidebarSection">
          <span className="sidebarLabel">Console</span>
          <nav className="viewTabs" aria-label="Console views">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button key={tab.id} className={activeView === tab.id ? "active" : ""} type="button" onClick={() => setView(tab.id)}>
                  <Icon size={16} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="sidebarFooter">
          <div className="userChip">
            <span className="avatar" aria-hidden="true">
              {auth.session.user.email.charAt(0).toUpperCase()}
            </span>
            <span className="userEmail" title={auth.session.user.email}>
              {auth.session.user.email}
            </span>
          </div>
          <button className="iconCommand" type="button" onClick={signOut} aria-label="Sign out" title="Sign out">
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      <section className="content">
        <header className="pageHeader">
          <div>
            <span className="eyebrow">{[organization?.name, project?.name].filter(Boolean).join(" / ") || "Workspace"}</span>
            <h1>{activeTab?.label || "Traces"}</h1>
          </div>
        </header>

        {workspaceError && <div className="banner">{workspaceError}</div>}
        {content}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
