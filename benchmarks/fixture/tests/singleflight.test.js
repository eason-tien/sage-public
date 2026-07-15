import assert from "node:assert/strict";
import test from "node:test";

import { createSingleFlight } from "../src/singleflight.js";

test("coalesces concurrent calls and clears after success", async () => {
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const load = createSingleFlight(async (key) => {
    calls += 1;
    await gate;
    return `${key}:${calls}`;
  });

  const first = load("a");
  const second = load("a");
  assert.strictEqual(first, second);
  release();
  assert.equal(await first, "a:1");
  assert.equal(calls, 1);

  assert.equal(await load("a"), "a:2");
  assert.equal(calls, 2);
});

test("rejects an invalid loader synchronously", () => {
  assert.throws(() => createSingleFlight(null), TypeError);
});

