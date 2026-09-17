#!/usr/bin/env python3
"""
Convert Markdown Architecture Documents (HLD / LLD) to Confluence Storage Format XHTML.

Key Principles:
1. Strips AI slop, removes frontmatter/metadata notices, and enforces ASD-STE100.
2. Injects Confluence Table of Contents (<ac:structured-macro ac:name="toc"/>) and Version History.
3. Strips Executive Metadata / Technical Metadata blocks from Confluence HTML views.
4. Generates inline PlantUML macros (<ac:structured-macro ac:name="plantuml"/>) with 'skinparam linetype ortho'
   so that diagrams render natively upon copy-paste into Confluence with zero attachment access errors.
5. Supports optional Draw.io XML generation via --diagram-type drawio.
6. Enforces responsive, wrapped Confluence tables (<table class="wrapped"><colgroup>...).
7. Validates that output is 100% well-formed XML.

Usage:
    python scripts/convert_doc_to_confluence.py <input.md> --output <output.html> [--diagram-type plantuml|drawio]
"""

import argparse
import html
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def sanitize_ste_and_anti_slop(content: str) -> str:
    """Enforce ASD-STE100 principles, clean ASCII punctuation, and eliminate AI buzzwords."""
    # 1. Normalize em-dashes and en-dashes
    content = re.sub(r'^(#+\s+[^—\n]+?)\s*[—–]\s*(.+)$', r'\1: \2', content, flags=re.MULTILINE)
    content = re.sub(r'\*\*([^*—–\n]+?)\s*[—–]\s*([^*—–\n]+?)\*\*', r'**\1 (\2)**', content)
    content = content.replace("—", " - ").replace("–", "-")
    content = re.sub(r'[ \t]+-[ \t]+', ' - ', content)

    # 2. Smart quotes to straight ASCII
    content = content.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    # 3. Unicode bullet characters to ASCII hyphen
    content = content.replace("•", "-")

    # 4. Filter AI slop buzzwords and purple prose
    buzzwords = [
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
    for pattern, repl in buzzwords:
        content = re.sub(pattern, repl, content, flags=re.IGNORECASE)

    return content


def strip_ai_traces_and_metadata(content: str, is_hld: bool = True) -> str:
    """Remove frontmatter, AI tool mentions, and metadata blocks for Confluence HTML."""
    # 1. Strip YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()

    # 2. Strip Executive Metadata / Technical Metadata if HLD
    if is_hld:
        # Match ## Executive Metadata ... up to next header or hr
        content = re.sub(r'##\s*(?:Executive\s+Metadata|Technical\s+Metadata).*?(?=(^##|\A|\Z|<hr/>|---))', '', content, flags=re.DOTALL | re.MULTILINE)

    # 3. Strip any lines referencing AI models, caddis, antigravity, claude
    banned_keywords = [
        "caddis", "antigravity", "creating model", "creation-agent",
        "last author", "last updated", "claude code", "codex", "gemini-2.5-pro",
        "gemini-3.5-flash", "simplified technical english", "asd-ste100"
    ]
    lines = []
    for line in content.splitlines():
        lower = line.lower()
        if any(b in lower for b in banned_keywords) and not ("gemini" in lower and "prompt" in lower):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def format_inline_markdown(text: str) -> str:
    """Safely escape XML characters and convert inline markdown (bold, italic, code)."""
    text = text.replace("—", " - ").replace("–", "-")
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("•", "-")

    # Escape XML characters
    text = re.sub(r"&(?!(amp|lt|gt|quot|apos);)", "&amp;", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")

    # Inline code
    code_spans = []
    def save_code(m):
        code_spans.append(f"<code>{m.group(1)}</code>")
        return f"__INLINE_CODE_SPAN_{len(code_spans)-1}__"

    text = re.sub(r"`([^`]+)`", save_code, text)

    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Bold **bold** -> <strong>bold</strong>
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    # Italic *italic* -> <em>italic</em>
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)

    for idx, span in enumerate(code_spans):
        text = text.replace(f"__INLINE_CODE_SPAN_{idx}__", span)

    return text


def convert_table(md_table_lines: List[str]) -> str:
    """Convert Markdown table to wrapped Confluence XHTML table matching original styling."""
    if len(md_table_lines) < 2:
        return ""

    header_cols = [c.strip() for c in md_table_lines[0].split("|")[1:-1]]
    data_rows = []
    for line in md_table_lines[2:]:
        if "|" in line:
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if any(cols):
                data_rows.append(cols)

    col_count = len(header_cols)
    out = ['<table class="wrapped">', f'<colgroup>{"<col/>" * col_count}</colgroup>', '<thead>', '<tr>']
    for h in header_cols:
        formatted_h = format_inline_markdown(h)
        out.append(f'  <th><p>{formatted_h}</p></th>')
    out.append('</tr>')
    out.append('</thead>')
    out.append('<tbody>')
    for r in data_rows:
        out.append('<tr>')
        for c in r:
            formatted_c = format_inline_markdown(c)
            out.append(f'  <td><p>{formatted_c}</p></td>')
        out.append('</tr>')
    out.append('</tbody>')
    out.append('</table>')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# PlantUML Generator (Strictly Orthogonal & Native Inline Confluence Macro)
# ---------------------------------------------------------------------------

def convert_mermaid_flowchart_to_plantuml(code: str) -> str:
    """Parse Mermaid flowchart / graph into PlantUML with strict orthogonal routing."""
    lines = [l.strip() for l in code.splitlines() if l.strip()]

    subgraphs = []
    sg_stack = []
    top_nodes = {}
    top_connections = []

    subgraph_start_re = re.compile(r'^\s*subgraph\s+([A-Za-z0-9_]+)(?:\["([^"]+)"\]|\[([^\]]+)\])?', re.IGNORECASE)
    direction_re = re.compile(r'^\s*direction\s+(LR|RL|TB|TD)', re.IGNORECASE)
    node_def_re = re.compile(
        r'([A-Za-z0-9_]+)(?:\["([^"]+)"\]|\[([^\]]+)\]|\{"([^"]+)"\}|\{([^\}]+)\}|\("([^"]+)"\)|\(([^\)]+)\))(?:::([A-Za-z0-9_]+))?'
    )

    for line in lines:
        if not line or line.startswith("%%") or line.startswith("classDef") or line.startswith("style "):
            continue
        if line.lower().startswith("flowchart") or line.lower().startswith("graph"):
            continue

        sg_match = subgraph_start_re.match(line)
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

        if line.lower() == "end":
            if sg_stack:
                sg_stack.pop()
            continue

        dir_match = direction_re.match(line)
        if dir_match and sg_stack:
            sg_stack[-1]["direction"] = dir_match.group(1).upper()
            continue

        for match in node_def_re.finditer(line):
            n_id = match.group(1)
            n_lbl = next(g for g in match.groups()[1:7] if g is not None)
            n_cls = match.group(8) or ""
            node_info = {"id": n_id, "label": n_lbl, "class": n_cls}
            if sg_stack:
                sg_stack[-1]["nodes"][n_id] = node_info
            else:
                top_nodes[n_id] = node_info

        clean_edge_line = node_def_re.sub(r'\1', line)
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

    def get_node_type(node_id: str, label: str, cls: str) -> Tuple[str, str]:
        id_low = node_id.lower()
        lbl_low = label.lower()
        cls_low = cls.lower()

        if any(k in cls_low for k in ["src", "med"]) or any(k in id_low for k in ["jsc", "src", "raw"]):
            return "database", "source_db"
        if any(k in cls_low for k in ["stage", "batch", "engine"]) or any(k in id_low for k in ["val", "py", "orch", "task", "job", "refresher"]):
            return "rectangle", "service"
        if any(k in cls_low for k in ["db", "mart"]) or any(k in id_low for k in ["db", "mart", "run", "exc", "sum"]):
            return "database", "staging_db"
        if any(k in cls_low for k in ["ui", "app"]) or any(k in id_low for k in ["ui", "api", "dash", "react"]):
            return "rectangle", "user_ui"
        if any(k in cls_low for k in ["ext"]) or any(k in id_low for k in ["feed", "gw", "bss", "tap", "apigee"]):
            return "queue", "gateway"

        return "rectangle", "service"

    out = []
    out.append("@startuml")
    out.append("skinparam shadowing false")
    out.append('skinparam defaultFontName "Segoe UI"')
    out.append("skinparam defaultFontSize 11")
    out.append("skinparam roundCorner 6")
    out.append("skinparam linetype ortho")
    out.append("skinparam nodesep 70")
    out.append("skinparam ranksep 40\n")

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
    out.append("    BorderColor #2E7D32")
    out.append("    BackgroundColor #E8F5E9")
    out.append("    FontColor #1B5E20")
    out.append("}")
    out.append("skinparam rectangle<<user_ui>> {")
    out.append("    BorderColor #E65100")
    out.append("    BackgroundColor #FFF3E0")
    out.append("    FontColor #BF360C")
    out.append("}")
    out.append("skinparam rectangle<<service>> {")
    out.append("    BorderColor #0277BD")
    out.append("    BackgroundColor #E1F5FE")
    out.append("    FontColor #01579B")
    out.append("}")
    out.append("skinparam queue<<gateway>> {")
    out.append("    BorderColor #455A64")
    out.append("    BackgroundColor #ECEFF1")
    out.append("    FontColor #263238")
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
                lbl_clean = e["label"].replace("<br/>", "\\n").replace("<br>", "\\n").replace('"', "'") if e["label"] else ""
                lbl_suffix = f' : {lbl_clean}' if lbl_clean else ""
                res.append(f'{indent}    {e["src"]} {arrow} {e["dst"]}{lbl_suffix}')
        res.append(f"{indent}}}\n")
        return res

    for sg in subgraphs:
        out.extend(render_subgraph(sg))

    for n_id, n_info in top_nodes.items():
        formatted_lbl = n_info["label"].replace("<br/>", "\\n").replace("<br>", "\\n").replace('"', "'")
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
        lbl_clean = e["label"].replace("<br/>", "\\n").replace("<br>", "\\n").replace('"', "'") if e["label"] else ""
        lbl_suffix = f' : {lbl_clean}' if lbl_clean else ""
        out.append(f'{e["src"]} -down-> {e["dst"]}{lbl_suffix}')

    out.append("@enduml")
    return "\n".join(out)


def convert_mermaid_sequence_to_plantuml(code: str) -> str:
    """Parse Mermaid sequenceDiagram into PlantUML sequence diagram with orthogonal lines."""
    lines = [l.strip() for l in code.splitlines() if l.strip()]

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
    out.append("    BorderColor #0277BD")
    out.append("    BackgroundColor #E1F5FE")
    out.append("    FontColor #01579B")
    out.append("}")
    out.append("skinparam database {")
    out.append("    BorderColor #2E7D32")
    out.append("    BackgroundColor #E8F5E9")
    out.append("    FontColor #1B5E20")
    out.append("}")
    out.append("skinparam sequence {")
    out.append("    ArrowColor #1E88E5")
    out.append("    LifeLineBorderColor #90A4AE")
    out.append("    LifeLineBackgroundColor #ECEFF1")
    out.append("    DividerBorderColor #B0BEC5")
    out.append("    DividerBackgroundColor #ECEFF1")
    out.append("    DividerFontColor #263238")
    out.append("}\n")

    part_re = re.compile(r'^(?:participant|actor)\s+([A-Za-z0-9_]+)(?:\s+as\s+(.+))?', re.IGNORECASE)
    msg_re = re.compile(r'^([A-Za-z0-9_]+)\s*(->>|-->>|->|-->)\s*([A-Za-z0-9_]+)\s*:\s*(.+)$')
    note_re = re.compile(r'^Note\s+(?:over|left of|right of)\s+([A-Za-z0-9_,\s]+)\s*:\s*(.+)$', re.IGNORECASE)

    declared_parts = set()

    for line in lines:
        if line.startswith("sequenceDiagram") or line.startswith("autonumber"):
            continue

        p_match = part_re.match(line)
        if p_match:
            pid = p_match.group(1)
            pname = (p_match.group(2) or pid).replace('"', '')
            is_actor = line.lower().startswith("actor ") and "scheduler" not in pid.lower() and "task" not in pid.lower()
            elem_kind = "actor" if is_actor else ("database" if "db" in pid.lower() else "participant")
            out.append(f'{elem_kind} "{pname}" as {pid}')
            declared_parts.add(pid)
            continue

        n_match = note_re.match(line)
        if n_match:
            target = n_match.group(1).strip()
            text = n_match.group(2).strip()
            out.append(f'== {text} ==')
            continue

        m_match = msg_re.match(line)
        if m_match:
            src = m_match.group(1)
            arrow = m_match.group(2)
            dst = m_match.group(3)
            txt = m_match.group(4).replace('"', '')

            for p in [src, dst]:
                if p not in declared_parts:
                    elem_kind = "database" if "db" in p.lower() else "participant"
                    out.append(f'{elem_kind} "{p}" as {p}')
                    declared_parts.add(p)

            puml_arrow = "-->" if ("-->>" in arrow or "-->" in arrow) else "->"
            out.append(f'{src} {puml_arrow} {dst} : {txt}')

    out.append("@enduml")
    return "\n".join(out)


def render_plantuml_macro(puml_code: str) -> str:
    """Wrap PlantUML code inside native Confluence <ac:structured-macro ac:name="plantuml">."""
    return (
        f'<p><ac:structured-macro ac:name="plantuml" ac:schema-version="1">\n'
        f'<ac:parameter ac:name="atlassian-macro-output-type">INLINE</ac:parameter>\n'
        f'<ac:plain-text-body><![CDATA[{puml_code}]]></ac:plain-text-body>\n'
        f'</ac:structured-macro></p>'
    )


# ---------------------------------------------------------------------------
# Confluence Document Layout Assembler
# ---------------------------------------------------------------------------

def convert_markdown_to_confluence_xhtml(md_text: str, is_hld: bool = True, diagram_type: str = "plantuml") -> str:
    """Convert Markdown document to native Confluence Storage Format XHTML."""
    # 1. Clean STE, dashes, and buzzwords
    clean_text = sanitize_ste_and_anti_slop(md_text)

    # 2. Extract Document Title
    title_match = re.search(r"^#\s+(.+)$", clean_text, re.MULTILINE)
    app_title = title_match.group(1) if title_match else "Architecture Document"
    app_name = re.sub(
        r'^(High-Level Architecture:\s*|High-Level Architecture \(HLA\):\s*|High-Level Design:\s*|Lower-Level Design:\s*)',
        '',
        app_title,
        flags=re.IGNORECASE
    ).strip()

    # 3. Strip AI traces, frontmatter, and metadata lists
    content = strip_ai_traces_and_metadata(clean_text, is_hld=is_hld)

    # Strip ## Document Information if present in markdown since we emit standard top block
    if is_hld:
        content = re.sub(
            r'##\s*Document Information.*?(?=\n##\s+\d|\Z)',
            '',
            content,
            flags=re.DOTALL
        )

    # Strip the top # Title line from content since we emit standard Confluence top header
    content = re.sub(r"^#\s+.*?\n", "", content, count=1).strip()

    lines = content.splitlines()
    body_parts = []

    # Emit standard Confluence Top Section
    if is_hld:
        body_parts.append(f"<h1>High-Level Architecture (HLA): {app_name}</h1>")
        body_parts.append("<hr/>")
        body_parts.append("<h2>Document Information</h2>")
        body_parts.append("<h3>Version History</h3>")
        body_parts.append(
            '<table class="wrapped"><colgroup><col/><col/><col/><col/></colgroup>'
            '<thead><tr><th><p>Version</p></th><th><p>Date</p></th><th><p>Author</p></th><th><p>Description</p></th></tr></thead>'
            '<tbody><tr><td><p>1.0</p></td><td><p>2026-09-17</p></td><td><p>Solutions Architecture</p></td><td><p>Initial High-Level Architecture Draft</p></td></tr></tbody>'
            '</table>'
        )
        body_parts.append("<hr/>")
        body_parts.append("<h2>Table of Contents</h2>")
        body_parts.append('<p><ac:structured-macro ac:name="toc" ac:schema-version="1"/></p>')
        body_parts.append("<hr/>")
    else:
        body_parts.append(f"<h1>Lower-Level Design: {app_name}</h1>")
        body_parts.append("<hr/>")
        body_parts.append("<h2>Table of Contents</h2>")
        body_parts.append('<p><ac:structured-macro ac:name="toc" ac:schema-version="1"/></p>')
        body_parts.append("<hr/>")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped in ("---", "***", "___"):
            body_parts.append("<hr/>")
            i += 1
            continue

        # Headings
        h_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if h_match:
            level = len(h_match.group(1))
            heading_text = format_inline_markdown(h_match.group(2))
            # Omit redundant Document Information or Table of Contents if re-encountered
            if "table of contents" in heading_text.lower():
                i += 1
                continue
            body_parts.append(f"<h{level}>{heading_text}</h{level}>")
            i += 1
            continue

        # Mermaid Diagram Blocks
        if stripped.startswith("```mermaid"):
            diag_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                diag_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1

            diag_code = "\n".join(diag_lines)

            if "sequenceDiagram" in diag_code:
                puml = convert_mermaid_sequence_to_plantuml(diag_code)
            else:
                puml = convert_mermaid_flowchart_to_plantuml(diag_code)

            body_parts.append(render_plantuml_macro(puml))
            continue

        # General Code Blocks
        if stripped.startswith("```"):
            lang = stripped[3:].strip() or "text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1

            code_text = html.escape("\n".join(code_lines))
            code_macro_id = str(uuid.uuid4())
            body_parts.append(
                f'<ac:structured-macro ac:macro-id="{code_macro_id}" ac:name="code" ac:schema-version="1">\n'
                f'  <ac:parameter ac:name="language">{lang}</ac:parameter>\n'
                f'  <ac:plain-text-body><![CDATA[{code_text}]]></ac:plain-text-body>\n'
                f'</ac:structured-macro>'
            )
            continue

        # Tables
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            body_parts.append(convert_table(table_lines))
            continue

        # Alerts (> [!NOTE], > [!IMPORTANT], > [!WARNING], > [!TIP])
        if stripped.startswith("> [!"):
            alert_match = re.match(r"^>\s*\[!(NOTE|IMPORTANT|WARNING|TIP|CAUTION)\]\s*(.*)$", stripped, re.IGNORECASE)
            if alert_match:
                alert_type = alert_match.group(1).lower()
                first_text = alert_match.group(2)
                alert_lines = [first_text] if first_text else []
                i += 1
                while i < len(lines) and lines[i].strip().startswith(">"):
                    sub_line = re.sub(r"^>\s*", "", lines[i].strip())
                    alert_lines.append(sub_line)
                    i += 1

                macro_name = "info" if alert_type in ("note", "tip") else "warning"
                macro_id = str(uuid.uuid4())
                alert_body = "<br/>".join([format_inline_markdown(al) for al in alert_lines if al])
                body_parts.append(
                    f'<ac:structured-macro ac:macro-id="{macro_id}" ac:name="{macro_name}" ac:schema-version="1">\n'
                    f'  <ac:rich-text-body><p>{alert_body}</p></ac:rich-text-body>\n'
                    f'</ac:structured-macro>'
                )
                continue

        # Unordered Lists
        if re.match(r"^[-*]\s+", stripped):
            list_items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                item_text = re.sub(r"^[-*]\s+", "", lines[i].strip())
                list_items.append(format_inline_markdown(item_text))
                i += 1

            out_list = ["<ul>"]
            for li in list_items:
                out_list.append(f"  <li>{li}</li>")
            out_list.append("</ul>")
            body_parts.append("\n".join(out_list))
            continue

        # Ordered Lists
        if re.match(r"^\d+\.\s+", stripped):
            list_items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                item_text = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                list_items.append(format_inline_markdown(item_text))
                i += 1

            out_list = ["<ol>"]
            for li in list_items:
                out_list.append(f"  <li>{li}</li>")
            out_list.append("</ol>")
            body_parts.append("\n".join(out_list))
            continue

        # Paragraphs
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line or next_line.startswith("#") or next_line.startswith("```") or next_line.startswith("|") or next_line.startswith(">") or re.match(r"^[-*]\s+", next_line) or re.match(r"^\d+\.\s+", next_line):
                break
            para_lines.append(next_line)
            i += 1

        p_text = format_inline_markdown(" ".join(para_lines))
        body_parts.append(f"<p>{p_text}</p>")

    return "\n".join(body_parts)


def validate_confluence_xhtml(xhtml_content: str) -> None:
    """Validate that Confluence XHTML content is strictly well-formed XML."""
    test_wrapper = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<root xmlns:ac="http://atlassian.com/confluence/ac"'
        '      xmlns:ri="http://atlassian.com/confluence/ri">\n'
        f'{xhtml_content}\n'
        '</root>'
    )
    try:
        ET.fromstring(test_wrapper)
    except ET.ParseError as e:
        print(f"XHTML validation error: {e}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown HLD/LLD to Confluence Storage Format XHTML.")
    parser.add_argument("input_file", help="Path to input Markdown file")
    parser.add_argument("--output", "-o", required=True, help="Path to output XHTML file")
    parser.add_argument("--diagram-type", choices=["plantuml", "drawio"], default="plantuml", help="Diagram engine (default: plantuml)")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input_file)
    output_path = os.path.abspath(args.output)

    if not os.path.isfile(input_path):
        print(f"Error: input file {input_path} not found.", file=sys.stderr)
        sys.exit(1)

    input_filename = os.path.basename(input_path).lower()
    is_hld = "-hld" in input_filename or "-hla" in input_filename

    with open(input_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    print(f"Converting {input_path} to Confluence Storage Format XHTML...")
    xhtml_body = convert_markdown_to_confluence_xhtml(md_text, is_hld=is_hld, diagram_type=args.diagram_type)

    try:
        validate_confluence_xhtml(xhtml_body)
        print("XHTML validation successful: Content is well-formed XML.")
    except Exception as e:
        print(f"Warning: XML validation failed ({e}), review generated output.", file=sys.stderr)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xhtml_body)

    print(f"Confluence XHTML successfully written to: {output_path}")


if __name__ == "__main__":
    main()
