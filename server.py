import json
import math
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import handle_get, handle_post

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
SUPPORTED_LANGUAGES = {"JavaScript", "Python", "C++", "Java"}
MODEL = "gemini-4-hydrogen"


def load_env():
    """Load key=value pairs from .env if present."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def get_rank(cc):
    if cc <= 5:
        return "A"
    if cc <= 10:
        return "B"
    if cc <= 20:
        return "C"
    return "D"


def get_rating_label(avg):
    if avg <= 5:
        return "A · Low Risk"
    if avg <= 10:
        return "B · Moderate"
    if avg <= 20:
        return "C · Complex"
    return "D · High Risk"


def count_branches(block, language):
    """Count decision branches after stripping strings and comments."""
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', '""', block)
    cleaned = re.sub(r"//.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"#.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)

    if language == "Python":
        patterns = [r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b", r"\bexcept\b", r"\band\b", r"\bor\b"]
    else:
        patterns = [
            r"\bif\b", r"\belse\s+if\b", r"\bfor\b", r"\bwhile\b",
            r"\bcase\b", r"\bcatch\b", r"&&", r"\|\|", r"\?[^:]+:",
        ]

    return 1 + sum(len(re.findall(p, cleaned)) for p in patterns)


def analyze_complexity(code, language):
    """Calculate per-function cyclomatic complexity, nesting depth, and maintainability."""
    lines = code.splitlines()
    loc = sum(1 for line in lines if line.strip())
    details = []

    if language == "Python":
        for i, line in enumerate(lines):
            match = re.match(r"^(\s*)def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", line)
            if not match:
                continue
            base_indent = len(match.group(1))
            fn_lines = [line]
            max_nest = 0

            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    fn_lines.append(nxt)
                    continue
                indent = len(nxt) - len(nxt.lstrip(" \t"))
                if indent <= base_indent and not nxt.lstrip().startswith("#"):
                    break
                max_nest = max(max_nest, max(0, (indent - base_indent) // 4 - 1))
                fn_lines.append(nxt)

            cc = count_branches("\n".join(fn_lines), language)
            details.append({
                "name": f"{match.group(2)}()",
                "line": i + 1,
                "complexity": cc,
                "nesting": max_nest,
                "rank": get_rank(cc),
            })
    else:
        if language == "JavaScript":
            fn_re = re.compile(
                r"^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\([^)]*\)\s*\{"
                r"|^\s*(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>\s*\{"
            )
        elif language == "Java":
            fn_re = re.compile(
                r"^\s*(?:public|private|protected|static|final|synchronized|\s)*[\w<>\[\]]+\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*\)\s*\{"
            )
        else:
            fn_re = re.compile(
                r"^\s*(?:static|inline|virtual|const|unsigned|signed|[\w:<>]+)\s+(?:[\w:*&<>]+\s+)*([a-zA-Z_][a-zA-Z0-9_:]*)\s*\([^;]*\)\s*(?:const)?\s*\{"
            )

        for i, line in enumerate(lines):
            if re.match(r"^\s*(if|else|for|while|switch|catch)\b", line):
                continue
            match = fn_re.match(line)
            if not match:
                continue

            fn_name = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None) or "anonymous"
            depth = 0
            max_nest = 0
            started = False
            fn_lines = []

            for cur in lines[i:]:
                fn_lines.append(cur)
                for ch in cur:
                    if ch == "{":
                        depth += 1
                        started = True
                        max_nest = max(max_nest, depth - 1)
                    elif ch == "}":
                        depth -= 1
                if started and depth <= 0:
                    break

            cc = count_branches("\n".join(fn_lines), language)
            details.append({
                "name": f"{fn_name}()",
                "line": i + 1,
                "complexity": cc,
                "nesting": max_nest,
                "rank": get_rank(cc),
            })

    if not details:
        overall_cc = count_branches(code, language)
        details.append({
            "name": "Module / Top-Level",
            "line": 1,
            "complexity": overall_cc,
            "nesting": 0,
            "rank": get_rank(overall_cc),
        })

    avg_cc = round(sum(d["complexity"] for d in details) / len(details), 2)
    max_cc = max(d["complexity"] for d in details)
    raw_mi = 100 - math.log2(max(loc, 1)) * 7.5 - avg_cc * 2.4

    return {
        "method": "Python Branch Scan" if language == "Python" else f"{language} Control-Flow Scan",
        "average_complexity": avg_cc,
        "max_complexity": max_cc,
        "rating": get_rating_label(avg_cc),
        "maintainability_index": max(0, min(100, round(raw_mi))),
        "loc": loc,
        "details": details,
    }


REVIEW_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING", "description": "Concise 1-2 sentence assessment of the code."},
        "bugs": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "line": {"type": "STRING", "description": 'Line number or range, e.g. "7" or "4-6".'},
                    "severity": {"type": "STRING", "description": "One of: critical, high, medium, low, info."},
                    "title": {"type": "STRING", "description": "Short 3-6 word bug title."},
                    "description": {"type": "STRING", "description": "Why this is a bug or risk."},
                    "fix": {"type": "STRING", "description": "Concrete fix recommendation."},
                },
                "required": ["line", "severity", "title", "description", "fix"],
            },
        },
        "improvements": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "Concise improvement headline."},
                    "category": {"type": "STRING", "description": "Category such as Readability, Performance, Safety, or Style."},
                    "description": {"type": "STRING", "description": "Why this change helps."},
                    "suggestion": {"type": "STRING", "description": "Actionable recommendation or snippet."},
                },
                "required": ["title", "category", "description", "suggestion"],
            },
        },
        "complexity_notes": {"type": "STRING", "description": "Concise Big-O time/space and control-flow analysis."},
        "overall_score": {"type": "NUMBER", "description": "Integer or half-step score from 1 to 10."},
        "improved_code_lines": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "The complete refactored code split into an array of individual lines, preserving leading indentation.",
        },
    },
    "required": ["summary", "bugs", "improvements", "complexity_notes", "overall_score", "improved_code_lines"],
}


def call_gemini_review(code, language):
    """Send code to Gemini API and return normalized review data."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing. Please configure it in Settings > Secrets.")

    numbered = "\n".join(f"{idx + 1}: {line}" for idx, line in enumerate(code.splitlines()))
    system_prompt = (
        f"You are an expert senior software engineer performing a thorough, constructive code review for {language}.\n"
        "Analyze the provided code for:\n"
        "1. Bugs, edge cases, null/bounds safety, off-by-one errors, type issues, or logic errors. Reference exact line numbers.\n"
        "2. Concrete, idiomatic improvements for readability, performance, error handling, and maintainability.\n"
        "3. Time and space complexity observations in complexity_notes.\n"
        "4. An honest overall_score from 1 to 10 (9-10 production-ready, 6-8 minor issues, 1-5 needs significant fixes).\n"
        "5. improved_code_lines: an array of strings where each string is one line of the clean refactored code "
        "(preserving leading indentation, with no line numbers)."
    )

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": f"Review this {language} code (line numbers included for reference):\n\n{numbered}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": REVIEW_SCHEMA},
    }

    base_url = (os.environ.get("GOOGLE_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com").rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "User-Agent": "aistudio-build",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="ignore")
        if err.code == 403 or "API_KEY_INVALID" in err_body or "PERMISSION_DENIED" in err_body:
            raise ValueError("The configured GEMINI_API_KEY was rejected. Please verify it in Settings > Secrets.")
        if err.code == 429 or "RESOURCE_EXHAUSTED" in err_body:
            raise ValueError("Rate limit reached for the Gemini API key. Please wait a moment and try again.")
        raise ValueError(err_body or str(err))

    text = raw["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)

    valid_severities = {"critical", "high", "medium", "low", "info"}
    bugs = [
        {
            "line": str(b.get("line", "N/A")),
            "severity": str(b.get("severity", "info")).lower() if str(b.get("severity", "info")).lower() in valid_severities else "info",
            "title": str(b.get("title", "Code issue")),
            "description": str(b.get("description", "")),
            "fix": str(b.get("fix", "")),
        }
        for b in (parsed.get("bugs") or [])
    ]

    improvements = [
        {
            "title": str(item.get("title", "Improvement")),
            "category": str(item.get("category", "Quality")),
            "description": str(item.get("description", "")),
            "suggestion": str(item.get("suggestion", "")),
        }
        for item in (parsed.get("improvements") or [])
    ]

    lines = parsed.get("improved_code_lines") or []
    improved_code = "\n".join(str(line) for line in lines) if lines else str(parsed.get("improved_code", code))
    score = max(0, min(10, float(parsed.get("overall_score", 7))))

    return {
        "summary": str(parsed.get("summary", "Review completed.")),
        "bugs": bugs,
        "improvements": improvements,
        "complexity_notes": str(parsed.get("complexity_notes", "")),
        "overall_score": int(score) if score.is_integer() else score,
        "improved_code": improved_code,
    }


def run_review(code, language):
    target = language if language in SUPPORTED_LANGUAGES else "Python"
    return call_gemini_review(code, target), analyze_complexity(code, target)


class ReviewHandler(BaseHTTPRequestHandler):
    def send_bytes(self, status, content_type, data, send_body=True):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if send_body:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_json(self, status, data):
        self.send_bytes(status, "application/json; charset=utf-8", json.dumps(data).encode("utf-8"))

    def do_HEAD(self):
        self.send_bytes(200, "text/html; charset=utf-8", b"", send_body=False)

    def do_GET(self):
        path = self.path.split("?", 1)[0].lstrip("/")
        if path and path != "index.html":
            target = (PUBLIC_DIR / path).resolve()
            if target.is_relative_to(PUBLIC_DIR.resolve()) and target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                return self.send_bytes(200, f"{mime or 'application/octet-stream'}; charset=utf-8", target.read_bytes())

        self.send_bytes(200, "text/html; charset=utf-8", handle_get().encode("utf-8"))

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_048_576:
            return self.send_json(413, {"error": "Payload too large."})

        raw_body = self.rfile.read(length).decode("utf-8")

        if route == "/":
            parsed = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
            form = {k: v[-1] for k, v in parsed.items()}
            html = handle_post(form, run_review)
            return self.send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

        if route != "/api/review":
            return self.send_json(404, {"error": "Not found"})

        try:
            body = json.loads(raw_body or "{}")
            code = str(body.get("code") or "")
            if not code.strip():
                return self.send_json(400, {"error": "Please paste some code first."})
            review, complexity = run_review(code, body.get("language"))
            return self.send_json(200, {"review": review, "complexity": complexity})
        except ValueError as err:
            msg = str(err)
            status = 403 if "rejected" in msg else 429 if "Rate limit" in msg else 500
            return self.send_json(status, {"error": msg})
        except Exception as err:
            return self.send_json(500, {"error": str(err) or "Something went wrong during review."})

    def log_message(self, format, *args):
        pass


class QuietHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        _, err, _ = sys.exc_info()
        if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("PORT", "3000"))
    server = QuietHTTPServer(("0.0.0.0", port), ReviewHandler)
    print(f"AI Code Reviewer server running on http://localhost:{port}")
    server.serve_forever()
