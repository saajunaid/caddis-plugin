"""Convert High-Level Architecture (HLA) Markdown documents into Confluence Storage Format XHTML.

This script parses an HLA Markdown document, strips YAML frontmatter, metadata notices,
and reference sections, converts Markdown structure and tables to native Confluence XHTML,
and embeds self-contained PlantUML macros with corporate Material Design styling.

Usage:
    python scripts/convert_hla_to_confluence.py <path-to-hla.md> [--output <path-to-output.html>]
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional


def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from the beginning of markdown content."""
    pattern = r"^---\s*\n(.*?)\n---\s*\n"
    return re.sub(pattern, "", content, flags=re.DOTALL)


def strip_references_and_ai_metadata(content: str) -> str:
    """Remove references section, document notices, and any AI/agent-specific metadata."""
    # 1. Remove Reference Documents subsection up to next header or end
    pattern_ref = r"###\s*\d+\.\d+\s+Reference Documents.*?(?=(^##|\Z))"
    content = re.sub(pattern_ref, "", content, flags=re.DOTALL | re.MULTILINE)

    # 2. Filter out document notices, STE statements, and AI tool/model metadata
    banned_keywords = [
        "document notice",
        "simplified technical english",
        "asd-ste100",
        "active voice is used",
        "sentences are short",
        "explanations are direct",
        "caddis",
        "creating model",
        "creation-agent",
        "claude code",
        "codex",
        "antigravity",
    ]

    lines = []
    for line in content.splitlines():
        lower = line.lower()
        if any(keyword in lower for keyword in banned_keywords):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_ai_slop_and_punctuation(content: str) -> str:
    """Normalize punctuation, eliminate em-dashes/en-dashes, and purge AI slop.

    1. Replaces em-dashes (—) and en-dashes (–) with colons, parentheses, or ASCII hyphens.
    2. Converts smart/curly quotes (“ ” ‘ ’) to straight ASCII quotes.
    3. Replaces unicode bullet characters (•) with ASCII dashes (-).
    4. Eliminates AI buzzwords, purple prose, and meta-commentary framing.
    """
    # 1. Normalize em-dashes and en-dashes in titles and bullet definitions
    content = re.sub(r'^(#+\s+[^—\n]+?)\s*[—–]\s*(.+)$', r'\1: \2', content, flags=re.MULTILINE)
    content = re.sub(r'\*\*([^*—–\n]+?)\s*[—–]\s*([^*—–\n]+?)\*\*', r'**\1 (\2)**', content)
    content = content.replace("—", " - ").replace("–", "-")
    content = re.sub(r'[ \t]+-[ \t]+', ' - ', content)

    # 2. Smart quotes to straight ASCII
    content = content.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    # 3. Unicode bullet characters to ASCII hyphen
    content = content.replace("•", "-")

    # 4. Filter AI slop buzzwords and purple prose
    ai_buzzword_replacements = [
        (r'\bdelve into\b', 'inspect'),
        (r'\bdelve\b', 'investigate'),
        (r'\bpivotal\b', 'primary'),
        (r'\btestament to\b', 'evidence of'),
        (r'\btapestry\b', 'architecture'),
        (r'\bbeacon of\b', 'model for'),
        (r'\bgame-changer\b', 'significant improvement'),
        (r'\brevolutionize\b', 'transform'),
        (r'\bcornerstone of\b', 'core element of'),
        (r'\bseamlessly\b', 'directly'),
        (r'\bseamless\b', 'direct'),
        (r'\bholistic\b', 'end-to-end'),
        (r'\bfoster\b', 'support'),
        (r'\bharnessing\b', 'using'),
        (r'\bleverage\b', 'use'),
        (r'\bleveraging\b', 'using'),
        (r'\bleverages\b', 'uses'),
        (r'\bleveraged\b', 'used'),
        (r'\bmeticulous\b', 'detailed'),
        (r'\bcrucial\b', 'critical'),
        (r'\bcutting-edge\b', 'modern'),
        (r'\brobust\b', 'reliable'),
    ]
    for pattern, repl in ai_buzzword_replacements:
        content = re.sub(pattern, repl, content, flags=re.IGNORECASE)

    return content


def format_inline_markdown(text: str) -> str:
    """Safely escape XML characters and convert inline markdown (bold, italic, code)."""
    # 0. Sanitize AI slop punctuation (em-dashes, en-dashes, smart quotes, bullets)
    text = text.replace("—", " - ").replace("–", "-")
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("•", "-")

    # 1. Escape XML characters
    text = re.sub(r"&(?!(amp|lt|gt|quot|apos);)", "&amp;", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")

    # 2. Extract and protect code spans with placeholders so wildcards (*) are not parsed as italics
    code_spans = []

    def save_code(m):
        code_spans.append(f"<code>{m.group(1)}</code>")
        return f"__INLINE_CODE_SPAN_{len(code_spans)-1}__"

    text = re.sub(r"`([^`]+)`", save_code, text)

    # 3. Bold **bold** -> <strong>bold</strong>
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    # 4. Italic *italic* -> <em>italic</em>
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)

    # 5. Restore code spans
    for idx, span in enumerate(code_spans):
        text = text.replace(f"__INLINE_CODE_SPAN_{idx}__", span)

    return text


def convert_table(md_table_lines: list[str]) -> str:
    """Convert Markdown table lines to Confluence wrapped table."""
    if len(md_table_lines) < 2:
        return ""

    header_line = md_table_lines[0].strip()
    data_lines = md_table_lines[2:]

    headers = [format_inline_markdown(c.strip()) for c in header_line.split("|")[1:-1]]
    num_cols = len(headers)

    cols_html = "".join("<col/>" for _ in range(num_cols))
    colgroup = f"<colgroup>{cols_html}</colgroup>"

    thead_cells = "".join(f"<th><p>{h}</p></th>" for h in headers)
    thead = f"<thead><tr>{thead_cells}</tr></thead>"

    rows_html = []
    for row in data_lines:
        row_str = row.strip()
        if not row_str or not row_str.startswith("|"):
            continue
        cells = [format_inline_markdown(c.strip()) for c in row_str.split("|")[1:-1]]
        while len(cells) < num_cols:
            cells.append("")
        cell_elements = [f"<td><p>{c}</p></td>" for c in cells]
        row_html = "".join(cell_elements)
        rows_html.append(f"<tr>{row_html}</tr>")

    tbody = f"<tbody>{''.join(rows_html)}</tbody>"
    return f'<table class="wrapped">{colgroup}{thead}{tbody}</table>'


def _parse_mermaid_flowchart(code: str) -> Optional[str]:
    """Dynamically converts any Mermaid flowchart into Confluence PlantUML with Material palette."""
    lines = code.strip().splitlines()
    subgraphs = []
    sg_stack = []
    top_connections = []
    top_nodes = {}

    subgraph_start_re = re.compile(r'^\s*subgraph\s+([A-Za-z0-9_]+)(?:\["([^"]+)"\]|\[([^\]]+)\])?', re.IGNORECASE)
    direction_re = re.compile(r'^\s*direction\s+(LR|RL|TB|TD)', re.IGNORECASE)
    node_def_re = re.compile(r'([A-Za-z0-9_]+)\["([^"]+)"\](?::::([A-Za-z0-9_]+))?|([A-Za-z0-9_]+)\[([^\]]+)\](?::::([A-Za-z0-9_]+))?')

    has_flowchart = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("%%") or stripped.startswith("classDef") or stripped.startswith("style "):
            continue
        if stripped.lower().startswith("flowchart") or stripped.lower().startswith("graph"):
            has_flowchart = True
            continue

        sg_match = subgraph_start_re.match(stripped)
        if sg_match:
            sg_id = sg_match.group(1)
            sg_title = sg_match.group(2) or sg_match.group(3) or sg_id
            new_sg = {
                "id": sg_id,
                "title": sg_title,
                "direction": "TB",
                "nodes": {},
                "edges": [],
                "children": []
            }
            if sg_stack:
                sg_stack[-1]["children"].append(new_sg)
            else:
                subgraphs.append(new_sg)
            sg_stack.append(new_sg)
            continue

        if stripped.lower() == "end":
            if sg_stack:
                sg_stack.pop()
            continue

        dir_match = direction_re.match(stripped)
        if dir_match and sg_stack:
            sg_stack[-1]["direction"] = dir_match.group(1).upper()
            continue

        # 1. Extract node definitions
        for match in node_def_re.finditer(stripped):
            n_id = match.group(1) or match.group(4)
            n_lbl = match.group(2) or match.group(5)
            n_cls = match.group(3) or match.group(6) or ""
            node_info = {"id": n_id, "label": n_lbl, "class": n_cls}
            if sg_stack:
                sg_stack[-1]["nodes"][n_id] = node_info
            else:
                top_nodes[n_id] = node_info

        # 2. Clean line for edge extraction
        def repl_node(m):
            return m.group(1) or m.group(4)
        clean_edge_line = node_def_re.sub(repl_node, stripped)

        # 3. Extract edges
        edge_tokens = re.split(r'(\s*(?:<-->|-->|---|->)\s*(?:\|"[^"]*"\|\s*|\|[^\|]*\|\s*)?)', clean_edge_line)
        if len(edge_tokens) >= 3:
            for i in range(0, len(edge_tokens) - 2, 2):
                src = edge_tokens[i].strip()
                arrow_token = edge_tokens[i+1].strip()
                dst = edge_tokens[i+2].strip()

                lbl_match = re.search(r'\|"?([^"\|]*)"?\|', arrow_token)
                lbl = lbl_match.group(1).strip() if lbl_match else ""

                if src and dst and re.match(r'^[A-Za-z0-9_]+$', src) and re.match(r'^[A-Za-z0-9_]+$', dst):
                    edge_obj = {"src": src, "dst": dst, "label": lbl}
                    if sg_stack:
                        sg_stack[-1]["edges"].append(edge_obj)
                    else:
                        top_connections.append(edge_obj)

    # If no subgraphs or nodes discovered, return None to trigger fallback
    if not subgraphs and not top_nodes:
        return None

    def get_node_type(node_id: str, label: str, cls: str) -> tuple:
        id_low = node_id.lower()
        lbl_low = label.lower()
        cls_low = cls.lower()

        # Specific classDef and archetype hints
        if "rlhf" in cls_low or "feedback" in id_low:
            return "database", "rlhf_db"
        if "src" in cls_low or "source" in id_low or "derby" in lbl_low or "case_fault" in lbl_low:
            return "database", "source_db"
        if id_low.endswith("db") or "_db" in id_low:
            return "database", "staging_db"
        if "model" in cls_low or "synth" in cls_low or "llm" in id_low or "ai model" in lbl_low or "gpt" in lbl_low or "gemma" in lbl_low:
            return "rectangle", "ai_model"
        if "ui" in cls_low or "browser" in id_low or "dashboard" in lbl_low or "screener" in id_low or "client" in id_low or "user" in id_low:
            return "rectangle", "user_ui"
        if "gateway" in id_low or "apigee" in id_low or "gateway" in cls_low:
            return "queue", "gateway"
        if "ext" in cls_low or "telemetry" in id_low or any(k in lbl_low for k in ["telemetry", "nxt", "fcaps", "cdn"]):
            return "rectangle", "telemetry"
        if any(k in id_low for k in ["recoutput", "decision", "action"]) or "outstyle" in cls_low:
            return "rectangle", "outcome"

        # Check if explicitly a database/table
        is_db = any(k in lbl_low for k in ["db:", "dbo.", "database", "table", "store", "sqlite", "sql server", "[sp_"]) or \
                any(k in id_low for k in ["db", "table", "store"]) or \
                any(k in cls_low for k in ["stage", "datastyle"])
        if is_db:
            return "database", "staging_db"

        return "rectangle", "service"

    out = []
    out.append("@startuml")
    out.append("skinparam shadowing false")
    out.append('skinparam defaultFontName "Segoe UI"')
    out.append("skinparam defaultFontSize 11")
    out.append("skinparam roundCorner 6")
    out.append("skinparam linetype ortho")
    out.append("skinparam nodesep 80")
    out.append("skinparam ranksep 45\n")

    out.append("skinparam package {")
    out.append("    BorderColor #546E7A")
    out.append("    BackgroundColor #F8FAFC")
    out.append("    FontColor #263238")
    out.append("    FontStyle bold")
    out.append("}\n")

    out.append("skinparam database<<source_db>> {")
    out.append("    BorderColor #3949AB")
    out.append("    BackgroundColor #E8EAF6")
    out.append("    FontColor #1A237E")
    out.append("}")
    out.append("skinparam database<<staging_db>> {")
    out.append("    BorderColor #0277BD")
    out.append("    BackgroundColor #E1F5FE")
    out.append("    FontColor #01579B")
    out.append("}")
    out.append("skinparam rectangle<<ai_model>> {")
    out.append("    BorderColor #6A1B9A")
    out.append("    BackgroundColor #F3E5F5")
    out.append("    FontColor #4A148C")
    out.append("}")
    out.append("skinparam rectangle<<user_ui>> {")
    out.append("    BorderColor #E65100")
    out.append("    BackgroundColor #FFF3E0")
    out.append("    FontColor #BF360C")
    out.append("}")
    out.append("skinparam database<<rlhf_db>> {")
    out.append("    BorderColor #2E7D32")
    out.append("    BackgroundColor #E8F5E9")
    out.append("    FontColor #1B5E20")
    out.append("}")
    out.append("skinparam rectangle<<service>> {")
    out.append("    BorderColor #00695C")
    out.append("    BackgroundColor #E0F2F1")
    out.append("    FontColor #004D40")
    out.append("}")
    out.append("skinparam queue<<gateway>> {")
    out.append("    BorderColor #E65100")
    out.append("    BackgroundColor #FFF3E0")
    out.append("    FontColor #BF360C")
    out.append("}")
    out.append("skinparam rectangle<<telemetry>> {")
    out.append("    BorderColor #C2185B")
    out.append("    BackgroundColor #FCE4EC")
    out.append("    FontColor #880E4F")
    out.append("}")
    out.append("skinparam rectangle<<outcome>> {")
    out.append("    BorderColor #2E7D32")
    out.append("    BackgroundColor #E8F5E9")
    out.append("    FontColor #1B5E20")
    out.append("}\n")

    def render_subgraph(sg, indent=""):
        res = [f'{indent}package "{sg["title"]}" as {sg["id"]} {{']
        for child in sg.get("children", []):
            res.extend(render_subgraph(child, indent + "    "))
        for n_id, n_info in sg["nodes"].items():
            formatted_lbl = (
                n_info["label"]
                .replace("<br/>", "\\n")
                .replace("<br>", "\\n")
                .replace("•", "-")
                .replace('"', "'")
            )
            elem_type, stereotype = get_node_type(n_id, n_info["label"], n_info["class"])
            stereo_suffix = f" <<{stereotype}>>" if stereotype else ""
            res.append(f'{indent}    {elem_type} "{formatted_lbl}" as {n_id}{stereo_suffix}')

        if sg["edges"]:
            res.append("")
            arrow = "-right->" if sg["direction"] == "LR" else "-down->"
            for e in sg["edges"]:
                lbl_clean = (
                    e["label"]
                    .replace("<br/>", "\\n")
                    .replace("<br>", "\\n")
                    .replace("•", "-")
                    .replace('"', "'")
                    if e["label"]
                    else ""
                )
                lbl_suffix = f' : {lbl_clean}' if lbl_clean else ""
                res.append(f'{indent}    {e["src"]} {arrow} {e["dst"]}{lbl_suffix}')
        res.append(f"{indent}}}\n")
        return res

    for sg in subgraphs:
        out.extend(render_subgraph(sg))

    for n_id, n_info in top_nodes.items():
        formatted_lbl = (
            n_info["label"]
            .replace("<br/>", "\\n")
            .replace("<br>", "\\n")
            .replace("•", "-")
            .replace('"', "'")
        )
        elem_type, stereotype = get_node_type(n_id, n_info["label"], n_info["class"])
        stereo_suffix = f" <<{stereotype}>>" if stereotype else ""
        out.append(f'{elem_type} "{formatted_lbl}" as {n_id}{stereo_suffix}')
    if top_nodes:
        out.append("")

    for i in range(len(subgraphs) - 1):
        out.append(f'{subgraphs[i]["id"]} -[hidden]down- {subgraphs[i+1]["id"]}')
    if subgraphs:
        out.append("")

    for e in top_connections:
        lbl_clean = (
            e["label"]
            .replace("<br/>", "\\n")
            .replace("<br>", "\\n")
            .replace("•", "-")
            .replace('"', "'")
            if e["label"]
            else ""
        )
        lbl_suffix = f' : {lbl_clean}' if lbl_clean else ""
        out.append(f'{e["src"]} -down-> {e["dst"]}{lbl_suffix}')

    out.append("\n@enduml")
    return "\n".join(out)


def _parse_mermaid_sequence_diagram(code: str) -> Optional[str]:
    """Dynamically parse a Mermaid sequenceDiagram into Corporate PlantUML."""
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    if not any("sequenceDiagram" in l for l in lines):
        return None

    out = []
    out.append("@startuml")
    out.append("autonumber")
    out.append("skinparam shadowing false")
    out.append('skinparam defaultFontName "Segoe UI"')
    out.append("skinparam defaultFontSize 11")
    out.append("skinparam roundCorner 6\n")
    out.append("skinparam actor {")
    out.append("    BorderColor #3949AB")
    out.append("    BackgroundColor #E8EAF6")
    out.append("    FontColor #1A237E")
    out.append("}")
    out.append("skinparam participant {")
    out.append("    BorderColor #455A64")
    out.append("    BackgroundColor #F8FAFC")
    out.append("    FontColor #263238")
    out.append("}")
    out.append("skinparam database {")
    out.append("    BorderColor #0277BD")
    out.append("    BackgroundColor #E1F5FE")
    out.append("    FontColor #01579B")
    out.append("}")
    out.append("skinparam queue {")
    out.append("    BorderColor #E65100")
    out.append("    BackgroundColor #FFF3E0")
    out.append("    FontColor #BF360C")
    out.append("}")
    out.append("skinparam sequence {")
    out.append("    ArrowColor #1E88E5")
    out.append("    LifeLineBorderColor #90A4AE")
    out.append("    LifeLineBackgroundColor #ECEFF1")
    out.append("    DividerBorderColor #B0BEC5")
    out.append("    DividerBackgroundColor #ECEFF1")
    out.append("    DividerFontColor #263238")
    out.append("}\n")

    for line in lines:
        if line.startswith("%%") or line == "sequenceDiagram" or line == "autonumber":
            continue

        # Check for actor / participant / database / queue
        part_match = re.match(
            r'^(actor|participant|database|queue)\s+([A-Za-z0-9_]+)(?:\s+as\s+(.*))?$',
            line,
            re.IGNORECASE,
        )
        if part_match:
            kind = part_match.group(1).lower()
            p_id = part_match.group(2)
            label = part_match.group(3) or p_id
            label_clean = (
                label.strip('"')
                .strip("'")
                .replace("<br/>", "\\n")
                .replace("<br>", "\\n")
            )
            # Smart element type inference
            if kind == "participant":
                if (
                    p_id.lower() == "db"
                    or "database" in label_clean.lower()
                    or "sql server" in label_clean.lower()
                ):
                    kind = "database"
                elif "queue" in label_clean.lower() or "gateway" in label_clean.lower():
                    kind = "queue"
            out.append(f'{kind} "{label_clean}" as {p_id}')
            continue

        # Check for Note over A,B: Text OR Note over A: Text
        note_match = re.match(
            r'^[Nn]ote\s+(over|left of|right of)\s+([A-Za-z0-9_,\s]+):\s*(.*)$',
            line,
        )
        if note_match:
            placement = note_match.group(1).lower()
            targets = note_match.group(2).strip()
            text = note_match.group(3).strip()
            text_clean = text.replace("<br/>", "\\n").replace("<br>", "\\n")

            # Major phase dividers vs in-place notes
            if re.match(r'^\d+\.\s+', text_clean):
                out.append(f"\n== {text_clean} ==")
            else:
                out.append(f"note {placement} {targets} : {text_clean}")
            continue

        # Check for message arrows
        msg_match = re.match(
            r'^([A-Za-z0-9_]+)\s*(-->>|->>|-->|->)\s*([A-Za-z0-9_]+)\s*:\s*(.*)$',
            line,
        )
        if msg_match:
            src = msg_match.group(1)
            arrow_token = msg_match.group(2)
            dst = msg_match.group(3)
            msg_text = msg_match.group(4).strip()
            msg_clean = msg_text.replace("<br/>", "\\n").replace("<br>", "\\n")
            arrow = "-->" if "--" in arrow_token else "->"
            out.append(f"{src} {arrow} {dst} : {msg_clean}")
            continue

    out.append("\n@enduml")
    return "\n".join(out)


def get_plantuml_code(code_clean: str, feature_slug: str) -> str:
    """Return matching clean PlantUML code with corporate Material Design styling."""
    # If the markdown block already contains valid PlantUML, pass it through directly
    if code_clean.startswith("@startuml"):
        return code_clean

    # 1. Dynamic Mermaid Sequence Diagram parsing
    if "sequenceDiagram" in code_clean:
        parsed_seq = _parse_mermaid_sequence_diagram(code_clean)
        if parsed_seq:
            return parsed_seq
        # Fallback to legacy static sequence diagram
        return """@startuml
autonumber
skinparam shadowing false
skinparam defaultFontName "Segoe UI"
skinparam defaultFontSize 12
skinparam roundCorner 6

skinparam actor {
    BorderColor #3949AB
    BackgroundColor #E8EAF6
    FontColor #1A237E
}
skinparam participant {
    BorderColor #455A64
    BackgroundColor #F8FAFC
    FontColor #263238
}
skinparam sequence {
    ArrowColor #1E88E5
    LifeLineBorderColor #90A4AE
    LifeLineBackgroundColor #ECEFF1
    DividerBorderColor #B0BEC5
    DividerBackgroundColor #ECEFF1
    DividerFontColor #263238
}

actor "Screener / Operations User" as User
participant "User Web Browser\\n(React)" as UI
participant "Backend Service\\n(FastAPI)" as API
participant "Diagnostics Worker" as Worker
database "SQL Server Database" as DB
queue "Apigee API Gateway" as Apigee
participant "Network & Outage APIs" as Telemetry
participant "Language Model Service" as Model

== 1. Automated Telemetry Ingestion & Analysis ==
Worker -> DB: Query scheduled appointments & customer history
DB --> Worker: Return pending appointment records
Worker -> Apigee: Request device metrics & outage data (OAuth2)
Apigee -> Telemetry: Call SAA NXT, FCAPS, CDN, Outage APIs
Telemetry --> Apigee: Return raw JSON telemetry
Apigee --> Worker: Return authenticated telemetry payloads
Worker -> Worker: Evaluate physical threshold rules
Worker -> Worker: Compile Network, Case & Account Summaries
Worker -> Model: Send combined summaries for recommendation
Model --> Worker: Return structured triage recommendation
Worker -> DB: Store diagnostics, summaries & recommendations

== 2. Screener Review & Queue Management ==
User -> UI: Open appointment screening queue
UI -> API: GET /api/cases (with date & filter criteria)
API -> DB: Query screened cases, health indicators & summaries
DB --> API: Return case datasets and diagnostics
API --> UI: Return cases, health scores, and summaries to queue view

== 3. Decision Capture via Feedback Service ==
User -> UI: Select case, review recommendation & decide action
User -> UI: Submit decision (Keep, Cancel, Override, Defer) with notes
UI -> API: POST /api/cases/{id}/decision (Feedback Service)
API -> DB: Record screener decision, notes & audit metadata into AppScreen_Case_Feedback
DB --> API: Confirm write operation
API --> UI: Return updated case state and confirmation
UI --> User: Display updated status and audit record

@enduml"""

    # 2. Dynamic Mermaid Flowchart parsing with Orthogonal Routing & Material Design
    parsed_uml = _parse_mermaid_flowchart(code_clean)
    if parsed_uml:
        return parsed_uml

    # 3. End-to-End Database and Data Processing Pipeline Diagram (Static Fallback)
    elif "CASE_FAULTS" in code_clean or "Pipeline" in code_clean or "rlhfStyle" in code_clean:
        return """@startuml
skinparam shadowing false
skinparam defaultFontName "Segoe UI"
skinparam defaultFontSize 11
skinparam roundCorner 6
skinparam linetype ortho
skinparam nodesep 80
skinparam ranksep 45

skinparam package {
    BorderColor #546E7A
    BackgroundColor #F8FAFC
    FontColor #263238
    FontStyle bold
}

skinparam database<<source_db>> {
    BorderColor #3949AB
    BackgroundColor #E8EAF6
    FontColor #1A237E
}

skinparam database<<staging_db>> {
    BorderColor #0277BD
    BackgroundColor #E1F5FE
    FontColor #01579B
}

skinparam rectangle<<ai_model>> {
    BorderColor #6A1B9A
    BackgroundColor #F3E5F5
    FontColor #4A148C
}

skinparam rectangle<<user_ui>> {
    BorderColor #E65100
    BackgroundColor #FFF3E0
    FontColor #BF360C
}

skinparam database<<rlhf_db>> {
    BorderColor #2E7D32
    BackgroundColor #E8F5E9
    FontColor #1B5E20
}

package "Layer 1: Upstream Ingestion & Telemetry Enrichment" as L1 {
    database "**Host: IEROXAPP2**\\n**DB: DERBY**\\n`dbo.CASE_FAULTS & CFY_CASES`\\nClarify Trouble Tickets\\n[sp_CASE_FAULTS on IEROXAPP2]" as SourceDB <<source_db>>
    database "**Host: DBUATL01**\\n**DB: Customer_FeedBack_JIT**\\n`dbo.AppScreen_Pending_Calls`\\nPending Appointments Queue\\n[Ingestion ETL via Linked Server]" as PendingDB <<staging_db>>
    database "**Host: DBUATL01**\\n**DB: Customer_FeedBack_JIT**\\n`dbo.AppScreen_Case_Diagnostics`\\nEnriched Telemetry & RAG Status\\n[Diagnostics Worker on App Host]" as DiagDB <<staging_db>>
    
    SourceDB -right-> PendingDB : 1. Ingest
    PendingDB -right-> DiagDB : 2. Enrich
}

package "Layer 2: AI Multi-Track Inference & Recommendation" as L2 {
    rectangle "**Host: App Server / Azure**\\n**AI Model Engine (GPT-4o)**\\n3-Track Summarization & Triage\\n[LLM Service on App Host]" as LLM <<ai_model>>
    database "**Host: DBUATL01**\\n**DB: Customer_FeedBack_JIT**\\n`dbo.AppScreen_Case_Recommendation`\\nRecommendations & Confidence\\n[save_recommendations on App Host]" as RecDB <<staging_db>>
    
    LLM -right-> RecDB : 4. Predict
}

package "Layer 3: Screener Review, Locking & RLHF Feedback" as L3 {
    rectangle "**Host: Browser / App Server**\\n**Dispatcher Web Dashboard**\\nScreener Review & Advisory Locks\\n[`dbo.AppScreen_Case_Assignment`]" as UI <<user_ui>>
    database "**Host: DBUATL01**\\n**DB: Customer_FeedBack_JIT**\\n`dbo.AppScreen_Case_Feedback`\\nScreener Decisions & RLHF Ground Truth\\n[FastAPI /api/cases/{id}/decision]" as FeedbackDB <<rlhf_db>>
    
    UI -right-> FeedbackDB : 6. Feedback
}

L1 -[hidden]down- L2
L2 -[hidden]down- L3

DiagDB -down-> LLM : 3. Prompt Features
RecDB -down-> UI : 5. Present to Queue

@enduml"""

    # 3. Summarization and Recommendation Pipeline Diagram
    elif "Summarization" in code_clean or "Synthesis" in code_clean:
        return """@startuml
skinparam shadowing false
skinparam defaultFontName "Segoe UI"
skinparam defaultFontSize 11
skinparam roundCorner 6
skinparam linetype ortho
skinparam nodesep 50
skinparam ranksep 35

skinparam package {
    BorderColor #546E7A
    BackgroundColor #F8FAFC
    FontColor #263238
    FontStyle bold
}

skinparam rectangle<<track1>> {
    BorderColor #00695C
    BackgroundColor #E0F2F1
    FontColor #004D40
}

skinparam rectangle<<track2>> {
    BorderColor #E65100
    BackgroundColor #FFF3E0
    FontColor #BF360C
}

skinparam rectangle<<track3>> {
    BorderColor #3949AB
    BackgroundColor #E8EAF6
    FontColor #1A237E
}

skinparam rectangle<<synthesis>> {
    BorderColor #6A1B9A
    BackgroundColor #F3E5F5
    FontColor #4A148C
}

skinparam rectangle<<outcome>> {
    BorderColor #2E7D32
    BackgroundColor #E8F5E9
    FontColor #1B5E20
}

package "Stage 1: Multi-Track Data Analysis" as Inputs {
    package "Track A: Network Health" as TrackA {
        rectangle "1. SAA NXT, FCAPS, CDN Telemetry" as N1 <<track1>>
        rectangle "2. Threshold Rules & Outage Check" as N2 <<track1>>
        rectangle "**Network Health Summary**" as NSum <<track1>>
        N1 -right-> N2
        N2 -right-> NSum
    }

    package "Track B: Case History" as TrackB {
        rectangle "1. 30-Day CRM Interactions" as C1 <<track2>>
        rectangle "2. Repeat Fault Clustering" as C2 <<track2>>
        rectangle "**Customer Case Summary**" as CSum <<track2>>
        C1 -right-> C2
        C2 -right-> CSum
    }

    package "Track C: Account Profile" as TrackC {
        rectangle "1. Equipment Inventory (CPE)" as A1 <<track3>>
        rectangle "2. Subscribed Services & Plans" as A2 <<track3>>
        rectangle "**Account Profile Summary**" as ASum <<track3>>
        A1 -right-> A2
        A2 -right-> ASum
    }
}

package "Stage 2: AI Synthesis" as Synthesis {
    rectangle "**Language Model Synthesis Engine**\\nEvaluates Network, Case, and Account Summaries" as LLMEngine <<synthesis>>
}

package "Stage 3: Decision Support" as Decision {
    rectangle "**Action Recommendation & Justification**\\nKeep / Cancel / Defer / Tech Visit" as RecOutput <<outcome>>
}

TrackA -[hidden]down- TrackB
TrackB -[hidden]down- TrackC

NSum -right-> LLMEngine : Line Quality
CSum -right-> LLMEngine : Case History
ASum -right-> LLMEngine : Equipment

LLMEngine -right-> RecOutput : Recommended Action

@enduml"""

    # 4. Architecture Topology Diagram
    else:
        return """@startuml
skinparam shadowing false
skinparam defaultFontName "Segoe UI"
skinparam defaultFontSize 11
skinparam roundCorner 6
skinparam linetype ortho
skinparam nodesep 60
skinparam ranksep 50

skinparam package {
    BorderColor #455A64
    BackgroundColor #F8FAFC
    FontColor #263238
    FontStyle bold
}

skinparam rectangle<<user>> {
    BorderColor #3949AB
    BackgroundColor #E8EAF6
    FontColor #1A237E
}
skinparam rectangle<<proxy>> {
    BorderColor #455A64
    BackgroundColor #ECEFF1
    FontColor #263238
}
skinparam rectangle<<service>> {
    BorderColor #00695C
    BackgroundColor #E0F2F1
    FontColor #004D40
}
skinparam queue<<gateway>> {
    BorderColor #E65100
    BackgroundColor #FFF3E0
    FontColor #BF360C
}
skinparam database<<db>> {
    BorderColor #0277BD
    BackgroundColor #E1F5FE
    FontColor #01579B
}
skinparam rectangle<<telemetry>> {
    BorderColor #C2185B
    BackgroundColor #FCE4EC
    FontColor #880E4F
}
skinparam rectangle<<model>> {
    BorderColor #6A1B9A
    BackgroundColor #F3E5F5
    FontColor #4A148C
}

package "User Access Layer" as UserLayer {
    rectangle "**User Web Browser**\\nDispatch & Screening Operations" as Browser <<user>>
}

package "Application Server (Internal Windows Server Host)" as HostLayer {
    rectangle "**IIS Web Server**\\nReverse Proxy & Auth Gate" as IIS <<proxy>>
    rectangle "**Static Web Assets**\\nCompiled React / Vite SPA" as UI <<service>>
    rectangle "**FastAPI Backend Service**\\nREST APIs & Feedback Service (:8203)" as API <<service>>
    rectangle "**Diagnostics Worker Engine**\\nScheduled Polling & Pipeline Rules" as Worker <<service>>
}

package "Artificial Intelligence Services" as ModelLayer {
    rectangle "**Language Model Service**\\nSummarization & Triage Inference" as LLM <<model>>
}

package "Integration & Middleware Layer" as MidLayer {
    database "**Configuration Store**\\nSQLite" as SQLite <<db>>
    database "**SQL Server Database**\\nCases & Feedback Tables" as SQL <<db>>
    queue "**Apigee API Gateway**\\nOAuth2 Token Management & Routing" as Apigee <<gateway>>
}

package "Core Telemetry APIs (via Apigee Gateway)" as TelemetryLayer {
    rectangle "**SAA NXT APIs**\\nCable Modem HFC Diagnostics" as SAA <<telemetry>>
    rectangle "**FCAPS Health API**\\nFiber ONT & IPTV Metrics" as FCAPS <<telemetry>>
    rectangle "**Device Mgmt v3 API**\\nSet-Top Box Diagnostics" as CDN <<telemetry>>
    rectangle "**Outage Checker APIs**\\nIE MSP & ServiceNow Incidents" as Outage <<telemetry>>
}

Browser -down-> IIS : HTTPS / Win Auth
IIS -right-> UI
IIS -down-> API : /api/*

API -down-> SQLite : Config DB
API -down-> SQL : Read / Feedback

Worker -down-> SQL : Poll Pending & Store
Worker -right-> LLM : HTTPS
Worker -down-> Apigee : Telemetry Auth

Apigee -down-> SAA : HFC Metrics
Apigee -down-> FCAPS : Fiber Metrics
Apigee -down-> CDN : CDM Metrics
Apigee -down-> Outage : Incident Records

@enduml"""


def convert_diagram_to_plantuml_macro(code: str, feature_slug: str) -> str:
    """Wrap PlantUML diagram in native Confluence storage format macro."""
    code = sanitize_ai_slop_and_punctuation(code)
    puml = get_plantuml_code(code.strip(), feature_slug)
    puml = sanitize_ai_slop_and_punctuation(puml)
    return (
        f'<p><ac:structured-macro ac:name="plantuml" ac:schema-version="1">\n'
        f'<ac:parameter ac:name="atlassian-macro-output-type">INLINE</ac:parameter>\n'
        f'<ac:plain-text-body><![CDATA[{puml}]]></ac:plain-text-body>\n'
        f'</ac:structured-macro></p>'
    )


def markdown_to_confluence_xhtml(
    md_text: str,
    feature_slug: str = "system",
) -> str:
    """Convert full Markdown text to Confluence Storage Format XHTML."""
    cleaned = strip_frontmatter(md_text)
    cleaned = strip_references_and_ai_metadata(cleaned)
    cleaned = sanitize_ai_slop_and_punctuation(cleaned)

    lines = cleaned.splitlines()
    output = []
    i = 0
    in_diagram = False
    diagram_lines = []

    in_table = False
    table_lines = []

    list_stack = []  # stack of (indent_level, list_tag) e.g. (0, 'ul')

    def close_lists_to_indent(target_indent: int):
        while list_stack and list_stack[-1][0] >= target_indent:
            _, tag = list_stack.pop()
            output.append(f"</{tag}>")

    def close_all_lists():
        while list_stack:
            _, tag = list_stack.pop()
            output.append(f"</{tag}>")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Handle Diagram code fence (mermaid or plantuml)
        if stripped.startswith("```mermaid") or stripped.startswith("```plantuml"):
            close_all_lists()
            in_diagram = True
            diagram_lines = []
            i += 1
            continue
        elif in_diagram:
            if stripped.startswith("```"):
                in_diagram = False
                diagram_code = "\n".join(diagram_lines)
                converted_macro = convert_diagram_to_plantuml_macro(diagram_code, feature_slug)
                output.append(converted_macro)
            else:
                diagram_lines.append(line)
            i += 1
            continue

        # Handle regular code block
        if stripped.startswith("```"):
            close_all_lists()
            code_block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_block.append(lines[i])
                i += 1
            i += 1
            code_content = "\n".join(code_block)
            output.append(
                f'<ac:structured-macro ac:name="code" ac:schema-version="1">'
                f"<ac:plain-text-body><![CDATA[{code_content}]]></ac:plain-text-body>"
                f"</ac:structured-macro>"
            )
            continue

        # Handle Markdown table
        if stripped.startswith("|") and stripped.endswith("|"):
            close_all_lists()
            in_table = True
            table_lines.append(stripped)
            i += 1
            continue
        elif in_table:
            in_table = False
            output.append(convert_table(table_lines))
            table_lines = []

        # Empty lines
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if stripped in ("---", "___", "***"):
            close_all_lists()
            output.append("<hr/>")
            i += 1
            continue

        # Table of contents placeholder
        if re.match(r"^#{1,3}\s+Table of Contents\b", stripped, re.IGNORECASE):
            close_all_lists()
            output.append("<h2>Table of Contents</h2>")
            output.append(
                '<p><ac:structured-macro ac:name="toc" ac:schema-version="1"/></p>'
            )
            output.append("<hr/>")
            # Skip subsequent lines until next header
            i += 1
            while i < len(lines) and not re.match(r"^(#{1,6})\s+", lines[i].strip()):
                i += 1
            continue

        # Headers
        header_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if header_match:
            close_all_lists()
            level = len(header_match.group(1))
            htext = format_inline_markdown(header_match.group(2).strip())
            if level == 1:
                output.append(f"<h1>{htext}</h1>")
            else:
                output.append(f"<h{level}>{htext}</h{level}>")
            i += 1
            continue

        # Blockquote / Notice (check for banned notices)
        if stripped.startswith(">"):
            close_all_lists()
            raw_notice = stripped.lstrip(">").strip()
            lower_notice = raw_notice.lower()
            if any(k in lower_notice for k in ["document notice", "simplified technical english", "asd-ste100", "active voice"]):
                i += 1
                continue
            notice_text = format_inline_markdown(raw_notice)
            output.append(f"<p><em>{notice_text}</em></p>")
            i += 1
            continue

        # List items (unordered or ordered)
        indent = len(line) - len(line.lstrip(" "))
        ul_match = re.match(r"^[-*]\s+(.*)$", stripped)
        ol_match = re.match(r"^\d+\.\s+(.*)$", stripped)

        if ul_match or ol_match:
            list_tag = "ul" if ul_match else "ol"
            item_text = format_inline_markdown((ul_match or ol_match).group(1).strip())

            # Manage list nesting
            if not list_stack or indent > list_stack[-1][0]:
                list_stack.append((indent, list_tag))
                output.append(f"<{list_tag}>")
            elif indent < list_stack[-1][0]:
                close_lists_to_indent(indent)
                if not list_stack or list_stack[-1][0] < indent:
                    list_stack.append((indent, list_tag))
                    output.append(f"<{list_tag}>")

            output.append(f"  <li>{item_text}</li>")
            i += 1
            continue
        else:
            close_all_lists()

        # Regular paragraph
        p_text = format_inline_markdown(stripped)
        output.append(f"<p>{p_text}</p>")
        i += 1

    close_all_lists()
    if in_table:
        output.append(convert_table(table_lines))

    return "\n".join(output)


def validate_confluence_xhtml(xhtml_content: str) -> bool:
    """Validate that the XHTML is well-formed XML compatible with Confluence."""
    wrapped = (
        f'<root xmlns:ac="http://www.atlassian.com/schema/confluence/4/ac/" '
        f'xmlns:ri="http://www.atlassian.com/schema/confluence/4/ri/">'
        f"{xhtml_content}"
        f"</root>"
    )
    try:
        ET.fromstring(wrapped)
        return True
    except ET.ParseError as e:
        print(f"XHTML validation error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert HLA Markdown to Confluence Storage Format XHTML with PlantUML macros"
    )
    parser.add_argument("input_file", help="Path to input HLA Markdown file")
    parser.add_argument("--output", "-o", help="Path to output HTML file (optional)")
    parser.add_argument(
        "--slug",
        "-s",
        default="system",
        help="Feature slug for diagram names (e.g. appointment-service)",
    )
    parser.add_argument(
        "--lineage-only",
        action="store_true",
        help="Extract and convert only Section 4.5 (Database and Data Processing Pipeline Lineage)",
    )
    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    content = input_path.read_text(encoding="utf-8")

    if args.lineage_only:
        # Match Section 4.5 (or any heading matching Pipeline Lineage) up to next section or end
        match = re.search(
            r"(###\s*4\.5\s+.*?)(?=(^###\s*4\.6|^##\s*5|\Z))",
            content,
            flags=re.DOTALL | re.MULTILINE,
        )
        if not match:
            print(
                "Error: Section 4.5 (Database Pipeline Lineage) not found in input document.",
                file=sys.stderr,
            )
            sys.exit(1)
        content = match.group(1)

    slug = (
        args.slug if args.slug != "system" else input_path.stem.replace("-hla", "")
    )

    xhtml = markdown_to_confluence_xhtml(
        content,
        feature_slug=slug,
    )

    # Validate XML
    if not validate_confluence_xhtml(xhtml):
        print("Warning: Generated XHTML has XML parsing issues.", file=sys.stderr)
    else:
        print("XHTML validation successful: Content is well-formed XML.")

    if args.output:
        output_path = Path(args.output)
    elif args.lineage_only:
        output_path = input_path.with_name(f"{input_path.stem}-lineage.html")
    else:
        output_path = input_path.with_suffix(".html")

    output_path.write_text(xhtml, encoding="utf-8")
    print(f"Confluence XHTML successfully written to: {output_path}")


if __name__ == "__main__":
    main()
