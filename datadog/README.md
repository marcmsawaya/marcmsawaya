# Istio memory alerting on Datadog

A dashboard and four monitors covering memory saturation and OOM risk for
`istio-proxy` sidecars, Istio gateways and `istiod`.

```
datadog/
├── dashboards/istio-memory.json          # import via UI or POST /api/v1/dashboard
├── monitors/
│   ├── istio-proxy-memory-saturation.json   # sidecar > 90% of limit  (warn 80)
│   ├── istiod-memory-saturation.json        # istiod  > 85% of limit  (warn 75)
│   ├── istio-oomkilled.json                 # a kill actually happened
│   └── istio-proxy-memory-leak.json         # +30% over 4h — early warning
└── apply.sh                              # dry-run by default, --push to create
```

## About the API key

You need **two** credentials, and they are not the same thing:

| | Where | What it does |
|---|---|---|
| **API key** | Organization Settings → [API Keys](https://app.datadoghq.com/organization-settings/api-keys) | Lets you *submit* data. On its own it cannot create a dashboard. |
| **Application key** | Organization Settings → [Application Keys](https://app.datadoghq.com/organization-settings/application-keys) | Lets you *read and write* Datadog resources. This is the one that actually creates dashboards and monitors. |

Both go in the request headers (`DD-API-KEY` and `DD-APPLICATION-KEY`).

Two things worth knowing before you generate one:

- **An app key inherits every permission of the user who created it.** By
  default that is your whole account. Datadog supports scoping a key when you
  create it — for this work `dashboards_write` and `monitors_write` are
  sufficient, and a scoped key limits the damage if it leaks.
- **Your API host depends on your Datadog site.** `datadoghq.com` (US1),
  `datadoghq.eu`, `us3.datadoghq.com`, `us5.datadoghq.com`,
  `ap1.datadoghq.com`. Check the URL in your browser. A key from one site
  returns 403 against another, which is the most common cause of "my key
  doesn't work".

### Don't paste keys into a chat window or a commit

Anything typed into a chat transcript is stored, and anything committed to git
stays in the history even after a later commit removes it. `apply.sh` reads
credentials from environment variables for that reason — they never touch the
repo, and they are not passed as command-line arguments either, since argv is
readable by other processes on the same host via `ps`.

If a key ever does end up somewhere it shouldn't: revoke it in Organization
Settings first, then clean up. Revocation is immediate; cleaning history is
not.

## Applying it

**Option A — the UI, no keys needed.** Dashboards → New → *Import Dashboard
JSON*, paste `dashboards/istio-memory.json`. For each monitor: Monitors → New
→ *Import Monitor from JSON*.

**Option B — the script.**

```bash
export DD_API_KEY=...
export DD_APP_KEY=...
export DD_SITE=datadoghq.com     # match your site

./apply.sh            # validates payloads, creates nothing
./apply.sh --push     # creates the dashboard and all four monitors
```

The dry run is the default on purpose. It refuses to push while the monitors
still contain `REPLACE-ME`, so you can't accidentally create alerts that
notify nobody.

**Option C — Terraform**, if you already manage Datadog that way. The
`datadog_dashboard_json` and `datadog_monitor_json` resources take these files
as-is:

```hcl
resource "datadog_dashboard_json" "istio_memory" {
  dashboard = file("${path.module}/dashboards/istio-memory.json")
}
```

## Before you push: fill in the placeholders

Every monitor contains `REPLACE-ME` in two places:

- `@slack-REPLACE-ME` at the end of the message — your notification handle
  (`@slack-platform-alerts`, `@pagerduty-istio`, an email address).
- `team:REPLACE-ME` in the tags — used for monitor filtering and, if you use
  it, Datadog's service ownership mapping.

## Check the metric names first

The queries use the kubelet metrics from the Datadog Agent's Kubernetes
integration, which is the most widely available source:

| Metric | Role |
|---|---|
| `kubernetes.memory.working_set` | Memory in use. **This is the number the OOM killer acts on.** |
| `kubernetes.memory.limits` | The container's memory limit. |
| `kubernetes_state.container.status_report.count.oomkilled` | Kills, from kube-state-metrics. |
| `kubernetes.containers.restarts` | Restart count, for correlation. |

Working set rather than `container.memory.usage` is a deliberate choice:
usage includes reclaimable page cache, so it reads high in a way that does not
predict a kill and will generate false alerts.

Two panels also use `istio.*` metrics (xDS pushes, istiod Go heap). Those need
the Istio integration enabled and the names differ between Istio's telemetry
v1 and v2 pipelines — if those panels are empty, search `istio.` in Metrics
Explorer and adjust. The memory panels and all four monitors do not depend on
them.

The container names assume a stock Istio install: `istio-proxy` for sidecars
and gateways, `discovery` for istiod. Confirm with:

```bash
kubectl get pods -n istio-system -o jsonpath='{.items[*].spec.containers[*].name}'
```

`kubernetes_state.*` metrics require kube-state-metrics; if you don't run it,
the OOMKill monitor and its dashboard panels will have no data. The saturation
monitors work without it.

## How the thresholds are meant to work together

The four monitors are deliberately layered rather than redundant:

- **Leak detector (P3, +30% / 4h)** fires first, while there is still time to
  roll back on your own schedule. Noisiest of the four; raise the threshold if
  it chatters, rather than muting it.
- **Sidecar saturation (P2, 90%)** fires when a specific pod is genuinely
  close to being killed. Scoped per pod, so a single bad workload doesn't page
  you about the whole mesh.
- **istiod saturation (P1, 85%)** is lower on purpose. A killed sidecar breaks
  one workload; a killed istiod stops xDS pushes mesh-wide, so new pods come up
  without config and route changes silently stop propagating. Bigger blast
  radius, earlier threshold.
- **OOMKilled (P1)** is ground truth. If this fires without the saturation
  monitor firing first, the growth outran the 10-minute evaluation window —
  that's your signal to lower thresholds or shorten the window, not to ignore
  it.

`evaluation_delay: 60` on all four absorbs the Agent's metric submission lag.
`new_group_delay: 300` stops a newly scheduled pod from alerting while it is
still filling its working set.

## Sizing note

Sidecar memory scales with the size of the mesh config, not with the
workload's traffic. Envoy holds the whole config in memory, so without a
`Sidecar` resource narrowing `egress.hosts`, every proxy gets every service and
endpoint in the mesh. If these alerts fire mesh-wide rather than on one pod,
that is the first thing to check — raising the limit treats the symptom.
