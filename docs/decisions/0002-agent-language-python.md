# 0002. Agent language: Python instead of Java + Spring AI

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

My strongest stack is Java 17 + Spring Boot. The agent could be written in Java with Spring AI
or in Python with the official Anthropic SDK. The goal is to learn how an LLM agent works end to
end and to show that knowledge in a technical interview.

## Options

1. **Python + official `anthropic` SDK**
   - Pros: first-class SDK, new API features land there first; the AI tooling ecosystem
     (official MCP SDK, embedding libraries, evaluation tooling) is Python-first; I already
     built small agents in Python; less ceremony, so the agent logic stays visible.
   - Cons: not my main production stack; typing and packaging discipline must be enforced
     by convention (Pydantic, ruff, tests).
2. **Java 17 + Spring AI**
   - Pros: my strongest stack; Spring Boot gives config, DI, actuator and observability out
     of the box; enterprise clients often run on the JVM.
   - Cons: Spring AI abstracts the provider (portable `ChatClient`), which hides exactly the
     mechanics I want to learn (tool_use / tool_result blocks, stop reasons, caching);
     provider-specific features may lag behind the official SDK.
3. **Java with the official Anthropic Java SDK (no Spring AI)**
   - Pros: JVM stack without the abstraction layer.
   - Cons: smaller ecosystem for MCP, embeddings and evals; more boilerplate for a prototype.

## Decision

Option 1, Python. The point of this project is to understand the agent loop, retrieval and
evaluation; Python keeps those mechanics explicit and close to the official documentation.

## Consequences

- The design (tool registry, validation at the tool boundary, explicit loop) is language
  agnostic and could be ported to Spring Boot; that port is listed as a possible next step.
- Java strengths still show up in the architecture: layered packages, typed contracts
  (Pydantic models play the role of DTOs), integration tests against a real database,
  optimistic locking, CI.
