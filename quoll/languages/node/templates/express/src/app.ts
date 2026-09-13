import express, { type NextFunction, type Request, type Response } from "express";

export function createApp() {
  const app = express();
  app.disable("x-powered-by");
  app.use(express.json());

  app.get("/health", (_req, res) => {
    res.json({ status: "ok" });
  });

  app.get("/api/hello", (req, res) => {
    const name = typeof req.query.name === "string" ? req.query.name : "world";
    res.json({ message: `Hello, ${name}!` });
  });

  app.use((_req, res) => {
    res.status(404).json({ error: "Not found" });
  });

  app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
    console.error(err);
    res.status(500).json({ error: "Internal server error" });
  });

  return app;
}
