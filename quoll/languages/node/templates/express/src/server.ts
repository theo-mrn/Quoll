import { createApp } from "./app.js";

const port = Number(process.env.PORT ?? 3000);
const host = process.env.HOST ?? "0.0.0.0";

const server = createApp().listen(port, host, () => {
  console.log(`Listening on http://${host}:${port}`);
});

// Containers stop with SIGTERM: finish the requests in flight, then exit.
process.on("SIGTERM", () => server.close(() => process.exit(0)));
