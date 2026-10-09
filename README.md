# Quilora Assistant

A customer-support agent for **Quilora**, a fictional online fashion store. Customers write
in natural language; the assistant answers by calling a small set of well-defined tools over
the store's data (catalog, stock, size guides, policies, orders, returns) and hands off to a
human when it should.

> **Status:** work in progress, built in phases. See [`docs/phases/`](docs/phases/).

All data in this repository is synthetic. Quilora is not a real brand.

## Principles

- **The model proposes, the code decides.** Tools validate inputs, enforce security
  invariants and own every side effect.
- **Quality comes from tool design and evaluation**, not from prompt tweaking alone.
- **Measured, not demoed:** an evaluation suite runs in CI.

## Decisions

See [`docs/decisions/`](docs/decisions/).

## License

MIT
