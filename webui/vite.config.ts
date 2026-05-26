import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.NANOBOT_API_URL ?? "http://127.0.0.1:8765";
  const wsTarget = target.replace(/^http/, "ws");
  const hmrPath = "/__nanobot_vite_hmr";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    optimizeDeps: {
      // Radix dialog was introduced mid-session for the mobile sidebar sheet.
      // When Vite re-optimizes it on a running dev server, the browser can race
      // and request stale chunk paths from `.vite/deps`. Excluding it keeps dev
      // reloads stable instead of rewriting those chunk filenames under us.
      exclude: ["@radix-ui/react-dialog"],
    },
    build: {
      outDir: path.resolve(__dirname, "../nanobot/web/dist"),
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes("node_modules/refractor/lang/")) {
              return;
            }
            if (
              id.includes("node_modules/react-syntax-highlighter")
              || id.includes("node_modules/refractor/core")
            ) {
              return "syntax-highlight";
            }
            if (
              id.includes("node_modules/react-markdown")
              || id.includes("node_modules/remark-")
              || id.includes("node_modules/rehype-")
              || id.includes("node_modules/unified")
              || id.includes("node_modules/mdast-")
              || id.includes("node_modules/hast-")
              || id.includes("node_modules/micromark")
              || id.includes("node_modules/unist-")
            ) {
              return "markdown-vendor";
            }
            if (id.includes("node_modules/katex")) {
              return "katex";
            }
          },
        },
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      // Keep Vite's HMR socket on a dedicated path so it doesn't collide with
      // the ``/`` proxy below (Vite HMR and the nanobot ws upgrade otherwise
      // both sit on the root path).
      hmr: {
        host: "127.0.0.1",
        path: hmrPath,
      },
      proxy: {
        "/webui": { target, changeOrigin: true },
        "/api": { target, changeOrigin: true },
        "/auth": { target, changeOrigin: true },
        // Forward only WebSocket upgrades on ``/`` to the nanobot gateway;
        // plain HTTP GETs on ``/`` must stay with Vite so it can serve the SPA.
        // ``bypass`` returning the original URL skips the proxy for that
        // request; returning undefined lets the proxy (and ws upgrade handler)
        // take it.
        "/": {
          target: wsTarget,
          ws: true,
          changeOrigin: true,
          bypass: (req) => {
            if (req.url?.startsWith(hmrPath)) {
              return req.url;
            }
            return req.headers.upgrade === "websocket" ? undefined : req.url;
          },
        },
      },
    },
    test: {
      environment: "happy-dom",
      globals: true,
      setupFiles: ["./src/tests/setup.ts"],
    },
  };
});
