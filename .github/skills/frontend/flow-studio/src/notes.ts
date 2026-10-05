// Implementation notes (a left drawer with numbered markers on the page) and the model reference
// section with Copy as Markdown and Copy JSON. The notes are for the person or agent who builds the page.

import { el, on, type Ctx } from "./ctx.ts";
import { esc } from "./model.ts";

export function install(ctx: Ctx): void {
  const { els, model } = ctx;
  const notes = ctx.notes.map((n, i) => ({ id: i + 1, ...n }));

  const card = (id: number) => els.notelist.querySelector<HTMLElement>(`[data-n="${id}"]`);
  const anchorOf = (sel: string): Element | null => { try { return document.querySelector(sel); } catch { return null; } };

  function clearMarkers(): void {
    document.querySelectorAll(".marker").forEach(m => m.remove());
    document.querySelectorAll(".anchored").forEach(a => a.classList.remove("anchored"));
  }

  function placeMarkers(): void {
    clearMarkers();
    for (const n of notes) {
      const a = anchorOf(n.anchor);
      if (!a) continue;
      let r = a.getBoundingClientRect();
      if (!r.width && !r.height) continue;
      if (a.id === "inspector" && !a.classList.contains("open")) {
        const vr = els.vp.getBoundingClientRect();
        r = { left: vr.right - 130, top: vr.top + 56, right: vr.right - 128, bottom: vr.top + 58, width: 2, height: 2, x: 0, y: 0, toJSON: () => ({}) };
      }
      const v = els.vp.getBoundingClientRect();
      if (a.closest("#world") && (r.right < v.left || r.left > v.right || r.bottom < v.top || r.top > v.bottom)) continue;
      const m = el("button", "marker", String(n.id));
      m.type = "button"; m.dataset.n = String(n.id); m.title = n.title;
      m.setAttribute("aria-label", `Note ${n.id}: ${n.title}`);
      m.style.left = r.left + scrollX - 10 + "px";
      m.style.top = r.top + scrollY - 10 + "px";
      m.addEventListener("mouseenter", () => { a.classList.add("anchored"); card(n.id)?.classList.add("on"); });
      m.addEventListener("mouseleave", () => { a.classList.remove("anchored"); card(n.id)?.classList.remove("on"); });
      m.addEventListener("click", () => card(n.id)?.scrollIntoView({ block: "center", behavior: ctx.reduced ? "auto" : "smooth" }));
      document.body.appendChild(m);
    }
  }

  function toggleNotes(next?: boolean): void {
    const on_ = next === undefined ? !document.body.classList.contains("notes") : next;
    document.body.classList.toggle("notes", on_);
    els.notesBtn.setAttribute("aria-pressed", String(on_));
    if (on_) window.setTimeout(placeMarkers, ctx.reduced ? 30 : 340);
    else clearMarkers();
  }

  els.notelist.innerHTML = notes.map(n => `<div class="ncard" data-n="${n.id}"><b><span>${n.id}</span>${esc(n.title)}</b>${esc(n.text)}</div>`).join("")
    || '<p class="note">This page has no implementation notes.</p>';
  els.notelist.querySelectorAll<HTMLElement>(".ncard").forEach(c => {
    c.addEventListener("mouseenter", () => { const n = notes.find(x => String(x.id) === c.dataset.n); const a = n && anchorOf(n.anchor); if (a) a.classList.add("anchored"); });
    c.addEventListener("mouseleave", () => document.querySelectorAll(".anchored").forEach(a => a.classList.remove("anchored")));
  });
  on(ctx, els.notesBtn, "click", () => toggleNotes());
  on(ctx, window, "scroll", () => { if (document.body.classList.contains("notes")) placeMarkers(); }, { passive: true });

  // ---- model reference
  const markdown = (): string => {
    const out = [`# ${model.meta.title}`, "", model.meta.help, "", `As of ${model.meta.asOf}. Source: ${model.meta.source}`, "", "## States"];
    for (const [id, s] of Object.entries(model.states)) out.push(`- **${s.word}** (${id}): tone ${s.tone}, border ${s.border}, link ${s.edge}, motion ${s.motion}, bucket ${s.bucket}`);
    out.push("", "## Columns", ...model.columns.map((c, i) => `${i + 1}. ${c.title}${c.phase ? ` (${c.phase})` : ""}`));
    out.push("", "## Lanes", ...model.lanes.map(l => `- ${l.title}${l.badge ? ` [${l.badge}]` : ""}${l.note ? `: ${l.note}` : ""}`));
    out.push("", `## Size`, `${model.nodes.length} nodes, ${model.links.length} links.`);
    if (notes.length) out.push("", "## Notes", ...notes.map(n => `${n.id}. **${n.title}**: ${n.text}`));
    return out.join("\n");
  };
  const rows = (items: string[]) => `<ul>${items.map(i => `<li>${i}</li>`).join("")}</ul>`;
  els.specbody.innerHTML = `<div class="specbtns"><button type="button" id="cpMd">Copy as Markdown</button><button type="button" id="cpJson">Copy model JSON</button><span class="note" id="cpMsg" style="margin:0"></span></div>
    <h3>States</h3>${rows(Object.entries(model.states).map(([id, s]) => `<b>${esc(s.word)}</b> (<code>${esc(id)}</code>): tone ${esc(s.tone)}, border ${esc(s.border)}, link ${esc(s.edge)}, motion ${esc(s.motion)}, bucket ${esc(s.bucket)}`))}
    <h3>Columns</h3>${rows(model.columns.map(c => `${esc(c.title)}${c.phase ? ` (${esc(c.phase)})` : ""}`))}
    <h3>Lanes</h3>${rows(model.lanes.map(l => `${esc(l.title)}${l.badge ? ` [${esc(l.badge)}]` : ""}${l.note ? `: ${esc(l.note)}` : ""}`))}
    <h3>Size</h3><p>${model.nodes.length} nodes, ${model.links.length} links.</p>`;
  const msg = (t: string) => { const m = document.getElementById("cpMsg"); if (m) m.textContent = t; };
  const copy = async (text: string, what: string) => {
    try { await navigator.clipboard.writeText(text); msg(`${what} copied.`); }
    catch {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); msg(`${what} copied.`); } catch { msg("Copy is blocked here: select the text instead."); }
      ta.remove();
    }
  };
  document.getElementById("cpMd")?.addEventListener("click", () => void copy(markdown(), "Markdown"));
  document.getElementById("cpJson")?.addEventListener("click", () => void copy(JSON.stringify(model, null, 2), "JSON"));

  ctx.fn.toggleNotes = toggleNotes;
  ctx.fn.placeMarkers = placeMarkers;
}
