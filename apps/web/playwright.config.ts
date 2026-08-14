import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3110",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "..\\..\\.venv\\Scripts\\uvicorn.exe app.main:app --app-dir ../api --host 127.0.0.1 --port 8110",
      url: "http://127.0.0.1:8110/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "powershell -NoProfile -Command \"$env:API_PROXY_URL='http://127.0.0.1:8110'; pnpm dev --webpack --hostname 127.0.0.1 --port 3110\"",
      url: "http://127.0.0.1:3110",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
