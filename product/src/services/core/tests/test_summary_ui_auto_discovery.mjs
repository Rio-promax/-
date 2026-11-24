import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const appScript = readFileSync(new URL("../app/ui/app.js", import.meta.url), "utf8");

function extractDeclaration(startMarker, endMarker) {
  const start = appScript.indexOf(startMarker);
  assert.notEqual(start, -1, `${startMarker} must exist`);
  const end = appScript.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(end, -1, `${endMarker} must follow ${startMarker}`);
  return appScript.slice(start, end);
}

test("summary model discovery debounces rapid configuration changes", () => {
  const state = { summaryDiscoveryTimer: null };
  const pending = new Map();
  let nextTimer = 1;
  let discoveryCalls = 0;
  const context = {
    state,
    window: {
      clearTimeout(timerId) {
        pending.delete(timerId);
      },
      setTimeout(callback, delay) {
        const timerId = nextTimer++;
        pending.set(timerId, { callback, delay });
        return timerId;
      },
    },
    discoverSummaryModels() {
      discoveryCalls += 1;
    },
  };
  const source = `${extractDeclaration("function scheduleSummaryModelDiscovery() {", "\nfunction invalidateSummaryConnection")}\nscheduleSummaryModelDiscovery();`;

  vm.runInNewContext(source, context);
  const firstTimer = state.summaryDiscoveryTimer;
  vm.runInNewContext("scheduleSummaryModelDiscovery();", context);

  assert.equal(pending.has(firstTimer), false);
  assert.equal(pending.size, 1);
  const [latestTimer] = [...pending.values()];
  assert.equal(latestTimer.delay, 700);
  latestTimer.callback();
  assert.equal(discoveryCalls, 1);
  assert.equal(state.summaryDiscoveryTimer, null);
});

test("invalid settings do not cancel a pending automatic model discovery", async () => {
  let clearCalls = 0;
  const state = { summaryDiscoveryTimer: 7 };
  const context = {
    state,
    window: {
      clearTimeout() {
        clearCalls += 1;
      },
    },
    summaryConfigFromForm() {
      return {};
    },
    validateSummaryDraft() {
      return false;
    },
  };
  const saveFunction = extractDeclaration(
    "async function saveSummarySettings(event) {",
    "\nasync function clearSummarySettings",
  );

  await vm.runInNewContext(`${saveFunction}\nsaveSummarySettings({ preventDefault() {} });`, context);

  assert.equal(clearCalls, 0);
  assert.equal(state.summaryDiscoveryTimer, 7);
});
