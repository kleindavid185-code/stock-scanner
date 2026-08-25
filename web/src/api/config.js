// VITE_API_URL is read from the build environment (Vite exposes anything
// prefixed VITE_ via import.meta.env). Falls back to localhost for local
// dev, matching how the backend runs on this same machine by default --
// override it in production (e.g. Render's dashboard) to point at the
// deployed backend's URL.
export const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:4000";
