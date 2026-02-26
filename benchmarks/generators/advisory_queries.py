"""Generate 520 advisory queries across 17 domains."""
import random

def generate_queries(seed=42):
    """Return list of dicts with id, tool, input, context, domain, subdomain."""
    rng = random.Random(seed)
    queries = []
    idx = 0

    # 17 domains with different query counts
    domain_counts = {
        "frontend": 50,
        "backend": 50,
        "devops": 30,
        "security": 30,
        "performance": 40,
        "testing": 30,
        "architecture": 30,
        "data_analytics": 30,
        "planning": 30,
        "communication": 30,
        "marketing": 20,
        "debugging": 40,
        "game_dev": 20,
        "ai_ml": 20,
        "mobile_pwa": 20,
        "cross_domain": 20,
        "vague_generic": 30,
    }

    for domain, count in domain_counts.items():
        for i in range(count):
            query = _gen_query(domain, i, rng)
            query["id"] = f"query_{idx}"
            queries.append(query)
            idx += 1

    rng.shuffle(queries)
    return queries

def _gen_query(domain, i, rng):
    """Generate a query for the given domain."""

    if domain == "frontend":
        tools = ["Edit", "Read", "Write"]
        tool = rng.choice(tools)

        files = [
            "src/components/Header.tsx",
            "src/pages/Dashboard.tsx",
            "src/App.css",
            "src/hooks/useAuth.ts",
            "package.json",
        ]

        tasks = [
            ("add loading spinner to", "implementing async data fetch"),
            ("fix responsive layout in", "mobile viewport showing desktop"),
            ("update button styles in", "matching new design system"),
            ("add error boundary to", "preventing white screen crashes"),
            ("optimize re-renders in", "component updates too frequently"),
        ]

        file = rng.choice(files)
        task, context = rng.choice(tasks)

        return {
            "tool": tool,
            "input": f"{task} {file}",
            "context": context,
            "domain": "frontend",
            "subdomain": "react" if "tsx" in file else "css",
        }

    elif domain == "backend":
        tools = ["Edit", "Read", "Bash"]
        tool = rng.choice(tools)

        files = [
            "src/api/auth.ts",
            "src/db/queries.sql",
            "src/services/email.ts",
            "src/middleware/rate-limit.ts",
            "prisma/schema.prisma",
        ]

        tasks = [
            ("add validation to", "preventing malformed requests"),
            ("optimize database query in", "query taking 2+ seconds"),
            ("implement caching for", "reduce database load"),
            ("add error handling to", "silent failures in production"),
            ("refactor endpoint in", "reducing code duplication"),
        ]

        file = rng.choice(files)
        task, context = rng.choice(tasks)

        return {
            "tool": tool,
            "input": f"{task} {file}",
            "context": context,
            "domain": "backend",
            "subdomain": "api" if "api" in file else "database",
        }

    elif domain == "devops":
        tools = ["Bash", "Edit", "Read"]
        tool = rng.choice(tools)

        commands = [
            "docker-compose up",
            "kubectl apply -f deployment.yaml",
            "terraform plan",
            "ansible-playbook deploy.yml",
            "pm2 start app.js",
        ]

        contexts = [
            "setting up local development environment",
            "deploying to production cluster",
            "scaling backend services",
            "updating infrastructure configuration",
            "automating deployment pipeline",
        ]

        return {
            "tool": tool,
            "input": rng.choice(commands) if tool == "Bash" else "Dockerfile",
            "context": rng.choice(contexts),
            "domain": "devops",
            "subdomain": "containers" if "docker" in rng.choice(commands) else "orchestration",
        }

    elif domain == "security":
        tools = ["Edit", "Read", "Bash"]
        tool = rng.choice(tools)

        files = [
            "src/auth/jwt.ts",
            "src/middleware/cors.ts",
            "src/utils/encrypt.ts",
            ".env.example",
            "src/api/upload.ts",
        ]

        tasks = [
            ("add input sanitization to", "preventing XSS attacks"),
            ("implement rate limiting for", "preventing brute force"),
            ("add CSRF protection to", "securing form submissions"),
            ("validate file uploads in", "preventing malicious files"),
            ("add security headers to", "hardening HTTP responses"),
        ]

        file = rng.choice(files)
        task, context = rng.choice(tasks)

        return {
            "tool": tool,
            "input": f"{task} {file}",
            "context": context,
            "domain": "security",
            "subdomain": "auth" if "auth" in file or "jwt" in file else "hardening",
        }

    elif domain == "performance":
        tools = ["Edit", "Read", "Bash"]
        tool = rng.choice(tools)

        files = [
            "src/components/HeavyList.tsx",
            "webpack.config.js",
            "next.config.js",
            "src/utils/cache.ts",
            "src/api/bulk-fetch.ts",
        ]

        tasks = [
            ("add memoization to", "component rendering too often"),
            ("implement code splitting in", "bundle size is 2MB"),
            ("add lazy loading to", "initial load taking 5+ seconds"),
            ("optimize images in", "page weight over 10MB"),
            ("implement caching for", "API calls too frequent"),
        ]

        file = rng.choice(files)
        task, context = rng.choice(tasks)

        return {
            "tool": tool,
            "input": f"{task} {file}",
            "context": context,
            "domain": "performance",
            "subdomain": "frontend" if "tsx" in file or "webpack" in file else "backend",
        }

    elif domain == "testing":
        tools = ["Write", "Edit", "Bash"]
        tool = rng.choice(tools)

        files = [
            "tests/auth.test.ts",
            "tests/integration/api.test.ts",
            "tests/e2e/checkout.spec.ts",
            "jest.config.js",
            "cypress.config.js",
        ]

        tasks = [
            ("add test coverage for", "edge case not tested"),
            ("fix flaky test in", "test fails randomly"),
            ("add integration test for", "only unit tests exist"),
            ("mock external API in", "test depends on network"),
            ("add E2E test for", "critical user flow untested"),
        ]

        file = rng.choice(files)
        task, context = rng.choice(tasks)

        return {
            "tool": tool,
            "input": f"{task} {file}",
            "context": context,
            "domain": "testing",
            "subdomain": "unit" if "unit" in file else "integration",
        }

    elif domain == "architecture":
        tools = ["Read", "Edit"]
        tool = rng.choice(tools)

        files = [
            "docs/ARCHITECTURE.md",
            "src/core/state-machine.ts",
            "src/services/orchestrator.ts",
            "src/types/index.ts",
            "src/config/dependencies.ts",
        ]

        contexts = [
            "designing event-driven system",
            "refactoring monolith to services",
            "implementing state management",
            "defining service boundaries",
            "reducing coupling between modules",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "architecture",
            "subdomain": "system_design",
        }

    elif domain == "data_analytics":
        tools = ["Bash", "Edit", "Read"]
        tool = rng.choice(tools)

        files = [
            "src/analytics/events.ts",
            "sql/queries/user-metrics.sql",
            "src/dashboards/metrics.ts",
            "scripts/export-data.py",
            "config/analytics.json",
        ]

        contexts = [
            "tracking user engagement metrics",
            "analyzing conversion funnel",
            "generating weekly reports",
            "exporting data for analysis",
            "setting up event tracking",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "data_analytics",
            "subdomain": "metrics",
        }

    elif domain == "planning":
        tools = ["Read", "Edit", "Write"]
        tool = rng.choice(tools)

        files = [
            "docs/ROADMAP.md",
            "docs/SPRINT_PLAN.md",
            "docs/REQUIREMENTS.md",
            "docs/API_SPEC.md",
            "docs/TASKS.md",
        ]

        contexts = [
            "planning next sprint features",
            "defining API requirements",
            "breaking down large feature",
            "estimating implementation time",
            "prioritizing bug fixes",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "planning",
            "subdomain": "project_management",
        }

    elif domain == "communication":
        tools = ["Write", "Edit"]
        tool = rng.choice(tools)

        files = [
            "docs/CHANGELOG.md",
            "README.md",
            "docs/API_DOCS.md",
            "docs/CONTRIBUTING.md",
            "docs/DEPLOYMENT.md",
        ]

        contexts = [
            "documenting new API endpoint",
            "writing release notes",
            "updating setup instructions",
            "explaining architecture decision",
            "creating contributor guide",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "communication",
            "subdomain": "documentation",
        }

    elif domain == "marketing":
        tools = ["Edit", "Write", "Read"]
        tool = rng.choice(tools)

        files = [
            "landing/index.html",
            "docs/MARKETING_COPY.md",
            "src/email/templates/welcome.html",
            "docs/CONTENT_STRATEGY.md",
            "analytics/campaign-metrics.json",
        ]

        contexts = [
            "improving landing page conversion",
            "writing product launch announcement",
            "optimizing email open rates",
            "planning content calendar",
            "analyzing campaign performance",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "marketing",
            "subdomain": "content",
        }

    elif domain == "debugging":
        tools = ["Read", "Bash", "Edit"]
        tool = rng.choice(tools)

        contexts = [
            "TypeError: Cannot read property 'map' of undefined",
            "CORS error on API request",
            "Memory leak in WebSocket connection",
            "Database deadlock on concurrent writes",
            "Race condition in async code",
            "CSS layout breaking on mobile",
            "Authentication token expired unexpectedly",
            "File upload failing silently",
            "Infinite loop in useEffect",
            "Build failing with cryptic error",
        ]

        files = [
            "src/components/UserList.tsx",
            "src/api/websocket.ts",
            "src/db/transactions.ts",
            "src/hooks/useAuth.ts",
            "src/utils/upload.ts",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files) if tool in ["Read", "Edit"] else "npm run build",
            "context": rng.choice(contexts),
            "domain": "debugging",
            "subdomain": "runtime_errors",
        }

    elif domain == "game_dev":
        tools = ["Edit", "Read", "Bash"]
        tool = rng.choice(tools)

        files = [
            "src/game/physics.ts",
            "src/game/renderer.ts",
            "src/game/entities/player.ts",
            "src/game/systems/collision.ts",
            "assets/sprites/player.png",
        ]

        contexts = [
            "implementing player movement",
            "optimizing render loop performance",
            "fixing collision detection bugs",
            "adding particle effects",
            "balancing game mechanics",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "game_dev",
            "subdomain": "mechanics",
        }

    elif domain == "ai_ml":
        tools = ["Edit", "Bash", "Read"]
        tool = rng.choice(tools)

        files = [
            "src/ml/training.py",
            "src/ml/inference.ts",
            "src/ml/embeddings.ts",
            "notebooks/model-eval.ipynb",
            "config/model-config.json",
        ]

        contexts = [
            "training classification model",
            "optimizing inference latency",
            "generating text embeddings",
            "evaluating model performance",
            "tuning hyperparameters",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "ai_ml",
            "subdomain": "inference",
        }

    elif domain == "mobile_pwa":
        tools = ["Edit", "Read"]
        tool = rng.choice(tools)

        files = [
            "src/service-worker.js",
            "manifest.json",
            "src/components/MobileNav.tsx",
            "src/utils/offline-cache.ts",
            "src/hooks/useOnline.ts",
        ]

        contexts = [
            "implementing offline mode",
            "adding PWA install prompt",
            "optimizing touch interactions",
            "caching API responses",
            "handling network transitions",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "mobile_pwa",
            "subdomain": "offline_first",
        }

    elif domain == "cross_domain":
        # Queries that touch multiple domains
        tools = ["Read", "Edit", "Bash"]
        tool = rng.choice(tools)

        contexts = [
            "setting up CI/CD pipeline for React app",
            "implementing auth with JWT and rate limiting",
            "optimizing database queries and caching strategy",
            "deploying ML model to production API",
            "building real-time dashboard with WebSockets",
            "creating mobile-friendly marketing landing page",
            "setting up E2E tests in CI pipeline",
            "implementing analytics tracking across app",
        ]

        files = [
            ".github/workflows/deploy.yml",
            "src/api/ml-endpoint.ts",
            "src/dashboard/realtime.tsx",
            "tests/e2e/full-flow.spec.ts",
        ]

        return {
            "tool": tool,
            "input": rng.choice(files),
            "context": rng.choice(contexts),
            "domain": "cross_domain",
            "subdomain": "integration",
        }

    else:  # vague_generic
        tools = ["Read", "Edit", "Write", "Bash"]
        tool = rng.choice(tools)

        vague_contexts = [
            "need to make this better",
            "fix the thing",
            "improve performance",
            "make it work",
            "update the code",
            "refactor this",
            "optimize",
            "clean up",
            "modernize",
            "simplify",
        ]

        vague_files = [
            "src/index.ts",
            "src/app.ts",
            "src/main.ts",
            "src/utils.ts",
            "src/helpers.ts",
        ]

        return {
            "tool": tool,
            "input": rng.choice(vague_files) if tool != "Bash" else "npm start",
            "context": rng.choice(vague_contexts),
            "domain": "vague_generic",
            "subdomain": "unclear",
        }
