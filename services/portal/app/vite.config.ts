import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// div:ide portal bundle config.
// `build.outDir` is the directory FastAPI's StaticFiles mount will
// serve. The container COPY moves services/portal/app/build to
// /app/portal/build inside the API image, and main.py mounts the
// build dir at / (root). The page is served at /, assets at /assets/.
//
// `base: '/'` makes Vite emit root-relative paths
// (`/assets/index-XXXX.js`) so the bundle resolves correctly when
// served from the root.
export default defineConfig({
  base: "/",
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
