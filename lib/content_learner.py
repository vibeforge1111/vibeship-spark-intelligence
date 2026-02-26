"""Content Learning - Learn from code and project structure, not just behavior.

Gap 8 implementation: Extract patterns from:
- Code written (naming conventions, error handling, imports)
- Project structure (test organization, file patterns)
- Domain knowledge (frameworks, libraries detected)

Philosophy: These are OBSERVATIONS, not preferences. They help understand
the project context but don't override explicit user preferences.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from lib.cognitive_learner import get_cognitive_learner, CognitiveCategory
from lib.diagnostics import log_debug

STATE_FILE = Path.home() / ".spark" / "content_learning_state.json"


class ContentLearner:
    """Learn patterns from code and project structure."""

    def __init__(self) -> None:
        self.state = self._load_state()
        self.cog = get_cognitive_learner()

    def _load_state(self) -> Dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "patterns_seen": {},  # pattern -> count
            "files_analyzed": 0,
            "last_project": None,
        }

    def _save_state(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def learn_from_code(self, code: str, file_path: str) -> List[Tuple[str, str]]:
        """Extract learnable patterns from code. Returns list of (pattern_type, value)."""
        if not code or len(code) < 20:
            return []

        patterns_found = []
        ext = Path(file_path).suffix.lower() if file_path else ""

        # Detect language from extension
        lang = self._detect_language(ext)

        # Python patterns
        if lang == "python":
            patterns_found.extend(self._analyze_python(code))

        # JavaScript/TypeScript patterns
        elif lang in ("javascript", "typescript"):
            patterns_found.extend(self._analyze_js_ts(code, lang))

        # Generic patterns (any language)
        patterns_found.extend(self._analyze_generic(code))

        # Record patterns
        for pattern_type, value in patterns_found:
            key = f"{pattern_type}:{value}"
            self.state["patterns_seen"][key] = self.state["patterns_seen"].get(key, 0) + 1

            # If we've seen this pattern 3+ times, store as observation
            if self.state["patterns_seen"][key] == 3:
                self._store_pattern_insight(pattern_type, value, lang)

        self.state["files_analyzed"] += 1
        self._save_state()

        return patterns_found

    def _detect_language(self, ext: str) -> Optional[str]:
        """Detect language from file extension."""
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".sh": "bash",
            ".bat": "batch",
            ".ps1": "powershell",
        }
        return mapping.get(ext)

    def _analyze_python(self, code: str) -> List[Tuple[str, str]]:
        """Analyze Python-specific patterns."""
        patterns = []

        # Naming conventions
        if re.search(r"def [a-z]+_[a-z]+\(", code):
            patterns.append(("naming_style", "snake_case"))
        if re.search(r"class [A-Z][a-zA-Z]+:", code):
            patterns.append(("class_naming", "PascalCase"))

        # Error handling style
        if "except Exception as" in code or "except Exception:" in code:
            patterns.append(("error_handling", "broad_except"))
        elif re.search(r"except \w+Error", code):
            patterns.append(("error_handling", "specific_except"))

        # Type hints
        if re.search(r"def \w+\([^)]*:\s*\w+", code) or "-> " in code:
            patterns.append(("typing", "type_hints"))

        # Import style
        if re.search(r"from \w+ import \*", code):
            patterns.append(("import_style", "star_import"))
        if re.search(r"from __future__ import", code):
            patterns.append(("import_style", "future_imports"))

        # Docstrings
        if '"""' in code or "'''" in code:
            patterns.append(("documentation", "docstrings"))

        # F-strings vs format
        if re.search(r'f"[^"]*\{', code) or re.search(r"f'[^']*\{", code):
            patterns.append(("string_style", "f_strings"))
        elif ".format(" in code:
            patterns.append(("string_style", "format_method"))

        # Dataclasses
        if "@dataclass" in code:
            patterns.append(("data_modeling", "dataclasses"))

        # Pathlib vs os.path
        if "from pathlib import" in code or "Path(" in code:
            patterns.append(("path_handling", "pathlib"))
        elif "os.path" in code:
            patterns.append(("path_handling", "os_path"))

        return patterns

    def _analyze_js_ts(self, code: str, lang: str) -> List[Tuple[str, str]]:
        """Analyze JavaScript/TypeScript patterns."""
        patterns = []

        # Function style
        if re.search(r"const \w+ = \([^)]*\) =>", code):
            patterns.append(("function_style", "arrow_functions"))
        if re.search(r"function \w+\(", code):
            patterns.append(("function_style", "function_declarations"))

        # Export style
        if "export default" in code:
            patterns.append(("export_style", "default_export"))
        if re.search(r"export (const|function|class)", code):
            patterns.append(("export_style", "named_exports"))

        # Async patterns
        if "async/await" in code or re.search(r"async \w+", code):
            patterns.append(("async_style", "async_await"))
        if ".then(" in code:
            patterns.append(("async_style", "promise_chains"))

        # TypeScript specific
        if lang == "typescript":
            if "interface " in code:
                patterns.append(("ts_patterns", "interfaces"))
            if "type " in code and " = " in code:
                patterns.append(("ts_patterns", "type_aliases"))
            if ": React.FC" in code or ": FC<" in code:
                patterns.append(("react_patterns", "typed_components"))

        # React patterns
        if "useState" in code:
            patterns.append(("react_patterns", "hooks"))
        if "useEffect" in code:
            patterns.append(("react_patterns", "effects"))

        # Semicolons
        lines_with_semi = len(re.findall(r";\s*$", code, re.MULTILINE))
        lines_without_semi = len(re.findall(r"[^;{]\s*$", code, re.MULTILINE))
        if lines_with_semi > lines_without_semi * 2:
            patterns.append(("formatting", "semicolons"))
        elif lines_without_semi > lines_with_semi * 2:
            patterns.append(("formatting", "no_semicolons"))

        return patterns

    def _analyze_generic(self, code: str) -> List[Tuple[str, str]]:
        """Analyze language-agnostic patterns."""
        patterns = []

        # Comment style
        if re.search(r"//\s*TODO", code, re.IGNORECASE):
            patterns.append(("comments", "todo_markers"))
        if re.search(r"//\s*FIXME", code, re.IGNORECASE):
            patterns.append(("comments", "fixme_markers"))

        # Line length (estimate)
        lines = code.split("\n")
        long_lines = sum(1 for l in lines if len(l) > 100)
        if long_lines > len(lines) * 0.1:
            patterns.append(("formatting", "long_lines"))

        # Indentation
        if "\t" in code:
            patterns.append(("indentation", "tabs"))
        elif re.search(r"^    ", code, re.MULTILINE):
            patterns.append(("indentation", "4_spaces"))
        elif re.search(r"^  [^ ]", code, re.MULTILINE):
            patterns.append(("indentation", "2_spaces"))

        return patterns

    def _store_pattern_insight(self, pattern_type: str, value: str, lang: Optional[str]) -> None:
        """Store a pattern as a cognitive insight."""
        lang_note = f" in {lang}" if lang else ""
        insight_text = f"Project uses {value.replace('_', ' ')}{lang_note} ({pattern_type})"

        key = f"content_pattern:{pattern_type}:{value}"
        if lang:
            key += f":{lang}"

        try:
            self.cog.store_insight(
                key=key,
                insight=insight_text,
                category=CognitiveCategory.CONTEXT,
                confidence=0.6,  # Observations start lower than preferences
                evidence=[f"Seen 3+ times in project code"],
            )
            log_debug("content_learner", f"Stored pattern: {insight_text}")
        except Exception as e:
            log_debug("content_learner", f"Failed to store pattern: {e}")

    def learn_from_project_structure(self, files: List[str]) -> Dict[str, str]:
        """Learn project conventions from file structure."""
        if not files:
            return {}

        conventions = {}

        # Test organization
        test_patterns = {
            "tests/": "separate_tests_dir",
            "test/": "separate_test_dir",
            "__tests__/": "jest_style",
            ".test.": "colocated_tests",
            ".spec.": "colocated_specs",
            "_test.py": "pytest_style",
        }

        for pattern, style in test_patterns.items():
            if any(pattern in f for f in files):
                conventions["test_organization"] = style
                break

        # Source organization
        if any("/src/" in f or "\\src\\" in f for f in files):
            conventions["source_organization"] = "src_directory"
        elif any("/lib/" in f or "\\lib\\" in f for f in files):
            conventions["source_organization"] = "lib_directory"

        # Config patterns
        if any("tsconfig.json" in f for f in files):
            conventions["typescript"] = "configured"
        if any("eslint" in f.lower() for f in files):
            conventions["linting"] = "eslint"
        if any("prettier" in f.lower() for f in files):
            conventions["formatting"] = "prettier"

        # Store as insights
        for conv_type, value in conventions.items():
            key = f"project_convention:{conv_type}"
            insight = f"Project uses {value.replace('_', ' ')} for {conv_type.replace('_', ' ')}"
            try:
                self.cog.store_insight(
                    key=key,
                    insight=insight,
                    category=CognitiveCategory.CONTEXT,
                    confidence=0.7,
                    evidence=["Detected from project structure"],
                )
            except Exception:
                pass

        self._save_state()
        return conventions

    def get_stats(self) -> Dict:
        """Get content learning statistics."""
        patterns = self.state.get("patterns_seen", {})
        return {
            "files_analyzed": self.state.get("files_analyzed", 0),
            "unique_patterns": len(patterns),
            "total_pattern_occurrences": sum(patterns.values()),
            "top_patterns": sorted(patterns.items(), key=lambda x: -x[1])[:10],
        }


# Singleton
_learner: Optional[ContentLearner] = None


def get_content_learner() -> ContentLearner:
    global _learner
    if _learner is None:
        _learner = ContentLearner()
    return _learner


def learn_from_edit_event(file_path: str, new_content: str) -> List[Tuple[str, str]]:
    """Convenience function to learn from an Edit/Write event."""
    learner = get_content_learner()
    return learner.learn_from_code(new_content, file_path)


def learn_from_glob_result(files: List[str]) -> Dict[str, str]:
    """Convenience function to learn from project file listing."""
    learner = get_content_learner()
    return learner.learn_from_project_structure(files)
