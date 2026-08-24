import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// div:ide portal/app bundle config.
// `build.outDir` is the directory FastAPI's StaticFiles mount will
// serve. The container COPY moves services/portal/app/build to
// /portal/app/build inside the API image, and main.py mounts the
// whole services/portal tree at /portal/. The page is served at
// /portal/app/ (root of this build dir), assets at /portal/app/assets/.
//
// `base: '/portal/app/'` makes Vite emit relative-style absolute
// paths (`/portal/app/assets/index-XXXX.js`) so the bundle resolves
// correctly when served from a sub-path.
export default defineConfig({
  base: "/portal/app/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: path.resolve(__dirname, "./build"),
    emptyOutDir: true,
    sourcemap: true,
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      // Forward API calls to the running uvicorn during dev so the
      // portal can `fetch("/api/v1/...")` without CORS plumbing.
      "/api": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
    },
  },
});
