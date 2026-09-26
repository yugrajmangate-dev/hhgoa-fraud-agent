import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import { fileBundleLoader } from "./bundles";
import { getStatus, handleCopilot, type ServerConfig } from "./handler";

// Serves /api/copilot from the Vite dev and preview servers (Node side only). The config holds the
// API key in this closure; it is never added to `define` or import.meta.env, so it cannot reach
// the browser bundle.

const MAX_BODY = 8 * 1024;

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new Error("body too large"));
        req.destroy();
      } else chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", reject);
  });
}

function send(res: ServerResponse, status: number, body: unknown) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

export function copilotApiPlugin(config: ServerConfig, dataDir: string): Plugin {
  const loadBundle = fileBundleLoader(dataDir);
  const middleware = async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = (req.url ?? "").split("?")[0];
    if (url !== "" && url !== "/") return next();
    try {
      if (req.method === "GET") return send(res, 200, getStatus(config));
      if (req.method !== "POST") return send(res, 405, { error: "method not allowed" });
      let body: unknown = null;
      try {
        body = JSON.parse(await readBody(req));
      } catch {
        return send(res, 200, { mode: "fallback", reason: "bad_request" });
      }
      return send(res, 200, await handleCopilot(body, { config, loadBundle }));
    } catch {
      // Never echo internal errors (they could include provider details).
      return send(res, 200, { mode: "fallback", reason: "provider_error" });
    }
  };
  return {
    name: "hhgoa-copilot-api",
    configureServer(server) {
      server.middlewares.use("/api/copilot", middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use("/api/copilot", middleware);
    },
  };
}
