// Build-time switches for the tropical page (design.md 7.7, 11f F1).
// VITE_TROPICAL_MODEL_LAYERS=off removes the numerical-model layers: no model section, no
// request under data/tropical/models/, no NOAA/ECMWF attribution lines. Anything else (or unset)
// keeps them; each model layer still starts switched off. To disable them on the live site
// without touching the publishing workflow, change the default below and commit.
export const MODEL_LAYERS_ENABLED = import.meta.env.VITE_TROPICAL_MODEL_LAYERS !== "off";
