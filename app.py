from html import escape
from pathlib import Path
import re
import uuid

TEMPLATE_PATH = Path(__file__).resolve().parent / "public" / "index.html"
SESSIONS = {}

LANGUAGES = [("Python", ".py"), ("C++", ".cpp"), ("Java", ".java")]

DEFAULT_CODE = {
    "Python": "def add(a, b):\n    return a+b\n",
    "C++": "int add(int a, int b) {\n    return a+b;\n}\n",
    "Java": "public class Main {\n    public static int add(int a, int b) {\n        return a+b;\n    }\n}\n",
}

PRESETS = {
    "py-default": ("Python", DEFAULT_CODE["Python"]),
    "py-invoice": (
        "Python",
        'def calculate_order_total(items, discount_code, tax_rate=0.08):\n'
        '    total = 0\n'
        '    for i in range(len(items)):\n'
        '        item = items[i]\n'
        '        if item["price"] > 0:\n'
        '            total = total + item["price"] * item["qty"]\n'
        '    if discount_code == "SAVE20":\n'
        '        total = total - (total * 0.2)\n'
        '    elif discount_code == "FLAT50":\n'
        '        total = total - 50\n'
        '    if total == 0:\n'
        '        return 0\n'
        '    final_price = total + (total * tax_rate)\n'
        '    return round(final_price, 2)\n',
    ),
    "cpp-search": (
        "C++",
        "#include <vector>\nusing namespace std;\n\n"
        "int binarySearch(vector<int> arr, int target) {\n"
        "    int left = 0;\n"
        "    int right = arr.size();\n"
        "    while (left <= right) {\n"
        "        int mid = (left + right) / 2;\n"
        "        if (arr[mid] == target) {\n"
        "            return mid;\n"
        "        } else if (arr[mid] < target) {\n"
        "            left = mid + 1;\n"
        "        } else {\n"
        "            right = mid - 1;\n"
        "        }\n"
        "    }\n"
        "    return -1;\n"
        "}\n",
    ),
    "java-cache": (
        "Java",
        "import java.util.*;\n\npublic class SessionManager {\n"
        "    private Map<String, String> sessions = new HashMap<>();\n\n"
        "    public String getUserRole(String token) {\n"
        "        String user = sessions.get(token);\n"
        '        if (user.equals("admin")) {\n'
        '            return "FULL_ACCESS";\n'
        '        } else if (user.equals("editor")) {\n'
        '            return "WRITE_ACCESS";\n'
        "        }\n"
        '        return "READ_ONLY";\n'
        "    }\n\n"
        "    public void addSession(String token, String role) {\n"
        '        if (token != "" && role != null) {\n'
        "            sessions.put(token, role);\n"
        "        }\n"
        "    }\n"
        "}\n",
    ),
}

SEVERITY_MAP = {
    "critical": ("Critical", "text-red"),
    "high": ("High", "text-red"),
    "medium": ("Medium", "text-amber"),
    "low": ("Low", "text-sky"),
}


def first_line_num(text):
    match = re.search(r"\d+", str(text or ""))
    return int(match.group(0)) if match else None


def score_meta(score):
    if score >= 8:
        return ("Healthy", "text-green", "bg-green", "This code is in great shape with strong clarity and low defect risk.")
    if score >= 5:
        return ("Needs Improvement", "text-amber", "bg-amber", "Decent foundation, but addressing the flagged bugs and suggestions will improve reliability.")
    return ("Critical Attention", "text-red", "bg-red", "Significant defects or structural risks were detected that should be resolved before shipping.")


def render_bugs(bugs, expanded_idx):
    if not bugs:
        return (
            '<div class="bugs-clean-box">'
            '<div class="bugs-clean-title">No bugs found. Nice and clean.</div>'
            '<div class="bugs-clean-desc">No runtime defects, bounds issues, or logic errors were detected in this snippet.</div>'
            "</div>"
        )

    items = []
    for idx, bug in enumerate(bugs):
        label, color = SEVERITY_MAP.get(bug.get("severity"), ("Info", "text-muted"))
        is_open = expanded_idx == idx
        fix_html = ""
        if bug.get("fix"):
            fix_html = f'<div class="fix-box"><span class="fix-label">Suggested Fix</span><div class="fix-text">{escape(bug["fix"])}</div></div>'
        body_html = f'<div class="accordion-body"><p class="accordion-desc">{escape(bug.get("description", ""))}</p>{fix_html}</div>' if is_open else ""

        items.append(
            f'<div class="accordion-item">'
            f'<button type="submit" name="action" value="bug:{idx}" class="accordion-trigger" aria-expanded="{str(is_open).lower()}">'
            f'<div><div class="accordion-title">{escape(bug.get("title", ""))}</div>'
            f'<div class="accordion-meta tabular-nums">Line {escape(str(bug.get("line", "")))} · <span class="{color}">{label}</span></div></div>'
            f'<span class="accordion-chevron">{"▲" if is_open else "▼"}</span></button>'
            f"{body_html}</div>"
        )
    return f'<div class="accordion-list">{"".join(items)}</div>'


def render_improvements(items):
    if not items:
        return '<p class="error-message">No specific improvements suggested for this snippet.</p>'

    blocks = []
    for item in items:
        code_html = f'<pre class="improvement-code">{escape(item["suggestion"])}</pre>' if item.get("suggestion") else ""
        blocks.append(
            f'<div class="improvement-item">'
            f'<div class="improvement-head"><h3 class="improvement-title">{escape(item.get("title", ""))}</h3>'
            f'<span class="improvement-cat">{escape(item.get("category", ""))}</span></div>'
            f'<p class="improvement-desc">{escape(item.get("description", ""))}</p>{code_html}</div>'
        )
    return "".join(blocks)


def render_complexity(comp, review):
    if not comp:
        return ""

    rows = "".join(
        f'<tr><td class="mono">{escape(r["name"])}</td>'
        f'<td class="mono tabular-nums text-right">{r["line"]}</td>'
        f'<td class="mono tabular-nums text-right">{r["complexity"]}</td>'
        f'<td class="mono tabular-nums text-right">{r["nesting"]}</td>'
        f'<td class="mono tabular-nums text-right">{escape(r["rank"])}</td></tr>'
        for r in comp.get("details", [])
    )

    table_html = (
        f'<div><div class="subblock-title">Function Breakdown</div><div class="table-wrapper">'
        f'<table class="data-table compact"><thead><tr><th>Block / Function</th>'
        f'<th class="text-right">Line</th><th class="text-right">Cyclomatic</th>'
        f'<th class="text-right">Nesting</th><th class="text-right">Rank</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div></div>"
        if rows else ""
    )

    notes_html = (
        f'<div class="complexity-notes"><div class="subblock-title">AI Complexity Notes</div>'
        f'<p>{escape(review["complexity_notes"])}</p></div>'
        if review.get("complexity_notes") else ""
    )

    return (
        f'<div class="metrics-grid tabular-nums">'
        f'<div class="metric-tile"><span class="metric-tile-label">Method</span><span class="metric-tile-value">{escape(comp["method"])}</span></div>'
        f'<div class="metric-tile"><span class="metric-tile-label">Avg. Complexity</span><span class="metric-tile-value">{comp["average_complexity"]}</span></div>'
        f'<div class="metric-tile"><span class="metric-tile-label">Rating</span><span class="metric-tile-value">{escape(comp["rating"])}</span></div>'
        f'<div class="metric-tile"><span class="metric-tile-label">Maintainability</span><span class="metric-tile-value">{comp["maintainability_index"]}/100</span></div>'
        f"</div>{table_html}{notes_html}"
    )


def render_score(review, comp, code):
    score = float(review.get("overall_score", 0))
    display_score = int(score) if score.is_integer() else score
    label, text_cls, bar_cls, summary = score_meta(score)
    pct = min(100, max(0, score * 10))
    loc = comp.get("loc") if comp else len(code.splitlines())

    return (
        f'<div><span class="metric-tile-label">Overall Code Health</span>'
        f'<h3 class="score-heading tabular-nums">{display_score}/10 <span class="score-heading-sub">— {label}</span></h3>'
        f'<div class="progress-track"><div class="progress-fill {bar_cls}" style="width: {pct}%"></div></div></div>'
        f'<div class="score-status-box"><div class="score-status-label {text_cls}">{label}</div>'
        f'<p class="score-status-desc">{summary}</p></div>'
        f'<div class="score-stats-row tabular-nums">'
        f'<div><span class="metric-tile-label">Bugs Detected</span><span class="metric-tile-value">{len(review.get("bugs", []))}</span></div>'
        f'<div><span class="metric-tile-label">Suggestions</span><span class="metric-tile-value">{len(review.get("improvements", []))}</span></div>'
        f'<div><span class="metric-tile-label">Lines Reviewed</span><span class="metric-tile-value">{loc}</span></div></div>'
    )


def render_diff_lines(text):
    return "".join(
        f'<div class="diff-code-line"><span class="diff-line-num tabular-nums">{i + 1}</span>'
        f'<span class="diff-line-text">{escape(line) if line else " "}</span></div>'
        for i, line in enumerate(str(text or "").replace("\r\n", "\n").split("\n"))
    )


def render_diff(review, code, language):
    improved = review.get("improved_code", "")
    if not improved:
        return '<p class="error-message">No improved version was returned for this code.</p>'

    return (
        f'<textarea id="improved-code-raw" class="hidden" readonly>{escape(improved)}</textarea>'
        f'<div class="diff-toolbar"><span class="results-empty-lang">Before / After comparison ({escape(language)})</span>'
        f'<div class="panel-controls">'
        f'<button type="button" id="copy-improved-btn" class="btn btn-outline btn-xs" '
        f'onclick="navigator.clipboard?.writeText(document.getElementById(\'improved-code-raw\').value);'
        f'this.textContent=\'Copied\';setTimeout(()=>this.textContent=\'Copy Improved\',1500)">Copy Improved</button>'
        f'<button type="submit" name="action" value="apply" id="apply-improved-btn" class="btn btn-primary btn-xs">Apply to Editor</button>'
        f"</div></div>"
        f'<div class="diff-grid">'
        f'<div class="diff-pane"><div class="diff-pane-header">Original</div><div class="diff-pre mono">{render_diff_lines(code)}</div></div>'
        f'<div class="diff-pane is-improved"><div class="diff-pane-header">AI-Improved</div><div class="diff-pre mono">{render_diff_lines(improved)}</div></div>'
        f"</div>"
    )


def render_empty(language):
    modules = [
        ("01. Bugs & Edge Cases", "Pinpoints line-level logic defects and boundary risks."),
        ("02. Refactoring Improvements", "Actionable suggestions for readability and safety."),
        ("03. Cyclomatic Complexity", "Function branch count, nesting depth, and maintainability."),
        ("04. Overall Health Score", "Clear 0–10 code health rating paired with justification."),
        ("05. Before / After Diff", "Side-by-side comparison with one-click apply to editor."),
    ]
    rows = "".join(f'<div class="module-row"><span class="module-name">{escape(n)}</span><span class="module-desc">{escape(d)}</span></div>' for n, d in modules)
    return (
        f'<div class="results-empty"><div><h2>Review Results</h2>'
        f"<p>Paste your code in the editor and click <strong>Review Code</strong> to run a full inspection across five modules.</p>"
        f'<div class="module-list">{rows}</div></div>'
        f'<div class="results-empty-footer"><span class="results-empty-lang">Active language: {escape(language)}</span>'
        f'<button type="submit" name="action" value="review" id="empty-review-btn" class="btn btn-outline btn-md">Review Current Code</button></div></div>'
    )


def render_results_html(state, session):
    if session.get("error"):
        return (
            f'<div class="results-error"><h2 class="error-title">Review could not complete</h2>'
            f'<p class="error-message">{escape(session["error"])}</p>'
            f'<div><button type="submit" name="action" value="review" id="retry-review-btn" class="btn btn-primary btn-md">Try Again</button></div></div>'
        )

    review = session.get("review")
    if not review:
        return render_empty(state["language"])

    comp = session.get("complexity")
    bugs = review.get("bugs", [])
    improvements = review.get("improvements", [])
    score = review.get("overall_score", 0)
    label, text_cls, _, _ = score_meta(float(score))
    active = state["active_tab"]

    tabs = [
        ("bugs", f"Bugs ({len(bugs)})"),
        ("improvements", f"Improvements ({len(improvements)})"),
        ("complexity", "Complexity"),
        ("score", f"Score ({score}/10)"),
        ("diff", "Before / After"),
    ]
    tab_btns = "".join(
        f'<button type="submit" name="action" value="tab:{tid}" role="tab" aria-selected="{str(active == tid).lower()}" '
        f'class="tab-btn {"is-active" if active == tid else ""}">{escape(tlabel)}</button>'
        for tid, tlabel in tabs
    )

    if active == "bugs":
        body = render_bugs(bugs, state["expanded_bug"])
    elif active == "improvements":
        body = render_improvements(improvements)
    elif active == "complexity":
        body = render_complexity(comp, review)
    elif active == "score":
        body = render_score(review, comp, state["code"])
    else:
        body = render_diff(review, state["code"], state["language"])

    mi_html = f'<span style="color:#64748b"> · MI {comp["maintainability_index"]}/100</span>' if comp else ""
    summary_html = f'<p class="summary-callout">{escape(review["summary"])}</p>' if review.get("summary") else ""

    return (
        f'<div class="results-summary-header"><div class="results-top-row"><h2 class="panel-title">Review Results</h2>'
        f'<div class="results-score-inline tabular-nums {text_cls}">Score {score}/10 · {label}{mi_html}</div></div>'
        f"{summary_html}</div>"
        f'<div role="tablist" aria-label="Review sections" class="tabs-bar">{tab_btns}</div>'
        f'<div class="tab-content">{body}</div>'
    )


def get_session(session_id):
    if not session_id or session_id not in SESSIONS:
        session_id = uuid.uuid4().hex
        if len(SESSIONS) > 100:
            SESSIONS.pop(next(iter(SESSIONS)))
        SESSIONS[session_id] = {"review": None, "complexity": None, "error": None}
    return session_id, SESSIONS[session_id]


def render_page(state, session_id, session):
    code = state["code"]
    lines = code.replace("\r\n", "\n").split("\n")
    line_count = len(lines)
    meta = f'{state["language"]} · {line_count} {"line" if line_count == 1 else "lines"} · {len(code)} chars'

    gutter = "".join(
        f'<div class="{"gutter-line is-highlighted" if state["highlighted_line"] == i + 1 else "gutter-line"}">{i + 1}</div>'
        for i in range(line_count)
    )

    lang_btns = "".join(
        f'<button type="submit" name="action" value="lang:{lang}" role="radio" '
        f'aria-checked="{str(state["language"] == lang).lower()}" '
        f'class="lang-btn {"is-selected" if state["language"] == lang else ""}">'
        f'<span>{lang}</span><span class="lang-ext">{ext}</span></button>'
        for lang, ext in LANGUAGES
    )

    has_output = bool(session.get("review") or session.get("error"))
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{SESSION_ID}}": escape(session_id),
        "{{LANGUAGE}}": escape(state["language"]),
        "{{ACTIVE_TAB}}": escape(state["active_tab"]),
        "{{EXPANDED_BUG}}": "" if state["expanded_bug"] is None else str(state["expanded_bug"]),
        "{{HIGHLIGHTED_LINE}}": "" if state["highlighted_line"] is None else str(state["highlighted_line"]),
        "{{LANGUAGE_BUTTONS}}": lang_btns,
        "{{EDITOR_META}}": escape(meta),
        "{{LINE_GUTTER}}": gutter,
        "{{CODE}}": escape(code),
        "{{CLEAR_HIDDEN}}": "" if has_output else "hidden",
        "{{RESULTS_HTML}}": render_results_html(state, session),
    }
    for key, val in replacements.items():
        html = html.replace(key, val)
    return html


def handle_get():
    session_id, session = get_session(None)
    state = {
        "language": "Python",
        "code": DEFAULT_CODE["Python"],
        "active_tab": "bugs",
        "expanded_bug": 0,
        "highlighted_line": None,
    }
    return render_page(state, session_id, session)


def handle_post(form, run_review_fn):
    session_id, session = get_session(form.get("session_id"))
    exp = form.get("expanded_bug", "")
    hl = form.get("highlighted_line", "")
    state = {
        "language": form.get("language") or "Python",
        "code": form.get("code") if "code" in form else DEFAULT_CODE["Python"],
        "active_tab": form.get("active_tab") or "bugs",
        "expanded_bug": int(exp) if exp.isdigit() else None,
        "highlighted_line": int(hl) if hl.isdigit() else None,
    }

    action = form.get("action") or ("preset" if form.get("preset_id") else "review")

    if action.startswith("lang:"):
        next_lang = action.split(":", 1)[1]
        is_default = any(s.strip() == state["code"].strip() for s in DEFAULT_CODE.values())
        state["language"] = next_lang
        if is_default or not state["code"].strip():
            state["code"] = DEFAULT_CODE.get(next_lang, "")
        state["highlighted_line"] = None

    elif action == "preset" or action.startswith("preset:"):
        pid = action.split(":", 1)[1] if ":" in action else form.get("preset_id", "")
        if pid in PRESETS:
            state["language"], state["code"] = PRESETS[pid]
            state["highlighted_line"] = None

    elif action.startswith("tab:"):
        state["active_tab"] = action.split(":", 1)[1]
        if state["active_tab"] != "bugs":
            state["highlighted_line"] = None

    elif action.startswith("bug:"):
        idx = int(action.split(":", 1)[1])
        next_idx = None if state["expanded_bug"] == idx else idx
        state["expanded_bug"] = next_idx
        bugs = (session.get("review") or {}).get("bugs", [])
        state["highlighted_line"] = first_line_num(bugs[next_idx].get("line")) if next_idx is not None and next_idx < len(bugs) else None

    elif action == "apply":
        improved = (session.get("review") or {}).get("improved_code")
        if improved:
            state["code"] = improved
            state["highlighted_line"] = None

    elif action == "clear":
        session["review"] = None
        session["complexity"] = None
        session["error"] = None
        state["highlighted_line"] = None

    elif action == "review":
        session["error"] = None
        state["highlighted_line"] = None
        if not state["code"].strip():
            session["error"] = "Please paste some code first before running a review."
        else:
            try:
                session["review"], session["complexity"] = run_review_fn(state["code"], state["language"])
                state["active_tab"] = "bugs"
                state["expanded_bug"] = 0
            except Exception as err:
                session["error"] = str(err)

    return render_page(state, session_id, session)
