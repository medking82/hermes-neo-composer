# Runtime regression tests

These tests execute against an **isolated Hermes source checkout** with the adapter installed. Do not copy them into a live runtime, and do not run them on GA401. Qualify on WSL/Linux and reserve GA401 for deployment acceptance.

From this Neo repository, with `HERMES_TEST_ROOT` pointing at the isolated checkout and `HERMES_PYTHON` pointing at its test environment:

```sh
python3 host-adapter/neo_host_adapter.py install --root "$HERMES_TEST_ROOT" --frontend skip
cp host-adapter/tests/test_neo_composer_*.py "$HERMES_TEST_ROOT/tests/gateway/"
(cd "$HERMES_TEST_ROOT" && bash scripts/run_tests.sh \
  tests/gateway/test_neo_composer_adapter.py \
  tests/gateway/test_neo_composer_integration.py)
```

The unit tests exercise real staging of PNG bytes, generation checks, receipt matching, timeout withdrawal before a queued reply worker starts, repeated request IDs, permissions and safe role alternation.

The integration test launches a real local gateway with a deterministic local model fixture. It proves image-reference injection into the same provider turn, durable history and absence of a second admission. It does **not** prove a real model called `vision_analyze` or understood an image. Temporary gateways and the fixture server are closed in fixture teardown. Gateway dependencies, including Starlette, must exist in the disposable test environment; an HTTP 500 during WebSocket upgrade is a failed test, not a skip.
