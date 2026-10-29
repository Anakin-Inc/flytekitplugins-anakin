# Changelog

## 0.1.0 (unreleased)

First release.

- 24 Flyte tasks covering scrape, map, crawl, search, agentic search, Wire
  (discover, catalogs, catalog, read, write, identities, login, build, build
  status), website monitors, AI visibility, browser sessions and AI browser
  tasks.
- Built on `anakin-sdk` 0.2. Wire actions accept `credential_id` /
  `identity_id`, so actions that need a signed-in account work.
- Outputs are typed `anakin.models` Pydantic models (flytekit >= 1.14).
- API key from the Flyte secret `anakin/api-key`, then `ANAKIN_API_KEY`, then
  keyless mode for scrape and Wire discovery.
