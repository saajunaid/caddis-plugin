/** Keep malformed auto models intact so validation reports their actual errors. */
export function prepareModel(input, autoLayout) {
  return input?.layout === "auto" && Array.isArray(input.nodes) && Array.isArray(input.links)
    && Array.isArray(input.columns) && Array.isArray(input.lanes) ? autoLayout(input) : input;
}
