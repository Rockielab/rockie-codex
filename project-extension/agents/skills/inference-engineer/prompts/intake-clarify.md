# Workload intake — intent questions

The agent asks the user these questions in order (one turn each, NOT all at once — the user types short answers; the agent acks and asks the next).

Goal: map the answers to one of six canonical workload shapes (`interactive`, `production-api`, `batch`, `embedding-throughput`, `vision-segmentation`, `scientific`) defined in `research/hardware-workload.md` § Workload taxonomy. The shape determines SKU + serving stack + cost cap defaults in step 3.

## Question 1 — Who hits this?

> *Who's going to actually call this model — just you (or a small team poking at it), an app with real users hitting an endpoint, or a queue of jobs to grind through?*

**Mapping:**
- "just me" / "small team" / "for my agent" / "personal use" → `interactive`
- "app with users" / "production" / "customers" / "API for my product" → `production-api`
- "queue of jobs" / "batch" / "process N documents" / "overnight" / "RL rollouts" / "synthetic data" → `batch`

If the modality is embedding or vision, **also** consider:
- "index N million docs" / "vector search" → `embedding-throughput`
- "image segmentation" / "masks" / "vision" → `vision-segmentation`
- "protein" / "molecule" / "scientific" / "regression" / "AlphaFold-like" → `scientific`

If the answer doesn't fit, ask one disambiguating follow-up. Do not invent a 7th shape.

## Question 2 — Does latency matter?

> *Does response latency matter for your use case, or is total wall-clock time the only thing you care about?*

**Mapping:**
- "yes, p99 matters" / "users are waiting" / "streaming" / "interactive" → high-latency-priority — favors nearby capacity and may favor on-demand if Question 4 says interruption is unacceptable
- "no, just total time" / "throughput is fine" / "I can wait" → low-latency-priority — favors spot, can pack more concurrent requests

For shape `interactive`: latency matters but utilization can be low → small-but-fast GPU is fine (L40S, L4, RTX-4090). For `production-api`: latency matters AND utilization matters → bigger GPU + continuous batching (H100, H200). For `batch`: latency doesn't matter → cheapest GPU + offline mode (L4, T4, spot anywhere).

## Question 3 — How much volume?

> *Roughly how many requests per day, and how long is the typical input?*

**Mapping:**
- "a few" / "I'll be testing it" / "<100/day" → interactive scale; small SKU
- "thousands/day" / "10K+/day" → production scale; medium SKU + batching
- "millions" / "indexing a corpus" → batch/embedding-throughput scale; spot swarm
- For input length: "short prompts" (<500 tokens) → standard config; "long context" (10K+ tokens) → bigger VRAM, possibly H200/H100 80GB; "documents" (100K+) → favor SGLang for prefix-cache reuse OR offline batch mode

## Question 4 — Can this be preempted?

> *Are you OK with the endpoint dying mid-request and auto-reprovisioning, or does this need to be live and survive the next 60 minutes?*

**Mapping:**
- "cannot die mid-request" / "must survive the next hour" / "no interruption" → `tier: "on_demand"` (non-preemptible; higher hourly cost, less interruption risk)
- "OK with dying mid-request" / "can retry" / "overnight" / "batch" / "async" / "one-off training run" / "cron" → `tier: "spot"` (preemptible; cheaper, accepts reprovisioning)

If the user says "make it cheap" but has not explicitly accepted mid-request death and reprovisioning, choose `on_demand` for live demos, customer-facing endpoints, and active agent loops, then say why in the cost-confirm. If they explicitly accept mid-request death for any workload, use `spot` and warn that a live/customer-facing endpoint may disappear during a request.

## Question 5 — Where are callers located? (latency-sensitive only)

Ask this only when Question 2 says latency matters or the workload maps to `interactive` / `production-api`:

> *Where will the customers calling this endpoint be located? Say `US`, `Europe`, or `any region` if location does not matter.*

**Mapping:**
- "US" / "US East" / "US West" / "North America" → `region: "us"`
- "Europe" / "EU" / "UK" → `region: "eu"`
- "any" / "latency not important" / "wherever is cheapest" → `region: "any"`

Do not expose or ask for a provider. Region is coarse latency intent only; the platform maps it to deidentified market candidates.

## After all answers

Echo the classification back in one sentence: *"OK — sounds like a `<shape>` workload: `<short paraphrase>`. Picking `<SKU>` with `<stack>` based on that + the model's VRAM needs. Cost-confirm coming next."*

If the user pushes back on the classification ("no, I want it on a cheap GPU even though it's production"), defer to their explicit preference only when they also accept preemption. If they did not explicitly accept mid-request death, keep `tier: "on_demand"` and explain the reliability tradeoff in the cost-confirm.
