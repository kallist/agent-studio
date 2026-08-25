import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 1,
  reporter: [["line"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3110",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
  webServer: [
    {
      command:
        "../../.venv/bin/python -m uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port 8110",
      env: {
        ALLOWED_HOSTS: "127.0.0.1,localhost",
        DEEPSEEK_API_KEY: "",
        MOCK_PROVIDER_BLOCK_INPUT: "__playwright_wait_for_cancel__",
        OPENAI_API_KEY: "",
        RUN_REAL_DEEPSEEK_TESTS: "0",
        RUN_REAL_OPENAI_TESTS: "0",
      },
      url: "http://127.0.0.1:8110/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "pnpm dev --webpack --hostname 127.0.0.1 --port 3110",
      env: { API_PROXY_URL: "http://127.0.0.1:8110" },
      url: "http://127.0.0.1:3110",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
