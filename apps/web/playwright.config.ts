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
      command: "powershell -NoProfile -Command \"if ($env:RUN_REAL_OPENAI_TESTS -ne '1') { Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue }; if ($env:RUN_REAL_DEEPSEEK_TESTS -ne '1') { Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue }; $env:MOCK_PROVIDER_BLOCK_INPUT='__playwright_wait_for_cancel__'; $env:OPENAI_MAX_OUTPUT_TOKENS='128'; $env:OPENAI_MAX_RETRIES='1'; $env:OPENAI_REQUEST_TIMEOUT_SECONDS='30'; $env:DEEPSEEK_MAX_OUTPUT_TOKENS='128'; $env:DEEPSEEK_MAX_RETRIES='1'; $env:DEEPSEEK_REQUEST_TIMEOUT_SECONDS='30'; ..\\..\\.venv\\Scripts\\uvicorn.exe app.main:app --app-dir ../api --host 127.0.0.1 --port 8110\"",
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
