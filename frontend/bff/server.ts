import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";

/**
 * AI Sandbox - Backend For Frontend (BFF) Proxy
 * 
 * Enforces server-side security boundaries:
 * 1. Keeps SANDBOX_API_KEY on the server; never exposed to browser.
 * 2. Injects X-API-Key header to FastAPI backend requests when configured.
 * 3. Enforces an explicit route and method allowlist (anti-open-proxy).
 * 4. Supports long-running synchronous agent executions with configurable timeout (default 300s).
 * 5. Production-ready standalone HTTP server serving frontend production assets and proxying API calls.
 */

const FASTAPI_TARGET =
  process.env.SANDBOX_BACKEND_URL ||
  process.env.FASTAPI_URL ||
  "http://127.0.0.1:8000";

// Server-side only: never prefixed with VITE_ or NEXT_PUBLIC_
const SERVER_API_KEY =
  process.env.SANDBOX_API_KEY ||
  process.env.API_KEY ||
  "";

// Route allowlist rule definition
interface RouteRule {
  pattern: RegExp;
  methods: string[];
  description: string;
}

const ALLOWED_ROUTES: RouteRule[] = [
  // Health probes
  { pattern: /^\/health$/, methods: ["GET"], description: "Liveness probe" },
  { pattern: /^\/ready$/, methods: ["GET"], description: "Readiness probe" },

  // Sandboxes list & create
  { pattern: /^\/api\/v1\/sandboxes$/, methods: ["GET", "POST"], description: "List or create sandboxes" },

  // Ephemeral execution (backward compatibility)
  { pattern: /^\/api\/v1\/sandboxes\/execute$/, methods: ["POST"], description: "Ephemeral execution" },

  // Sandbox detail & delete
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+$/, methods: ["GET", "DELETE"], description: "Get or destroy sandbox" },

  // Sandbox code execution
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/execute$/, methods: ["POST"], description: "Execute code in sandbox" },

  // Sandbox execution history & specific execution detail
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/executions$/, methods: ["GET"], description: "List sandbox executions" },
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/executions\/[a-zA-Z0-9_-]+$/, methods: ["GET"], description: "Get execution detail" },

  // Workspace files (list, create/write, delete by query)
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/files$/, methods: ["GET", "POST", "DELETE"], description: "Manage workspace files root" },

  // Workspace file read and delete by path
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/files\/.+$/, methods: ["GET", "DELETE"], description: "Read or delete specific workspace file" },

  // Workspace directory creation
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/directories$/, methods: ["POST"], description: "Create workspace directory" },

  // Sandbox-scoped agent tasks (list, create/run)
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/agent\/tasks$/, methods: ["GET", "POST"], description: "List or execute sandbox agent task" },

  // Sandbox-scoped agent task detail
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/agent\/tasks\/[a-zA-Z0-9_-]+$/, methods: ["GET"], description: "Get sandbox agent task details" },

  // Sandbox-scoped agent task cancellation
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/agent\/tasks\/[a-zA-Z0-9_-]+\/cancel$/, methods: ["POST"], description: "Cancel sandbox agent task" },

  // Sandbox-scoped agent task execution jobs
  { pattern: /^\/api\/v1\/sandboxes\/[a-zA-Z0-9_-]+\/agent\/tasks\/[a-zA-Z0-9_-]+\/executions$/, methods: ["GET"], description: "Get agent task executions" },

  // Agent model-driven task (standalone synchronous run)
  { pattern: /^\/api\/v1\/agent\/run$/, methods: ["POST"], description: "Synchronous agent run" },

  // Global agent task detail & cancellation by ID
  { pattern: /^\/api\/v1\/agent\/tasks\/[a-zA-Z0-9_-]+$/, methods: ["GET"], description: "Get agent task by ID" },
  { pattern: /^\/api\/v1\/agent\/tasks\/[a-zA-Z0-9_-]+\/cancel$/, methods: ["POST"], description: "Cancel agent task by ID" },

  // Security Policy Engine (read platform policy & dry-run evaluation)
  { pattern: /^\/api\/v1\/security\/policy$/, methods: ["GET"], description: "Get platform security policy" },
  { pattern: /^\/api\/v1\/security\/evaluate$/, methods: ["POST"], description: "Dry-run security policy evaluation" },
];

/**
 * Check if the given request method and path are explicitly permitted.
 */
export function isRouteAllowed(method: string, path: string): boolean {
  const normalizedMethod = method.toUpperCase();
  const cleanPath = path.split("?")[0];

  for (const route of ALLOWED_ROUTES) {
    if (route.pattern.test(cleanPath)) {
      return route.methods.includes(normalizedMethod);
    }
  }
  return false;
}

/**
 * Handle incoming BFF HTTP request and forward to FastAPI target.
 */
export function handleBffRequest(
  req: IncomingMessage,
  res: ServerResponse,
  targetUrl = FASTAPI_TARGET,
  apiKey = SERVER_API_KEY
): void {
  const method = req.method?.toUpperCase() || "GET";
  const rawUrl = req.url || "/";
  const cleanPath = rawUrl.split("?")[0];

  // 1. Enforce strict allowlist (no open proxy)
  if (!isRouteAllowed(method, cleanPath)) {
    res.statusCode = 403;
    res.setHeader("Content-Type", "application/json");
    res.end(
      JSON.stringify({
        error: "Forbidden",
        message: `BFF blocked request: Method '${method}' on '${cleanPath}' is not allowlisted.`,
      })
    );
    return;
  }

  // 2. Resolve destination URL
  let destUrl: URL;
  try {
    destUrl = new URL(rawUrl, targetUrl);
  } catch {
    res.statusCode = 400;
    res.setHeader("Content-Type", "application/json");
    res.end(
      JSON.stringify({
        error: "BadRequest",
        message: "Invalid upstream URL resolution.",
      })
    );
    return;
  }

  // 3. Prepare headers - NEVER forward client headers that might leak credentials
  const headers: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(req.headers)) {
    const lowerKey = key.toLowerCase();
    // Strip client-side attempt to spoof or pass X-API-Key or host
    if (lowerKey === "x-api-key" || lowerKey === "host") {
      continue;
    }
    if (value !== undefined) {
      headers[key] = value;
    }
  }

  // 4. Inject server-side API key if configured
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }

  headers["host"] = destUrl.host;

  // 5. Configure long timeout for synchronous agent operations (300 seconds)
  const proxyReq = http.request(
    destUrl,
    {
      method,
      headers,
      timeout: 300_000, // 5 minutes timeout for long-running agent tasks
    },
    (proxyRes: IncomingMessage) => {
      res.statusCode = proxyRes.statusCode || 500;

      // Copy response headers safely
      for (const [key, value] of Object.entries(proxyRes.headers)) {
        if (value !== undefined) {
          res.setHeader(key, value);
        }
      }

      // Stream response back to browser client
      proxyRes.pipe(res);
    }
  );

  proxyReq.on("timeout", () => {
    proxyReq.destroy();
    if (!res.headersSent) {
      res.statusCode = 504;
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify({
          error: "GatewayTimeout",
          message: "Upstream AI Sandbox backend timed out after 300 seconds.",
        })
      );
    }
  });

  proxyReq.on("error", (err: Error) => {
    if (!res.headersSent) {
      res.statusCode = 502;
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify({
          error: "BadGateway",
          message: `BFF failed to connect to upstream backend: ${err.message}`,
        })
      );
    }
  });

  // Forward incoming body data
  req.pipe(proxyReq);
}

/**
 * MIME type resolution helper for static assets in production mode.
 */
function getMimeType(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case ".html": return "text/html; charset=utf-8";
    case ".js": return "application/javascript; charset=utf-8";
    case ".css": return "text/css; charset=utf-8";
    case ".json": return "application/json; charset=utf-8";
    case ".svg": return "image/svg+xml";
    case ".png": return "image/png";
    case ".jpg": case ".jpeg": return "image/jpeg";
    case ".gif": return "image/gif";
    case ".ico": return "image/x-icon";
    case ".woff": return "font/woff";
    case ".woff2": return "font/woff2";
    default: return "application/octet-stream";
  }
}

/**
 * Standalone production HTTP server handler.
 * Serves `/api/*`, `/health`, `/ready` via the BFF proxy, and static frontend assets from `dist/` with SPA fallback.
 */
export function createBffServer(distDir?: string): http.Server {
  const resolvedDist = distDir || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist");

  return http.createServer((req: IncomingMessage, res: ServerResponse) => {
    const rawPath = req.url?.split("?")[0] || "/";

    if (rawPath.startsWith("/api/") || rawPath === "/health" || rawPath === "/ready") {
      handleBffRequest(req, res);
      return;
    }

    // Static asset serving with SPA fallback
    const safePath = path.normalize(rawPath).replace(/^(\.\.[/\\])+/, "");
    let filePath = path.join(resolvedDist, safePath);

    if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
      filePath = path.join(filePath, "index.html");
    }

    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      res.setHeader("Content-Type", getMimeType(filePath));
      fs.createReadStream(filePath).pipe(res);
      return;
    }

    // SPA fallback: index.html
    const indexPath = path.join(resolvedDist, "index.html");
    if (fs.existsSync(indexPath)) {
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      fs.createReadStream(indexPath).pipe(res);
    } else {
      res.statusCode = 404;
      res.end("Not Found");
    }
  });
}

/**
 * Vite plugin exposing the BFF middleware on same-origin `/api/*`, `/health`, and `/ready`.
 */
export function bffPlugin() {
  return {
    name: "vite-bff-proxy",
    configureServer(server: { middlewares: { use: (fn: (req: IncomingMessage, res: ServerResponse, next: () => void) => void) => void } }) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split("?")[0] || "";
        if (path.startsWith("/api/") || path === "/health" || path === "/ready") {
          handleBffRequest(req, res);
        } else {
          next();
        }
      });
    },
    configurePreviewServer(server: { middlewares: { use: (fn: (req: IncomingMessage, res: ServerResponse, next: () => void) => void) => void } }) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split("?")[0] || "";
        if (path.startsWith("/api/") || path === "/health" || path === "/ready") {
          handleBffRequest(req, res);
        } else {
          next();
        }
      });
    },
  };
}

// Auto-run standalone server if invoked directly
const isDirectExecution =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (isDirectExecution) {
  const port = Number(process.env.PORT) || 3000;
  const server = createBffServer();
  server.listen(port, () => {
    console.log(`[BFF Server] Running on http://localhost:${port}`);
    console.log(`[BFF Server] Proxying to FastAPI backend: ${FASTAPI_TARGET}`);
  });
}

export default bffPlugin;
