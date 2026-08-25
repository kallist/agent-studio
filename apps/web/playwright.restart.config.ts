import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./reliability-e2e",
  timeout: 20_000,
  retries: 1,
  reporter: [["line"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.DOCKER_E2E_BASE_URL ?? "http://127.0.0.1:3300",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
});
