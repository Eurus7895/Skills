import assert from "node:assert/strict";
import { test } from "node:test";
import { status } from "./status.js";

test("status is queued", () => {
  assert.deepEqual(status("P1"), { parcelId: "P1", state: "queued" });
});
