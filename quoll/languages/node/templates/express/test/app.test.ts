import request from "supertest";
import { describe, expect, it } from "vitest";

import { createApp } from "../src/app.js";

const app = createApp();

describe("API", () => {
  it("reports its health", async () => {
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok" });
  });

  it("says hello", async () => {
    const res = await request(app).get("/api/hello?name=quoll");
    expect(res.body).toEqual({ message: "Hello, quoll!" });
  });

  it("says hello to the world by default", async () => {
    const res = await request(app).get("/api/hello");
    expect(res.body).toEqual({ message: "Hello, world!" });
  });

  it("answers 404 to unknown routes", async () => {
    const res = await request(app).get("/nope");
    expect(res.status).toBe(404);
  });
});
