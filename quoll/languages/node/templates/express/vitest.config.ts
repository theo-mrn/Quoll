import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      // The entry point only starts the server.
      exclude: ["src/server.ts"],
    },
  },
});
