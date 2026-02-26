"""Generate 2000 garbage memories for benchmarking."""
import random

def generate_garbage(seed=42):
    """Return list of dicts with id, text, label, layer, garbage_type."""
    rng = random.Random(seed)
    memories = []
    idx = 0

    # Types and counts:
    types = {
        "tool_sequence": 250,
        "timing_metrics": 200,
        "platitude": 200,
        "transcript": 150,
        "system_noise": 150,
        "duplicate": 200,
        "code_snippet": 150,
        "reaction_noise": 100,
        "sophisticated": 350,
        "edge_case": 250,
    }

    for gtype, count in types.items():
        for i in range(count):
            text = _gen(gtype, i, rng)
            memories.append({
                "id": f"garbage_{idx}",
                "text": text,
                "label": "garbage",
                "layer": "garbage",
                "garbage_type": gtype,
            })
            idx += 1

    rng.shuffle(memories)
    return memories

def _gen(gtype, i, rng):
    if gtype == "tool_sequence":
        tools = ["Bash", "Edit", "Read", "Write", "Glob", "Grep"]
        t1, t2, t3 = rng.sample(tools, 3)
        templates = [
            f"Used {t1} tool to run git status",
            f"{t1} -> {t2} -> {t3}",
            f"Tool sequence: {t1}, then {t2}",
            f"Applied {t1} on file, then {t2} to verify",
            f"Ran {t1} tool successfully",
            f"Executed {t1} command, followed by {t2}",
            f"Tool chain: {t1} → {t2} → {t3}",
            f"{t1} then {t2} for verification",
            f"Standard workflow: {t1}, {t2}, {t3}",
            f"Completed {t1} operation then moved to {t2}",
        ]
        return rng.choice(templates)

    elif gtype == "timing_metrics":
        ms = rng.randint(50, 5000)
        templates = [
            f"Response time: {ms}ms",
            f"Bridge cycle completed in {ms}ms",
            f"Advisory latency: {ms}ms (p95)",
            f"Pipeline processed in {ms}ms",
            f"Total execution: {ms}ms",
            f"Query took {ms}ms to complete",
            f"Processing time: {ms}ms",
            f"Latency measurement: {ms}ms",
            f"Operation finished in {ms}ms",
            f"Runtime: {ms}ms",
        ]
        return rng.choice(templates)

    elif gtype == "platitude":
        templates = [
            "Code should be well-written and maintainable",
            "Testing helps find bugs early",
            "Good documentation is important",
            "Security should be a priority",
            "Performance matters for user experience",
            "Clean code is better than messy code",
            "Communication is key to project success",
            "Technical debt should be managed carefully",
            "Code reviews improve quality",
            "Automation saves time in the long run",
            "Best practices should be followed",
            "Quality over quantity",
            "Consistency is important in coding",
            "User experience should be prioritized",
            "Collaboration makes teams stronger",
            "Planning ahead prevents problems",
            "Regular backups are essential",
            "Error handling is important",
            "Version control is necessary",
            "Refactoring improves code quality",
        ]
        return rng.choice(templates)

    elif gtype == "transcript":
        templates = [
            "yeah so I was thinking about that",
            "can you help me with this thing?",
            "ok let me try something else",
            "hmm that doesn't look right",
            "wait actually never mind",
            "oh I see what you mean now",
            "let me think about this for a sec",
            "that's interesting, tell me more",
            "okay got it",
            "sure thing",
            "yep makes sense",
            "I don't know about that",
            "maybe we should try something different",
            "hold on a second",
            "what do you think?",
            "I'm not sure",
            "let me check on that",
            "give me a minute",
        ]
        return rng.choice(templates)

    elif gtype == "system_noise":
        templates = [
            "[System Gap] Auto-tuner not active",
            "bridge_cycle processed 39 patterns",
            "Queue rotated: 1500 -> 0 events",
            "Cognitive learner saved 12 insights",
            "Pipeline health: OK (3/3 checks passed)",
            "Session started: abc123",
            "Memory capture: 5 items stored",
            "Meta-Ralph scoring completed",
            "Advisory gate check passed",
            "EIDOS episode created",
            "Chip runtime initialized",
            "Pattern detection complete",
            "Distillation phase finished",
            "Queue worker active",
            "Bridge worker running",
        ]
        return rng.choice(templates)

    elif gtype == "duplicate":
        base_texts = [
            "Always use bcrypt for password hashing",
            "React components should handle error states",
            "Database connections should use pooling",
            "API endpoints need rate limiting",
            "Cache invalidation requires careful strategy",
            "Input validation prevents security issues",
            "Async operations should handle errors",
            "Environment variables store configuration",
            "CSS should be modular and reusable",
            "Testing should cover edge cases",
        ]
        base = rng.choice(base_texts)
        variations = [
            base,
            base + ".",
            base.lower(),
            base.replace("should", "must"),
            "Remember: " + base,
            base + " for security",
            base + " in production",
        ]
        return rng.choice(variations)

    elif gtype == "code_snippet":
        templates = [
            "import os\nimport sys\nfrom pathlib import Path",
            "def main():\n    pass",
            "const x = await fetch('/api/data')",
            "SELECT * FROM users WHERE id = $1",
            "git checkout -b feature/new-thing",
            "npm install --save-dev typescript",
            ".container { display: flex; gap: 1rem; }",
            "async function getData() { return await api.get(); }",
            "class Component extends React.Component {}",
            "for i in range(10): print(i)",
            "const result = data.map(x => x * 2)",
            "UPDATE users SET active = true WHERE id = 1",
        ]
        return rng.choice(templates)

    elif gtype == "reaction_noise":
        templates = ["lgtm", "+1", "ship it!", "nice!", "cool", "thanks", "ok", "done", "yes", "no", "agree", "👍", "sounds good", "perfect", "got it", "ack", "noted", "approved", "confirmed", "great"]
        return rng.choice(templates)

    elif gtype == "sophisticated":
        templates = [
            "Reliability is important because unreliable systems are not reliable enough for production use",
            "The architecture should be scalable because scalability ensures the system can scale",
            "Performance optimization improves performance by making the system more performant",
            "Security is critical because insecure systems pose security risks",
            "We need better testing because our tests aren't testing enough things",
            "The deployment process should be streamlined to make deployments more streamlined",
            "Error handling is important for handling errors gracefully",
            "Code quality matters because low quality code has quality issues",
            "The monitoring system monitors the system to ensure it's being monitored",
            "Database optimization optimizes the database for optimal performance",
            "Load balancing distributes load across servers for better load distribution",
            "Horizontal scaling adds more instances to handle increased load",
            "Feedback is valuable for improving the quality of our deliverables",
            "Technical debt should be addressed proactively to prevent future issues",
            "Communication is essential for effective team collaboration and coordination",
            "Modularity improves maintainability by making code more modular",
            "Consistency ensures that things are consistent across the system",
            "Documentation documents the system for documentation purposes",
            "Automation automates tasks that should be automated",
            "Refactoring refactors code to improve code structure",
        ]
        return rng.choice(templates)

    elif gtype == "edge_case":
        templates = [
            "",
            " ",
            "a" * 2000,
            "!!!@@@###$$$%%%",
            '{"key": "value", "nested": {"a": 1}}',
            "<script>alert('xss')</script>",
            "🔥" * 50,
            "\n\n\n\t\t\t",
            "NULL",
            "undefined",
            "null",
            "true",
            "false",
            "0",
            "-1",
            "NaN",
            "Infinity",
            "[]",
            "{}",
            ";" * 100,
        ]
        return rng.choice(templates)

    return f"Generic garbage {i}"
