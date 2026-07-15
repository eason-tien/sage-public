import assert from "node:assert/strict";
import test from "node:test";

import { auditSnapshot, createGame, parseLayout, stepGame } from "../game-core.js";

const layout = ["#######", "#P..G##", "#.##..#", "#E....#", "#######"];

test("layout parser rejects missing audit-critical entities", () => {
  assert.throws(() => parseLayout(["###", "#P#", "###"]), /requires P, G, E/);
});

test("wall blocks movement without changing the player position", () => {
  const before = createGame({ layout });
  const after = stepGame(before, "up");
  assert.deepEqual(after.player, before.player);
  assert.equal(after.events.at(-1).type, "blocked");
});

test("collecting a star increments score and removes exactly one star", () => {
  const before = createGame({ layout });
  const after = stepGame(before, "right");
  assert.equal(after.score, 10);
  assert.equal(after.stars.length, before.stars.length - 1);
  assert.equal(after.events.at(-1).type, "star_collected");
});

test("portal is fail-closed while stars remain", () => {
  let state = createGame({ layout });
  state = stepGame(state, "right");
  state = stepGame(state, "right");
  const blocked = stepGame(state, "right");
  assert.notDeepEqual(blocked.player, blocked.portal);
  assert.equal(blocked.status, "playing");
});

test("serialized audit state never authorizes merge or claims R5", () => {
  const snapshot = auditSnapshot(createGame({ layout }));
  assert.equal(snapshot.r5HumanVerification, "pending");
  assert.equal(snapshot.mergeAuthorized, false);
  assert.equal(snapshot.status, "playing");
});

test("invalid directions fail explicitly", () => {
  assert.throws(() => stepGame(createGame({ layout }), "teleport"), /invalid direction/);
});
