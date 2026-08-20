# Agent Studio handbook

## Mission

Agent Studio is a development and debugging platform for creating, configuring, and evaluating AI agents. Its purpose is to make agent behavior observable, testable, explainable, and reproducible. It is not a ChatGPT clone.

## Runtime

The runtime follows a hybrid architecture. The OpenAI Agents SDK stays inside the AgentRuntime adapter, while persistence, evaluation, knowledge retrieval, memory policy, and application tracing remain owned by Agent Studio.

## Testing

The deterministic MockProvider is used for tests and the calculator demo. Unit tests and primary integration paths must run without a real API key.
