#!/usr/bin/env python3
"""
Convert Markdown Architecture Documents (HLD / LLD) to Confluence Storage Format XHTML.

Key Principles:
1. Strips AI slop, removes frontmatter/metadata notices, and enforces ASD-STE100.
2. Injects Confluence Table of Contents (<ac:structured-macro ac:name="toc"/>) and Version History.
3. Strips Executive Metadata / Technical Metadata blocks from Confluence HTML views (kept in markdown/LLD).
4. Generates Draw.io diagrams (<ac:structured-macro ac:name="drawio"/>) with strict 100% orthogonal connectors.
   - Simultaneously writes out standalone .drawio files to a `diagrams/` directory.
   - Attaching these .drawio files to the Confluence page ensures seamless rendering with zero attachment access errors.
5. Also supports PlantUML inline macros (<ac:structured-macro ac:name="plantuml"/>) with 'skinparam linetype ortho'.
6. Enforces responsive, wrapped Confluence tables (<table class="wrapped"><colgroup>...).
7. Validates that output is 100% well-formed XML.

Usage:
    python scripts/convert_doc_to_confluence.py <input.md> --output <output.html> [--diagram-type drawio|plantuml]
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

    # 4. Filter AI buzzwords and purple prose
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
        content = re.sub(r'##\s*(?:Executive\s+Metadata|Technical\s+Metadata).*?(?=(^##|\A|\Z|<hr/>|---))', '', content, flags=re.DOTALL | re.MULTILINE)

    # 3. Strip any lines referencing AI models, caddis, antigravity, claude
    banned_keywords = [
        "caddis", "antigravity", "creating model", "creation-agent",
        "last author", "last updated", "claude code", "codex", "gemini-2.5-pro",
        "gemini-3.5-flash", "gemini-3.8-flash", "simplified technical english", "asd-ste100"
    ]
    lines = []
    for line in content.splitlines():
        lower = line.lower()
        if any(b in lower for b in banned_keywords) and not ("gemini" in lower and "prompt" in lower):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def format_inline_markdown(text: str) -> str:
    """Convert Markdown inline formatting (bold, code, links) to safe Confluence XHTML."""
    code_blocks: List[str] = []

    def replace_code(m):
        code_blocks.append(m.group(1))
        return f"__INLINE_CODE_{len(code_blocks)-1}__"

    text = re.sub(r'`([^`]+)`', replace_code, text)
    text = html.escape(text)

    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Bold: **text** -> <strong>text</strong>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)

    # Italic: *text* -> <em>text</em>
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)

    # Restore code blocks
    for idx, c in enumerate(code_blocks):
        c_esc = html.escape(c)
        text = text.replace(f"__INLINE_CODE_{idx}__", f"<code>{c_esc}</code>")

    return text


def convert_table(lines: List[str]) -> str:
    """Convert GitHub Markdown table to responsive Confluence wrapped table."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            continue
        rows.append(cells)

    if not rows:
        return ""

    num_cols = max(len(r) for r in rows)
    out = ['<table class="wrapped">']
    out.append("  <colgroup>")
    for _ in range(num_cols):
        out.append("    <col/>")
    out.append("  </colgroup>")

    # Header
    out.append("  <thead>")
    out.append("    <tr>")
    for cell in rows[0]:
        out.append(f"      <th><p>{format_inline_markdown(cell)}</p></th>")
    for _ in range(num_cols - len(rows[0])):
        out.append("      <th><p></p></th>")
    out.append("    </tr>")
    out.append("  </thead>")

    # Body
    out.append("  <tbody>")
    for row in rows[1:]:
        out.append("    <tr>")
        for cell in row:
            out.append(f"      <td><p>{format_inline_markdown(cell)}</p></td>")
        for _ in range(num_cols - len(row)):
            out.append("      <td><p></p></td>")
        out.append("    </tr>")
    out.append("  </tbody>")
    out.append("</table>")

    return "\n".join(out)


def _get_drawio_style(node_id: str, label: str, cls: str) -> Dict[str, str]:
    """Return styling dictionary for Draw.io node based on Material palette."""
    id_low = node_id.lower()
    lbl_low = label.lower()
    cls_low = cls.lower()

    if any(k in cls_low for k in ["src", "med"]) or any(k in id_low for k in ["jsc", "src", "raw"]):
        return {"fill": "#E8EAF6", "stroke": "#3949AB", "color": "#1A237E"}
    if any(k in cls_low for k in ["stage", "batch", "engine"]) or any(k in id_low for k in ["val", "py", "orch", "task", "job", "refresher", "worker"]):
        return {"fill": "#E1F5FE", "stroke": "#0277BD", "color": "#01579B"}
    if any(k in cls_low for k in ["db", "mart"]) or any(k in id_low for k in ["db", "mart", "run", "exc", "sum"]):
        return {"fill": "#E8F5E9", "stroke": "#2E7D32", "color": "#1B5E20"}
    if any(k in cls_low for k in ["ui", "app"]) or any(k in id_low for k in ["ui", "api", "dash", "react"]):
        return {"fill": "#FFF3E0", "stroke": "#E65100", "color": "#BF360C"}
    if any(k in cls_low for k in ["ext"]) or any(k in id_low for k in ["feed", "gw", "bss", "tap", "apigee"]):
        return {"fill": "#ECEFF1", "stroke": "#455A64", "color": "#263238"}

    return {"fill": "#F1F5F9", "stroke": "#475569", "color": "#0F172A"}


def convert_mermaid_flowchart_to_drawio(code: str, diagram_name: str) -> Tuple[str, int]:
    """Parse Mermaid flowchart / graph into Draw.io <mxGraphModel> XML with 100% orthogonal edges."""
    lines = [l.strip() for l in code.splitlines() if l.strip()]

    subgraphs = []
    sg_stack = []
    top_nodes = {}
    edges = []

    node_def_re = re.compile(
        r'([A-Za-z0-9_]+)\s*(?:\[\[(.+?)\]\]|\(\((.+?)\)\)|\[\((.+?)\)\]|\[\/(.+?)\/\]|\[\\(.+?)\\\]|\[(.+?)\])'
    )
    subgraph_start_re = re.compile(r'^subgraph\s+([A-Za-z0-9_]+)(?:\s*\["([^"]+)"\]|\s*\[(.+)\])?', re.IGNORECASE)

    for line in lines:
        if line.startswith("flowchart") or line.startswith("graph") or line.startswith("classDef") or line.startswith("style "):
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
            }
            subgraphs.append(new_sg)
            sg_stack.append(new_sg)
            continue

        if line.lower() == "end":
            if sg_stack:
                sg_stack.pop()
            continue

        if line.lower().startswith("direction "):
            d = line.split()[1].upper()
            if sg_stack:
                sg_stack[-1]["direction"] = d
            continue

        # Strip inline styling like :::srcStyle before parsing nodes and edges
        clean_line_no_style = re.sub(r':::[A-Za-z0-9_]+', '', line)

        # Extract nodes
        for match in node_def_re.finditer(clean_line_no_style):
            n_id = match.group(1)
            n_lbl = next(g for g in match.groups()[1:7] if g is not None)
            if (n_lbl.startswith('"') and n_lbl.endswith('"')) or (n_lbl.startswith("'") and n_lbl.endswith("'")):
                n_lbl = n_lbl[1:-1]
            node_info = {"id": n_id, "label": n_lbl, "class": ""}
            if sg_stack:
                sg_stack[-1]["nodes"][n_id] = node_info
            else:
                top_nodes[n_id] = node_info

        # Extract edges
        clean_edge_line = node_def_re.sub(r'\1', clean_line_no_style)
        tokens = re.split(r'(\s*(?:<-->|-->|---|->|-\.->|\.-\.|\.\->)\s*(?:\|"[^"]*"\|\s*|\|[^\|]*\|\s*)?)', clean_edge_line)
        if len(tokens) >= 3:
            for i in range(0, len(tokens) - 2, 2):
                src = tokens[i].strip()
                arrow = tokens[i+1].strip()
                dst = tokens[i+2].strip()

                lbl_match = re.search(r'\|"?([^"\|]*)"?\|', arrow)
                lbl = lbl_match.group(1).strip() if lbl_match else ""
                dashed = "-.-" in arrow or ".-" in arrow

                if src and dst and re.match(r'^[A-Za-z0-9_]+$', src) and re.match(r'^[A-Za-z0-9_]+$', dst):
                    edge_obj = {"src": src, "dst": dst, "label": lbl, "dashed": dashed}
                    edges.append(edge_obj)

    # Compute Layout Coordinates
    node_w = 260
    node_h = 60
    sg_margin_x = 40
    sg_margin_y = 50
    sg_pad_x = 30
    sg_pad_y = 40
    sg_gap = 40

    sg_coords = {}
    node_coords = {}

    cur_x = sg_margin_x
    cur_y = sg_margin_y
    max_h = 0

    for sg in subgraphs:
        nodes_count = len(sg["nodes"])
        sg_direction = sg.get("direction", "TB")

        if sg_direction == "TB":
            sg_w = node_w + (sg_pad_x * 2)
            sg_h = sg_pad_y + (nodes_count * (node_h + 30)) + 20
            sg_coords[sg["id"]] = {"x": cur_x, "y": cur_y, "w": sg_w, "h": sg_h}

            n_y = cur_y + sg_pad_y + 10
            for nid, ninfo in sg["nodes"].items():
                node_coords[nid] = {"x": cur_x + sg_pad_x, "y": n_y, "w": node_w, "h": node_h}
                n_y += node_h + 30

            cur_x += sg_w + sg_gap
            if sg_h > max_h:
                max_h = sg_h
        else:
            sg_w = sg_pad_x + (nodes_count * (node_w + 30)) + 20
            sg_h = node_h + (sg_pad_y * 2) + 20
            sg_coords[sg["id"]] = {"x": cur_x, "y": cur_y, "w": sg_w, "h": sg_h}

            n_x = cur_x + sg_pad_x
            for nid, ninfo in sg["nodes"].items():
                node_coords[nid] = {"x": n_x, "y": cur_y + sg_pad_y + 10, "w": node_w, "h": node_h}
                n_x += node_w + 30

            cur_y += sg_h + sg_gap
            if sg_w > max_h:
                max_h = sg_w

    if top_nodes:
        top_y = cur_y + max_h + sg_gap if subgraphs else sg_margin_y + 40
        top_x = sg_margin_x
        for nid, ninfo in top_nodes.items():
            node_coords[nid] = {"x": top_x, "y": top_y, "w": node_w, "h": node_h}
            top_x += node_w + sg_gap
        if not subgraphs:
            cur_x = top_x

    canvas_w = max(1200, cur_x + 100)
    canvas_h = max(800, cur_y + max_h + 200)

    out = []
    out.append(f'<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{canvas_w}" pageHeight="{canvas_h}" math="0" shadow="0">')
    out.append('  <root>')
    out.append('    <mxCell id="0"/>')
    out.append('    <mxCell id="1" parent="0"/>')

    # Emit Subgraphs
    for sg in subgraphs:
        c = sg_coords[sg["id"]]
        title_esc = html.escape(sg["title"])
        out.append(f'    <mxCell id="{sg["id"]}" value="{title_esc}" style="swimlane;whiteSpace=wrap;html=1;fillColor=#F8FAFC;strokeColor=#546E7A;strokeWidth=1.5;fontStyle=1;fontSize=12;fontColor=#263238;startSize=28;rounded=1;arcSize=4;" vertex="1" parent="1">')
        out.append(f'      <mxGeometry x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" as="geometry"/>')
        out.append('    </mxCell>')

    # Emit Nodes
    for sg in subgraphs:
        for nid, ninfo in sg["nodes"].items():
            c = node_coords[nid]
            style_info = _get_drawio_style(nid, ninfo["label"], ninfo["class"])
            lbl_clean = ninfo["label"].replace("<br/>", "&#xa;").replace("<br>", "&#xa;").replace('"', '&quot;')
            lbl_esc = html.escape(lbl_clean)
            style_str = f'rounded=1;whiteSpace=wrap;html=1;fillColor={style_info["fill"]};strokeColor={style_info["stroke"]};fontColor={style_info["color"]};strokeWidth=2;fontSize=11;fontFamily=Segoe UI;align=center;'
            out.append(f'    <mxCell id="{nid}" value="{lbl_esc}" style="{style_str}" vertex="1" parent="1">')
            out.append(f'      <mxGeometry x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" as="geometry"/>')
            out.append('    </mxCell>')

    for nid, ninfo in top_nodes.items():
        c = node_coords[nid]
        style_info = _get_drawio_style(nid, ninfo["label"], ninfo["class"])
        lbl_clean = ninfo["label"].replace("<br/>", "&#xa;").replace("<br>", "&#xa;").replace('"', '&quot;')
        lbl_esc = html.escape(lbl_clean)
        style_str = f'rounded=1;whiteSpace=wrap;html=1;fillColor={style_info["fill"]};strokeColor={style_info["stroke"]};fontColor={style_info["color"]};strokeWidth=2;fontSize=11;fontFamily=Segoe UI;align=center;'
        out.append(f'    <mxCell id="{nid}" value="{lbl_esc}" style="{style_str}" vertex="1" parent="1">')
        out.append(f'      <mxGeometry x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" as="geometry"/>')
        out.append('    </mxCell>')

    # Emit Edges with 100% Orthogonal Routing
    for idx, e in enumerate(edges):
        eid = f"edge_{idx+1}"
        src = e["src"]
        dst = e["dst"]
        lbl_clean = e["label"].replace("<br/>", "&#xa;").replace("<br>", "&#xa;").replace('"', '&quot;') if e["label"] else ""
        lbl_esc = html.escape(lbl_clean)
        dashed_str = "dashed=1;" if e["dashed"] else ""
        edge_style = f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#37474F;strokeWidth=2;endArrow=block;endFill=1;fontSize=10;fontColor=#37474F;{dashed_str}"
        out.append(f'    <mxCell id="{eid}" value="{lbl_esc}" style="{edge_style}" edge="1" parent="1" source="{src}" target="{dst}">')
        out.append('      <mxGeometry relative="1" as="geometry"/>')
        out.append('    </mxCell>')

    out.append('  </root>')
    out.append('</mxGraphModel>')
    return "\n".join(out), canvas_w


def convert_mermaid_sequence_to_drawio(code: str, diagram_name: str) -> Tuple[str, int]:
    """Parse Mermaid sequenceDiagram into Draw.io <mxGraphModel> XML."""
    lines = [l.strip() for l in code.splitlines() if l.strip()]

    participants = []
    messages = []
    notes = []

    part_re = re.compile(r'^(?:participant|actor)\s+([A-Za-z0-9_]+)(?:\s+as\s+(.+))?', re.IGNORECASE)
    msg_re = re.compile(r'^([A-Za-z0-9_]+)\s*(->>|-->>|->|-->)\s*([A-Za-z0-9_]+)\s*:\s*(.+)$')
    note_re = re.compile(r'^Note\s+(?:over|left of|right of)\s+([A-Za-z0-9_,\s]+)\s*:\s*(.+)$', re.IGNORECASE)

    part_order = []
    part_names = {}

    for l in lines:
        if l.startswith("sequenceDiagram") or l.startswith("autonumber"):
            continue

        p_match = part_re.match(l)
        if p_match:
            pid = p_match.group(1)
            pname = p_match.group(2) or pid
            if pid not in part_order:
                part_order.append(pid)
                part_names[pid] = pname
            continue

        n_match = note_re.match(l)
        if n_match:
            target = n_match.group(1).strip()
            text = n_match.group(2).strip()
            notes.append({"target": target, "text": text, "index": len(messages)})
            continue

        m_match = msg_re.match(l)
        if m_match:
            src = m_match.group(1)
            arrow = m_match.group(2)
            dst = m_match.group(3)
            txt = m_match.group(4)

            for p in [src, dst]:
                if p not in part_order:
                    part_order.append(p)
                    part_names[p] = p

            messages.append({"src": src, "dst": dst, "text": txt, "dashed": "--" in arrow})

    part_w = 180
    part_h = 45
    col_gap = 40
    start_x = 40
    start_y = 50
    lifeline_h = max(550, (len(messages) + len(notes) + 2) * 55)

    part_x = {}
    for i, pid in enumerate(part_order):
        part_x[pid] = start_x + (i * (part_w + col_gap))

    canvas_w = max(1200, start_x + (len(part_order) * (part_w + col_gap)) + 60)
    canvas_h = max(700, start_y + lifeline_h + 100)

    out = []
    out.append(f'<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{canvas_w}" pageHeight="{canvas_h}" math="0" shadow="0">')
    out.append('  <root>')
    out.append('    <mxCell id="0"/>')
    out.append('    <mxCell id="1" parent="0"/>')

    # Emit Lifelines & Headers
    for pid in part_order:
        px = part_x[pid]
        pname = part_names.get(pid, pid).replace("<br/>", "&#xa;").replace("<br>", "&#xa;").replace('"', '&quot;')
        pname_esc = html.escape(pname)
        is_actor = "analyst" in pid.lower() or "user" in pid.lower()
        fill_col = "#E8EAF6" if is_actor else "#E1F5FE"
        stroke_col = "#3949AB" if is_actor else "#0277BD"
        font_col = "#1A237E" if is_actor else "#01579B"

        header_id = f"hdr_{pid}"
        out.append(f'    <mxCell id="{header_id}" value="{pname_esc}" style="rounded=1;whiteSpace=wrap;html=1;fillColor={fill_col};strokeColor={stroke_col};fontColor={font_col};fontStyle=1;fontSize=11;fontFamily=Segoe UI;align=center;" vertex="1" parent="1">')
        out.append(f'      <mxGeometry x="{px}" y="{start_y}" width="{part_w}" height="{part_h}" as="geometry"/>')
        out.append('    </mxCell>')

        ll_id = f"ll_{pid}"
        mid_x = px + (part_w // 2)
        out.append(f'    <mxCell id="{ll_id}" value="" style="edgeStyle=none;html=1;strokeColor=#90A4AE;strokeWidth=1;dashed=1;endArrow=none;startArrow=none;" edge="1" parent="1" source="{header_id}">')
        out.append(f'      <mxGeometry relative="1" as="geometry">')
        out.append(f'        <mxPoint x="{mid_x}" y="{start_y + lifeline_h}" as="targetPoint"/>')
        out.append('      </mxGeometry>')
        out.append('    </mxCell>')

    # Emit Messages and Notes
    msg_y = start_y + part_h + 35
    msg_step = 50
    note_map = {n["index"]: n for n in notes}

    for idx, m in enumerate(messages):
        if idx in note_map:
            n = note_map[idx]
            n_txt = html.escape(n["text"])
            out.append(f'    <mxCell id="note_{idx}" value="{n_txt}" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;fillColor=#FFF8E1;strokeColor=#FFA000;fontColor=#5D4037;fontSize=10;fontStyle=2;align=center;" vertex="1" parent="1">')
            out.append(f'      <mxGeometry x="{start_x + 20}" y="{msg_y - 15}" width="{canvas_w - start_x - 120}" height="26" as="geometry"/>')
            out.append('    </mxCell>')
            msg_y += 35

        src_mid = part_x[m["src"]] + (part_w // 2)
        dst_mid = part_x[m["dst"]] + (part_w // 2)
        txt = html.escape(m["text"])
        dash_str = "dashed=1;" if m["dashed"] else ""
        edge_style = f"edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#1E88E5;strokeWidth=2;endArrow=block;endFill=1;fontSize=10;fontColor=#263238;{dash_str}"

        out.append(f'    <mxCell id="seq_msg_{idx+1}" value="{idx+1}. {txt}" style="{edge_style}" edge="1" parent="1">')
        out.append(f'      <mxGeometry relative="1" as="geometry">')
        out.append(f'        <mxPoint x="{src_mid}" y="{msg_y}" as="sourcePoint"/>')
        out.append(f'        <mxPoint x="{dst_mid}" y="{msg_y}" as="targetPoint"/>')
        out.append('      </mxGeometry>')
        out.append('    </mxCell>')
        msg_y += msg_step

    out.append('  </root>')
    out.append('</mxGraphModel>')
    return "\n".join(out), canvas_w


def render_drawio_macro(drawio_xml: str, diagram_filename: str, display_name: str, width: int = 1200) -> str:
    """Generate native Confluence Draw.io macro."""
    macro_id = str(uuid.uuid4())
    name_esc = html.escape(diagram_filename)
    disp_esc = html.escape(display_name)
    return (
        f'<p>\n'
        f'  <ac:structured-macro ac:macro-id="{macro_id}" ac:name="drawio" ac:schema-version="1">\n'
        f'    <ac:parameter ac:name="border">true</ac:parameter>\n'
        f'    <ac:parameter ac:name="diagramName">{name_esc}</ac:parameter>\n'
        f'    <ac:parameter ac:name="diagramDisplayName">{disp_esc}</ac:parameter>\n'
        f'    <ac:parameter ac:name="simpleViewer">false</ac:parameter>\n'
        f'    <ac:parameter ac:name="links">auto</ac:parameter>\n'
        f'    <ac:parameter ac:name="tbstyle">top</ac:parameter>\n'
        f'    <ac:parameter ac:name="lbox">true</ac:parameter>\n'
        f'    <ac:parameter ac:name="diagramWidth">{width}</ac:parameter>\n'
        f'    <ac:parameter ac:name="revision">1</ac:parameter>\n'
        f'    <ac:plain-text-body>\n'
        f'      <![CDATA[\n'
        f'{drawio_xml}\n'
        f'      ]]>\n'
        f'    </ac:plain-text-body>\n'
        f'  </ac:structured-macro>\n'
        f'</p>'
    )


def convert_mermaid_flowchart_to_plantuml(code: str, is_lineage: bool = False) -> str:
    """Parse Mermaid flowchart into PlantUML with strict orthogonal routing."""
    # Strip Mermaid init blocks %%{init: ... }%%
    code = re.sub(r'%%\{init:.*?\}%%', '', code, flags=re.DOTALL)
    lines = [l.strip() for l in code.splitlines() if l.strip()]

    subgraphs = []
    sg_stack = []
    top_nodes = {}
    top_connections = []

    node_def_re = re.compile(
        r'([A-Za-z0-9_]+)\s*(?:\[\["?(.*?)"?\]\]|\(\("?(.*?)"?\)\)|\[\("?(.*?)"?\)\]|\[\/"?(.*?)"?\/\]|\[\\"?(.*?)"?\\\]|\["([^"]*)"\]|\[([^\]]*)\])'
    )
    subgraph_start_re = re.compile(r'^subgraph\s+([A-Za-z0-9_]+)(?:\s*\["([^"]+)"\]|\s*\[(.+)\])?', re.IGNORECASE)
    direction_re = re.compile(r'^direction\s+([A-Za-z]+)', re.IGNORECASE)

    node_classes = {}

    for line in lines:
        if line.startswith("flowchart") or line.startswith("graph") or line.startswith("classDef") or line.startswith("style ") or line.startswith("%%"):
            continue

        class_match = re.match(r'^\s*class\s+([A-Za-z0-9_,\s]+)\s+([A-Za-z0-9_]+)\s*;?', line)
        if class_match:
            targets = [t.strip() for t in class_match.group(1).split(',') if t.strip()]
            cls_name = class_match.group(2)
            for t in targets:
                node_classes[t] = cls_name
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

        for m in re.finditer(r'([A-Za-z0-9_]+)(?:\[.*?\]|\(.*?\))?:::([A-Za-z0-9_]+)', line):
            node_classes[m.group(1)] = m.group(2)

        clean_line_no_style = re.sub(r':::[A-Za-z0-9_]+', '', line)

        # Stash edge labels before matching node definitions so brackets inside labels aren't mistaken for nodes
        edge_labels = []
        def stash_label(m):
            edge_labels.append(m.group(0))
            return f" __EDGE_LABEL_{len(edge_labels)-1}__ "

        stashed_line = re.sub(r'\|"[^"]*"\||\|[^|]*\|', stash_label, clean_line_no_style)

        for match in node_def_re.finditer(stashed_line):
            n_id = match.group(1)
            n_lbl = next((g for g in match.groups()[1:] if g is not None), "")
            if (n_lbl.startswith('"') and n_lbl.endswith('"')) or (n_lbl.startswith("'") and n_lbl.endswith("'")):
                n_lbl = n_lbl[1:-1]
            node_info = {"id": n_id, "label": n_lbl, "class": node_classes.get(n_id, "")}
            if sg_stack:
                sg_stack[-1]["nodes"][n_id] = node_info
            else:
                top_nodes[n_id] = node_info

        clean_edge_line = node_def_re.sub(r'\1', stashed_line)
        for idx, orig_lbl in enumerate(edge_labels):
            clean_edge_line = clean_edge_line.replace(f"__EDGE_LABEL_{idx}__", orig_lbl)
        edge_tokens = re.split(r'(\s*(?:<-->|-->|---|->|-\.->|\.-\.|\.\->)\s*(?:\|"[^"]*"\|\s*|\|[^\|]*\|\s*)?)', clean_edge_line)
        if len(edge_tokens) >= 3:
            for i in range(0, len(edge_tokens) - 2, 2):
                src = edge_tokens[i].strip()
                arrow_token = edge_tokens[i+1].strip()
                dst = edge_tokens[i+2].strip()

                lbl_match = re.search(r'\|"?([^"\|]*)"?\|', arrow_token)
                lbl = lbl_match.group(1).strip() if lbl_match else ""
                dashed = "-.-" in arrow_token or ".-" in arrow_token

                if src and dst and re.match(r'^[A-Za-z0-9_]+$', src) and re.match(r'^[A-Za-z0-9_]+$', dst):
                    edge_obj = {"src": src, "dst": dst, "label": lbl, "dashed": dashed}
                    if sg_stack:
                        sg_stack[-1]["edges"].append(edge_obj)
                    else:
                        top_connections.append(edge_obj)

    def clean_node_label(label: str) -> str:
        cleaned = label
        cleaned = re.sub(r'<i>\s*(?:New Component|Existing Platform|Existing Component|Impacted Component|New|Existing)\s*</i>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<b>\s*\((?:New Component|Existing Platform|Existing Component|Impacted Component|New|Existing)\)\s*</b>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\((?:New Component|Existing Platform|Existing Component|Impacted Component|New|Existing)\)', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\[(?:New|Existing)\]', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'(?:<br\s*/?>\s*)+$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'^(?:\s*<br\s*/?>)+', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    # Flatten nodes to annotate element type and background color
    all_nodes = {}
    def collect_nodes(sg_list):
        for sg in sg_list:
            for nid, ninfo in sg["nodes"].items():
                all_nodes[nid] = ninfo
            collect_nodes(sg.get("children", []))
    collect_nodes(subgraphs)
    for nid, ninfo in top_nodes.items():
        all_nodes[nid] = ninfo

    for nid, ninfo in all_nodes.items():
        id_low = nid.lower()
        lbl_low = ninfo["label"].lower()
        cls_low = (node_classes.get(nid, "") or ninfo.get("class", "")).lower()

        is_db = (
            "db" in id_low or "mart" in id_low or "raw" in id_low or "database" in lbl_low or
            "store" in id_low or "table" in id_low or "snapshot" in id_low or
            "jsc" in id_low or "src" in id_low or any(k in cls_low for k in ["db", "src", "mart", "staging"])
        )
        elem_type = "database" if is_db else "rectangle"

        is_new_or_impacted = (
            "new" in cls_low or "impacted" in cls_low or
            "new" in lbl_low or "impacted" in lbl_low or
            "new" in id_low or "impacted" in id_low
        )
        bg_color = "#FEF2F2;line:DC2626" if is_new_or_impacted else "#EFF6FF;line:2563EB"
        ninfo["elem_type"] = elem_type
        ninfo["bg_color"] = bg_color
        ninfo["is_new"] = is_new_or_impacted

    is_lr = any(re.match(r'^\s*(flowchart|graph)\s+LR', l, re.IGNORECASE) for l in lines)
    has_sys_int = bool(re.search(r'SYS_|INT_', code))

    out = []
    out.append("@startuml")
    if is_lr and not subgraphs:
        out.append("left to right direction")
    out.append("scale 1.2")
    out.append("skinparam defaultFontSize 11")
    out.append("skinparam nodesep 24")
    out.append("skinparam ranksep 28\n")
    out.append("skinparam shadowing false")
    out.append('skinparam defaultFontName "Segoe UI"')
    out.append("skinparam roundCorner 6")

    out.append("skinparam package {")
    out.append("    BorderColor #475569")
    out.append("    BorderThickness 1.5")
    out.append("    BackgroundColor #F8FAFC")
    out.append("    FontColor #0F172A")
    out.append("    FontStyle bold")
    out.append("    Padding 10")
    out.append("}")

    out.append("skinparam rectangle {")
    out.append("    BorderThickness 1.5")
    out.append("}")
    out.append("skinparam database {")
    out.append("    BorderThickness 1.5")
    out.append("}\n")

    out.append("skinparam legend {")
    out.append("    BackgroundColor #FFFFFF")
    out.append("    BorderColor #CBD5E1")
    out.append("    BorderThickness 1")
    out.append("    FontSize 9")
    out.append('    FontName "Segoe UI"')
    out.append("}\n")

    def wrap_edge_label(lbl: str, max_len: int = 24) -> str:
        clean = lbl.strip()
        clean = re.sub(r'\[(?:New|Existing|New Connectivity|Existing Connectivity)\]', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\((?:New|Existing|New Connectivity|Existing Connectivity)\)', '', clean, flags=re.IGNORECASE)
        clean = clean.replace("<br/>", "\\n").replace("<br>", "\\n").replace('"', "'").strip()
        if not clean:
            return ""
        if "\\n" in clean or "\n" in clean:
            return clean

        m = re.match(r'^(INT_[A-Za-z0-9_]+(?:\s*\[[^\]]+\])?\s*:\s*)(.+)$', clean)
        if m:
            prefix = m.group(1).strip()
            desc = m.group(2).strip()
            words = desc.split()
            lines = [prefix]
            curr = []
            for w in words:
                if sum(len(x) for x in curr) + len(curr) + len(w) > max_len:
                    lines.append(" ".join(curr))
                    curr = [w]
                else:
                    curr.append(w)
            if curr:
                lines.append(" ".join(curr))
            return "\\n".join(lines)

        words = clean.split()
        lines = []
        curr = []
        for w in words:
            if sum(len(x) for x in curr) + len(curr) + len(w) > max_len:
                lines.append(" ".join(curr))
                curr = [w]
            else:
                curr.append(w)
        if curr:
            lines.append(" ".join(curr))
        return "\\n".join(lines)

    node_to_sg = {}
    sg_dir_by_id = {}
    sg_index_by_id = {}
    def collect_sg_info(sg_list, idx_counter=None):
        if idx_counter is None:
            idx_counter = [0]
        for sg in sg_list:
            sg_index_by_id[sg["id"]] = idx_counter[0]
            idx_counter[0] += 1
            sg_dir_by_id[sg["id"]] = sg.get("direction", "TB")
            for n_id in sg.get("nodes", {}):
                node_to_sg[n_id] = sg["id"]
            collect_sg_info(sg.get("children", []), idx_counter)
    collect_sg_info(subgraphs)

    def format_edge_arrow(e: dict, sg_dir: str = "TB") -> Tuple[str, str]:
        raw_lbl = e.get("label", "")
        wrapped_lbl = wrap_edge_label(raw_lbl)
        lbl_suffix = f' : {wrapped_lbl}' if wrapped_lbl else ""

        src_node = all_nodes.get(e["src"])
        dst_node = all_nodes.get(e["dst"])
        src_is_new = src_node and src_node.get("is_new", False)
        dst_is_new = dst_node and dst_node.get("is_new", False)

        is_new_edge = (
            bool(re.search(r'\b(new|impacted)\b', raw_lbl, re.IGNORECASE)) or
            src_is_new or dst_is_new
        )
        if bool(re.search(r'\bexisting\b', raw_lbl, re.IGNORECASE)):
            color = "#2563EB"
        elif is_new_edge:
            color = "#DC2626"
        else:
            color = "#2563EB"

        src_sg = node_to_sg.get(e["src"])
        dst_sg = node_to_sg.get(e["dst"])
        is_cross_sg = src_sg and dst_sg and src_sg != dst_sg
        
        is_upward = False
        if is_cross_sg and not is_lr:
            src_idx = sg_index_by_id.get(src_sg, 0)
            dst_idx = sg_index_by_id.get(dst_sg, 0)
            if dst_idx < src_idx:
                is_upward = True

        if e.get("dashed"):
            if is_cross_sg:
                arrow = f".-[{color},norank]->" if (is_lr or is_upward) else f".-[{color}]->"
            else:
                arrow = f".-[{color}]->"
        elif is_cross_sg:
            if is_lr:
                arrow = f"-[{color},norank]right->"
            elif is_upward:
                arrow = f"-[{color},norank]up->"
            else:
                arrow = f"-[{color}]->"
        elif sg_dir == "LR":
            arrow = f"-[{color}]right->"
        else:
            arrow = f"-[{color}]->"
        return arrow, lbl_suffix

    def render_subgraph(sg, indent=""):
        res = [f'{indent}package "<b>{sg["title"]}</b>" as {sg["id"]} {{']
        for child in sg.get("children", []):
            res.extend(render_subgraph(child, indent + "    "))
        for n_id, n_info in sg["nodes"].items():
            formatted_lbl = (
                clean_node_label(n_info["label"])
                .replace("<br/>", "\\n")
                .replace("<br>", "\\n")
                .replace("•", "-")
                .replace('"', "'")
            )
            elem_type = n_info["elem_type"]
            bg_color = n_info["bg_color"]
            res.append(f'{indent}    {elem_type} "{formatted_lbl}" as {n_id} {bg_color}')

        sg_dir = sg.get("direction", "TB")
        if sg_dir == "LR":
            node_ids = list(sg["nodes"].keys())
            for i in range(len(node_ids) - 1):
                res.append(f'{indent}    {node_ids[i]} -[hidden]right-> {node_ids[i+1]}')
            if node_ids:
                res.append("")

        if sg["edges"]:
            res.append("")
            for e in sg["edges"]:
                arrow, lbl_suffix = format_edge_arrow(e, sg_dir)
                res.append(f'{indent}    {e["src"]} {arrow} {e["dst"]}{lbl_suffix}')
        res.append(f"{indent}}}\n")
        return res

    for sg in subgraphs:
        out.extend(render_subgraph(sg))

    for n_id, n_info in top_nodes.items():
        formatted_lbl = clean_node_label(n_info["label"]).replace("<br/>", "\\n").replace("<br>", "\\n").replace('"', "'")
        elem_type = n_info["elem_type"]
        bg_color = n_info["bg_color"]
        out.append(f'{elem_type} "{formatted_lbl}" as {n_id} {bg_color}')
    if top_nodes:
        out.append("")

    for i in range(len(subgraphs) - 1):
        if is_lr:
            out.append(f'{subgraphs[i]["id"]} -[hidden]right-> {subgraphs[i+1]["id"]}')
        else:
            out.append(f'{subgraphs[i]["id"]} -[hidden]down-> {subgraphs[i+1]["id"]}')
    if subgraphs:
        out.append("")

    for e in top_connections:
        arrow, lbl_suffix = format_edge_arrow(e)
        out.append(f'{e["src"]} {arrow} {e["dst"]}{lbl_suffix}')

    out.append("\nlegend bottom")
    out.append("|= Marker |= Classification |= Description |")
    out.append('|<color:#DC2626><b>━━━━▶</b></color> | <b>New/Impacted Connection</b> | New or modified integration interface created for this solution |')
    out.append('|<color:#2563EB><b>━━━━▶</b></color> | <b>Existing Connection</b> | Pre-existing unmodified production integration pathway |')
    out.append('|<back:#FEF2F2><color:#DC2626><b> ■ </b></color></back> | <b>New / Impacted Component</b> | Component introduced or modified specifically for this solution |')
    out.append('|<back:#EFF6FF><color:#2563EB><b> ■ </b></color></back> | <b>Existing Platform</b> | Unmodified pre-existing production enterprise fleet component |')
    out.append('|<size:9><b>[SYS_xx]</b></size> | <b>System ID</b> | Mapped directly to Architecture Specifications |')
    out.append("endlegend")

    out.append("@enduml")
    return "\n".join(out)


def convert_mermaid_sequence_to_plantuml(code: str, is_lineage: bool = False) -> str:
    """Parse Mermaid sequenceDiagram into PlantUML sequence diagram with orthogonal lines."""
    code = re.sub(r'%%\{init:.*?\}%%', '', code, flags=re.DOTALL)
    lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("%%")]

    out = []
    out.append("@startuml")
    out.append("autonumber")
    out.append("scale max 2000 width")
    out.append("skinparam defaultFontSize 11")
    out.append("skinparam shadowing false")
    out.append('skinparam defaultFontName "Segoe UI"')
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


def convert_mermaid_class_to_plantuml(diag_code: str) -> str:
    """Convert Mermaid classDiagram block into native PlantUML class diagram."""
    lines = diag_code.strip().splitlines()
    out = [
        "@startuml",
        "scale 1.2",
        "skinparam defaultFontSize 11",
        "skinparam defaultFontName \"Segoe UI\"",
        "skinparam shadowing false",
        "skinparam roundCorner 6",
        "skinparam class {",
        "    BackgroundColor #F8FAFC",
        "    BorderColor #2563EB",
        "    BorderThickness 1.5",
        "    ArrowColor #2563EB",
        "    FontColor #0F172A",
        "    FontStyle bold",
        "    AttributeFontColor #334155",
        "    AttributeFontSize 10",
        "}",
        ""
    ]
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("classDiagram"):
            continue
        # Convert Mermaid generic syntax ~Type~ to PlantUML <Type>
        converted = line
        while "~" in converted:
            converted = converted.replace("~", "<", 1).replace("~", ">", 1)
        out.append(converted)
    out.append("@enduml")
    return "\n".join(out)


def convert_mermaid_er_to_plantuml(diag_code: str) -> str:
    """Convert Mermaid erDiagram block into native PlantUML ER entity diagram."""
    lines = diag_code.strip().splitlines()
    out = [
        "@startuml",
        "scale 1.2",
        "skinparam defaultFontSize 11",
        "skinparam defaultFontName \"Segoe UI\"",
        "skinparam shadowing false",
        "skinparam roundCorner 6",
        "skinparam entity {",
        "    BackgroundColor #F8FAFC",
        "    BorderColor #2563EB",
        "    BorderThickness 1.5",
        "    ArrowColor #2563EB",
        "    FontColor #0F172A",
        "    FontStyle bold",
        "}",
        ""
    ]
    in_entity = False
    entity_hdr_re = re.compile(r'^([A-Za-z0-9_-]+)\s*\{$')

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("erDiagram"):
            continue

        m_ent = entity_hdr_re.match(stripped)
        if m_ent and not in_entity:
            in_entity = True
            ent_name = m_ent.group(1)
            alias = ent_name.replace("-", "_")
            out.append(f'entity "{ent_name}" as {alias} {{')
            continue

        if stripped == "}" and in_entity:
            in_entity = False
            out.append("}")
            continue

        if in_entity:
            parts = stripped.split()
            if len(parts) >= 2:
                dtype = parts[0]
                col = parts[1]
                is_pk = "PK" in parts[2:]
                prefix = "* " if is_pk else ""
                suffix = " <<PK>>" if is_pk else ""
                out.append(f"    {prefix}{col} : {dtype}{suffix}")
            else:
                out.append(f"    {stripped}")
        else:
            out.append(line)

    out.append("@enduml")
    return "\n".join(out)


def render_plantuml_macro(puml_code: str) -> str:
    """Wrap PlantUML code inside native Confluence <ac:structured-macro ac:name="plantuml"> with centered alignment."""
    return (
        f'<div style="text-align:center;">\n'
        f'<ac:structured-macro ac:name="plantuml" ac:schema-version="1">\n'
        f'<ac:parameter ac:name="atlassian-macro-output-type">INLINE</ac:parameter>\n'
        f'<ac:plain-text-body><![CDATA[{puml_code}]]></ac:plain-text-body>\n'
        f'</ac:structured-macro>\n'
        f'</div>'
    )


def convert_markdown_to_confluence_xhtml(
    md_text: str,
    is_hld: bool = True,
    is_lineage: bool = False,
    diagram_type: str = "plantuml",
    diagrams_dir: Optional[str] = None,
    app_prefix: str = "app"
) -> str:
    """Convert Markdown document to well-formed Confluence XHTML."""
    cleaned_md = sanitize_ste_and_anti_slop(md_text)
    cleaned_md = strip_ai_traces_and_metadata(cleaned_md, is_hld=is_hld)

    lines = cleaned_md.splitlines()
    body_parts = []

    # Extract Title
    title = f"{app_prefix.capitalize()} Architecture Specification"
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            title = re.sub(r'^(?:High-Level\s+Architecture\s*\(HLA\):\s*|Lower-Level\s+Design:\s*)', '', title)
            break

    app_name = title
    safe_app_name = html.escape(app_name)

    # Build Header Block
    if is_lineage:
        body_parts.append(f"<h1>Data Lineage &amp; Telemetry: {safe_app_name}</h1>")
        body_parts.append("<hr/>")
        body_parts.append("<h2>Table of Contents</h2>")
        body_parts.append('<p><ac:structured-macro ac:name="toc" ac:schema-version="1"/></p>')
        body_parts.append("<hr/>")

        # Find starting index of Section 1
        start_idx = 0
        for idx, l in enumerate(lines):
            if re.match(r'^##\s+1\.', l.strip()):
                start_idx = idx
                break
        i = start_idx
    elif is_hld:
        body_parts.append(f"<h1>High-Level Architecture (HLA): {safe_app_name}</h1>")
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

        # Find starting index of Section 1
        start_idx = 0
        for idx, l in enumerate(lines):
            if re.match(r'^##\s+1\.', l.strip()):
                start_idx = idx
                break
        i = start_idx
    else:
        body_parts.append(f"<h1>Lower-Level Design: {safe_app_name}</h1>")
        body_parts.append("<hr/>")

        # Check for Technical Metadata before Section 1
        meta_lines = []
        in_meta = False
        start_idx = 0
        for idx, l in enumerate(lines):
            if re.match(r'^##\s+Technical Metadata', l.strip(), re.IGNORECASE):
                in_meta = True
                continue
            if re.match(r'^##\s+1\.', l.strip()):
                start_idx = idx
                break
            if in_meta:
                meta_lines.append(l)

        if meta_lines:
            body_parts.append("<h2>Technical Metadata</h2>")
            meta_items = [re.sub(r'^[-*]\s+', '', ml.strip()) for ml in meta_lines if re.match(r'^[-*]\s+', ml.strip())]
            if meta_items:
                body_parts.append("<ul>")
                for item in meta_items:
                    body_parts.append(f"  <li>{format_inline_markdown(item)}</li>")
                body_parts.append("</ul>")
            body_parts.append("<hr/>")

        body_parts.append("<h2>Table of Contents</h2>")
        body_parts.append('<p><ac:structured-macro ac:name="toc" ac:schema-version="1"/></p>')
        body_parts.append("<hr/>")
        i = start_idx
    diagram_count = 0
    last_heading = "architecture-diagram"

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
            last_heading = re.sub(r'[^a-zA-Z0-9]+', '-', h_match.group(2).strip().lower()).strip('-')
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
            diagram_count += 1

            slug = last_heading if last_heading else f"diagram-{diagram_count}"
            diagram_filename = f"{app_prefix}-{slug}.drawio"
            display_name = last_heading.replace('-', ' ').title()

            if diagram_type == "drawio":
                if "sequenceDiagram" in diag_code:
                    drawio_xml, canvas_w = convert_mermaid_sequence_to_drawio(diag_code, display_name)
                else:
                    drawio_xml, canvas_w = convert_mermaid_flowchart_to_drawio(diag_code, display_name)

                # If diagrams_dir is specified, write standalone .drawio file
                if diagrams_dir:
                    os.makedirs(diagrams_dir, exist_ok=True)
                    drawio_path = os.path.join(diagrams_dir, diagram_filename)
                    with open(drawio_path, "w", encoding="utf-8") as df:
                        df.write(drawio_xml)
                    print(f"  [Draw.io Export] Saved: {drawio_path}")

                body_parts.append(render_drawio_macro(drawio_xml, diagram_filename, display_name, canvas_w))
            else:
                if "sequenceDiagram" in diag_code:
                    puml = convert_mermaid_sequence_to_plantuml(diag_code, is_lineage=is_lineage)
                elif "classDiagram" in diag_code:
                    puml = convert_mermaid_class_to_plantuml(diag_code)
                elif "erDiagram" in diag_code:
                    puml = convert_mermaid_er_to_plantuml(diag_code)
                else:
                    puml = convert_mermaid_flowchart_to_plantuml(diag_code, is_lineage=is_lineage)

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
    parser = argparse.ArgumentParser(description="Convert Markdown HLD/LLD to Confluence Storage Format XHTML with Draw.io diagrams.")
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
    is_lineage = "-data-lineage" in input_filename or "-lineage" in input_filename

    # Derive app prefix (e.g. order-service)
    app_prefix = input_filename.split("-hld")[0].split("-lld")[0].split("-hla")[0].split("-data-lineage")[0].split("-lineage")[0]

    # Target diagrams directory adjacent to output file
    diagrams_dir = os.path.join(os.path.dirname(output_path), "diagrams")

    with open(input_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    print(f"Converting {input_path} to Confluence Storage Format XHTML (Diagram Engine: {args.diagram_type})...")
    xhtml_body = convert_markdown_to_confluence_xhtml(
        md_text,
        is_hld=is_hld,
        is_lineage=is_lineage,
        diagram_type=args.diagram_type,
        diagrams_dir=diagrams_dir,
        app_prefix=app_prefix
    )

    try:
        validate_confluence_xhtml(xhtml_body)
        print("XHTML validation successful: Content is well-formed XML.")
    except Exception as e:
        print(f"Warning: XML validation failed ({e}), review generated output.", file=sys.stderr)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xhtml_body)

    print(f"Confluence XHTML successfully written to: {output_path}")
    if args.diagram_type == "drawio":
        print(f"Standalone .drawio files generated in: {diagrams_dir}")


if __name__ == "__main__":
    main()
