"""Generate 3000 useful memories across 6 layers."""
import random

DOMAINS = [
    "marketing", "vibe_coding", "planning", "ui_ux", "debugging",
    "auth_security", "communication", "architecture", "data_analytics",
    "performance", "devops", "game_dev"
]

def generate_useful(seed=42):
    """Return list of dicts with id, text, label, layer, domain."""
    rng = random.Random(seed)
    memories = []
    idx = 0

    # Layer A: 600 very useful (causal + specific + tech + actionable)
    for i in range(600):
        text = _gen_layer_a(i, rng)
        memories.append({
            "id": f"useful_a_{idx}",
            "text": text,
            "label": "useful",
            "layer": "A",
            "domain": rng.choice(DOMAINS),
        })
        idx += 1

    # Layer B: 600 somewhat useful (good insight but vague)
    for i in range(600):
        text = _gen_layer_b(i, rng)
        memories.append({
            "id": f"useful_b_{idx}",
            "text": text,
            "label": "useful",
            "layer": "B",
            "domain": rng.choice(DOMAINS),
        })
        idx += 1

    # Layer C: 400 needs context (vague)
    for i in range(400):
        text = _gen_layer_c(i, rng)
        memories.append({
            "id": f"useful_c_{idx}",
            "text": text,
            "label": "useful",
            "layer": "C",
            "domain": rng.choice(DOMAINS),
        })
        idx += 1

    # Layer D: 400 edge cases
    for i in range(400):
        subtype = ["truncated", "hybrid", "very_long", "very_short"][i % 4]
        text = _gen_layer_d(subtype, i, rng)
        memories.append({
            "id": f"useful_d_{idx}",
            "text": text,
            "label": "useful",
            "layer": "D",
            "domain": rng.choice(DOMAINS),
        })
        idx += 1

    # Layer E: 400 A/B styles (100 groups × 4 variants)
    for i in range(100):
        base_insight = _gen_layer_e_base(i, rng)
        for variant in ["terse", "imperative", "narrative", "data_rich"]:
            text = _gen_layer_e_variant(base_insight, variant, rng)
            memories.append({
                "id": f"useful_e_{idx}",
                "text": text,
                "label": "useful",
                "layer": "E",
                "domain": rng.choice(DOMAINS),
                "style_group": i,
                "style_variant": variant,
            })
            idx += 1

    # Layer F: 600 real patterns (mimics cognitive store)
    for i in range(600):
        pattern_type = ["blind_spot", "goal_telemetry", "user_pref", "reasoning", "wisdom", "meta_learning"][i % 6]
        text = _gen_layer_f(pattern_type, i, rng)
        memories.append({
            "id": f"useful_f_{idx}",
            "text": text,
            "label": "useful",
            "layer": "F",
            "domain": rng.choice(DOMAINS),
        })
        idx += 1

    rng.shuffle(memories)
    return memories

def _gen_layer_a(i, rng):
    """Very useful: causal + specific + tech + actionable + quantitative."""
    templates = [
        "Always use bcrypt with cost=12 because MD5 is brute-forceable in under 1 minute on modern GPUs",
        "React setState is async - batch updates in useEffect to prevent race conditions causing stale state",
        "PostgreSQL VACUUM FULL locks table for hours on 100M+ rows - use VACUUM ANALYZE instead which is non-blocking",
        "JWT tokens should expire in 15min max because leaked tokens give full access until expiry",
        "Cloudflare cache TTL of 2 hours reduced server load by 73% (measured over 30 days)",
        "Use debounce 300ms on search input because users type 4-5 chars before deciding, saves 80% of API calls",
        "Redis pub/sub loses messages on network split - use Kafka for guaranteed delivery in distributed systems",
        "CSS paint time dropped 45% after moving box-shadow to GPU via transform: translateZ(0)",
        "Docker layer caching failed because COPY . . invalidates all downstream layers - copy package.json first",
        "Rate limit to 100 req/min per IP because 99th percentile legitimate usage is 47 req/min",
        "Stripe webhooks retry 3 times over 3 days - must be idempotent or risk duplicate charges",
        "MongoDB $lookup on 10M docs took 40s - denormalize into single collection reduced to 200ms",
        "Use SameSite=Strict on auth cookies because Lax allows CSRF on top-level navigation",
        "Webpack bundle size dropped 60% after tree-shaking unused lodash functions via babel-plugin-lodash",
        "CORS preflight adds 200ms - cache with Access-Control-Max-Age: 86400 to reduce OPTIONS requests by 95%",
        "SQLite WAL mode prevents SQLITE_BUSY errors under concurrent writes - journal mode locks entire DB",
        "Vercel functions timeout at 10s on hobby tier - move long tasks to background queue",
        "React.memo prevents 80% of unnecessary renders when props are primitives - fails with object props",
        "S3 eventual consistency caused 404 errors for 2 seconds after PUT - use strong consistency regions",
        "Argon2 is 3x slower than bcrypt but resistant to GPU/ASIC attacks - use for high-value accounts",
    ]

    tech_stacks = [
        ("Next.js 14", "React Server Components", "87% smaller JS bundle"),
        ("Supabase", "Row Level Security", "eliminated backend auth checks"),
        ("Tailwind", "JIT mode", "98% CSS purge rate"),
        ("Vite", "ES modules", "5x faster HMR than Webpack"),
        ("Prisma", "connection pooling", "reduced DB connections from 200 to 12"),
        ("tRPC", "end-to-end type safety", "zero runtime validation overhead"),
        ("SvelteKit", "zero-config SSR", "50% smaller bundles than React"),
        ("Zod", "schema validation", "caught 90% of type errors at runtime"),
        ("Drizzle ORM", "prepared statements", "3x faster than Prisma"),
        ("Bun", "native bundler", "40x faster than esbuild"),
    ]

    causal_patterns = [
        ("because", "prevents", "reduces"),
        ("due to", "causes", "eliminates"),
        ("since", "allows", "improves"),
        ("after", "dropped", "increased"),
        ("when", "triggers", "avoids"),
    ]

    # Mix templates with dynamic generation
    if i % 3 == 0:
        return rng.choice(templates)
    elif i % 3 == 1:
        tech, feature, metric = rng.choice(tech_stacks)
        conn = rng.choice(causal_patterns)
        return f"{tech} {feature} {conn[1]} {metric} {conn[0]} it {conn[2]} overhead"
    else:
        num1 = rng.randint(10, 95)
        num2 = rng.randint(100, 5000)
        tech = rng.choice(["Redis", "Postgres", "MongoDB", "MySQL", "Elasticsearch"])
        action = rng.choice(["indexing", "caching", "sharding", "replication", "denormalization"])
        return f"{tech} {action} reduced query time by {num1}% from {num2}ms to {num2 - num2*num1//100}ms under production load"

def _gen_layer_b(i, rng):
    """Somewhat useful: good insight but vague on specifics."""
    templates = [
        "React components should be small and focused on a single responsibility",
        "Database queries should be optimized for the most common use cases",
        "API responses should include proper error messages for debugging",
        "CSS should follow a consistent naming convention across the project",
        "Authentication flows need to handle edge cases like expired sessions",
        "State management should be centralized for complex applications",
        "User input should always be validated before processing",
        "Caching strategies can significantly improve performance",
        "Microservices architecture helps with independent scaling",
        "Monitoring is essential for catching production issues early",
        "Documentation should be updated when code changes",
        "Test coverage is important for catching regressions",
        "Security headers should be configured on all endpoints",
        "Mobile-first design improves user experience on smaller screens",
        "Code splitting reduces initial load time",
        "Background jobs should handle failures gracefully",
        "Database migrations should be reversible when possible",
        "Feature flags enable safer deployments",
        "Logging helps with debugging production issues",
        "Version control branches should be short-lived",
    ]

    domains = {
        "ui_ux": ["component hierarchy", "responsive design", "accessibility", "user feedback"],
        "performance": ["lazy loading", "bundle optimization", "server-side rendering", "caching layers"],
        "security": ["input sanitization", "authentication", "authorization", "encryption"],
        "devops": ["CI/CD pipelines", "container orchestration", "infrastructure as code", "monitoring"],
        "architecture": ["service boundaries", "data flow", "error handling", "state management"],
    }

    if i % 2 == 0:
        return rng.choice(templates)
    else:
        domain = rng.choice(list(domains.keys()))
        pattern = rng.choice(domains[domain])
        return f"Consider {pattern} when designing for {domain} - it improves maintainability"

def _gen_layer_c(i, rng):
    """Needs context: vague, generic advice."""
    templates = [
        "The deployment strategy worked better this time",
        "That approach to error handling seems more robust",
        "The new component structure feels cleaner",
        "Performance improved after the refactor",
        "Users responded positively to the changes",
        "The configuration is more flexible now",
        "This pattern reduced complexity",
        "The API design is easier to understand",
        "Testing became simpler with this structure",
        "The code is more maintainable after restructuring",
        "This solution handles edge cases better",
        "The workflow is more intuitive now",
        "Load times improved with these changes",
        "The interface feels more responsive",
        "Error messages are clearer in this version",
        "The database schema is more normalized",
        "This abstraction reduces duplication",
        "The caching strategy is more effective",
        "Security improved with the new approach",
        "The build process is faster now",
    ]
    return rng.choice(templates)

def _gen_layer_d(subtype, i, rng):
    """Edge cases: truncated, hybrid, very_long, very_short."""
    if subtype == "truncated":
        full = _gen_layer_a(i, rng)
        cutoff = rng.randint(20, len(full) // 2)
        return full[:cutoff] + "..."
    elif subtype == "hybrid":
        insight = _gen_layer_b(i, rng)
        code = rng.choice([
            "const x = await fetch('/api')",
            "SELECT * FROM users",
            "git commit -m 'fix'",
            "npm run build",
        ])
        return f"{insight}\n\n```\n{code}\n```"
    elif subtype == "very_long":
        parts = [_gen_layer_b(i + j, rng) for j in range(5)]
        return " ".join(parts) + " This is a very detailed explanation that goes into depth about the reasoning and trade-offs involved in the decision-making process."
    else:  # very_short
        return rng.choice([
            "Use Redis here",
            "Avoid N+1 queries",
            "Cache this",
            "Index that column",
            "Debounce input",
            "Validate first",
            "Log errors",
            "Add tests",
        ])

def _gen_layer_e_base(i, rng):
    """Generate base insight for style variants."""
    insights = [
        ("JWT refresh tokens", "rotation", "prevents replay attacks"),
        ("React keys", "stable IDs", "prevents reconciliation bugs"),
        ("CSS grid", "minmax()", "responsive without media queries"),
        ("Postgres indexes", "partial", "saves 70% disk space"),
        ("Webhook retries", "exponential backoff", "avoids rate limits"),
        ("Image optimization", "WebP format", "reduces bandwidth 40%"),
        ("API pagination", "cursor-based", "scales to millions of rows"),
        ("Form validation", "client + server", "UX and security"),
        ("Docker multi-stage", "builder pattern", "10x smaller images"),
        ("Git squash", "feature branches", "clean history"),
    ]
    return insights[i % len(insights)]

def _gen_layer_e_variant(base, variant, rng):
    """Generate style variant of base insight."""
    subject, feature, benefit = base

    if variant == "terse":
        return f"{subject} {feature} → {benefit}"
    elif variant == "imperative":
        return f"Use {feature} for {subject} to {benefit.replace('prevents', 'prevent').replace('reduces', 'reduce').replace('avoids', 'avoid')}"
    elif variant == "narrative":
        return f"When working with {subject}, I found that {feature} {benefit} - this improved reliability significantly"
    else:  # data_rich
        num = rng.randint(40, 95)
        return f"{subject} with {feature} {benefit} (measured {num}% improvement in production)"

def _gen_layer_f(pattern_type, i, rng):
    """Real patterns mimicking cognitive store entries."""
    if pattern_type == "blind_spot":
        return rng.choice([
            "Forgot to handle loading state in async component - causes flash of undefined",
            "Missed CORS headers on OPTIONS request - preflight fails silently",
            "Ignored timezone conversion in date calculations - off by hours for some users",
            "Overlooked mobile viewport meta tag - desktop layout on mobile",
            "Didn't validate file upload size - server OOM on large files",
        ])
    elif pattern_type == "goal_telemetry":
        return rng.choice([
            "Goal: reduce API latency below 100ms - achieved 87ms p95 via caching",
            "Goal: increase test coverage to 80% - reached 83% with integration tests",
            "Goal: eliminate memory leaks - fixed 3 listener leaks, now stable over 48h",
            "Goal: improve bundle size by 30% - achieved 42% reduction via code splitting",
            "Goal: zero downtime deploys - implemented blue-green, 12 deploys successful",
        ])
    elif pattern_type == "user_pref":
        return rng.choice([
            "User prefers iterative fixes over big rewrites",
            "User wants to see trade-offs before deciding",
            "User values performance over feature completeness",
            "User prefers TypeScript strict mode always on",
            "User likes short git commit messages (50 char max)",
        ])
    elif pattern_type == "reasoning":
        return rng.choice([
            "Chose Postgres over MongoDB because schema validation prevents bad data",
            "Skipped microservices for MVP because team is 2 people - monolith is faster",
            "Used server-side rendering for SEO even though it complicates caching",
            "Picked REST over GraphQL because mobile team already knows REST",
            "Deployed to edge functions for latency even though it costs 3x more",
        ])
    elif pattern_type == "wisdom":
        return rng.choice([
            "Premature optimization is worse than no optimization - profile first",
            "Code that's easy to delete is better than code that's easy to extend",
            "The best API design is no API - inline when possible",
            "Deploy on Friday if you have good rollback - fear causes stagnation",
            "Types catch bugs that tests miss - use both",
        ])
    else:  # meta_learning
        return rng.choice([
            "Pattern: after 3 similar bugs, create a linter rule to prevent the 4th",
            "Learning: refactors take 2x longer than estimated - pad estimates",
            "Observation: users report bugs in features they use most - good sign",
            "Trend: performance issues appear at 10x scale - load test early",
            "Rule: if explaining code takes >2min, refactor for clarity",
        ])
