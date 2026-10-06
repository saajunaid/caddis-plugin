// Which default demo-pack notes survive for one model and one built shell. Shared by build.mjs
// and its tests. Only default notes are filtered here: notes from the model and from --notes are
// appended unfiltered (at runtime a note whose selector matches nothing simply gets no marker).

// An exact attribute match, not a pattern: an id with regex metacharacters must never match a
// different id, and a data-id="..." substring must not count as an id.
const hasId = (shell, id) => shell.includes(` id="${id}"`) || shell.includes(` id='${id}'`);

export function keepDefaultNotes(defaults, model, shell) {
  return defaults.filter(n => {
    if (n.anchor === "#playbar" && (!Array.isArray(model.scenarios) || model.scenarios.length === 0)) {
      return false;
    }
    if (n.anchor === "#modeSwitch" && (!Array.isArray(model.views) || model.views.length < 2)) {
      return false;
    }
    if (typeof n.anchor === "string" && n.anchor.startsWith("#")) {
      const id = n.anchor.slice(1);
      if (!hasId(shell, id)) return false;
    }
    return true;
  });
}
