import assert from "node:assert/strict";

let assertBrowserExpression;
let runtimeExceptionMessage;
try {
  ({ assertBrowserExpression, runtimeExceptionMessage } = await import("./browser_runtime.mjs"));
} catch {
  // The assertions below are the RED state before the shared guard exists.
}

assert.equal(typeof assertBrowserExpression, "function", "browser expression validator must exist");
assert.equal(typeof runtimeExceptionMessage, "function", "runtime exception formatter must exist");
assert.doesNotThrow(() => assertBrowserExpression("(() => true)()"));
assert.throws(() => assertBrowserExpression("if (!text || /^https?:///i.test(text)) return false;"), SyntaxError);
assert.equal(runtimeExceptionMessage({ text: "Uncaught", exception: { description: "SyntaxError: Unexpected token 'const'" } }), "SyntaxError: Unexpected token 'const'");

console.log("browser_runtime_tests=PASS");
