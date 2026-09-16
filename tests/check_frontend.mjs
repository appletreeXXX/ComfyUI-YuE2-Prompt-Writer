// Syntax-check the frontend modules by parsing them, without executing the
// imports (which resolve to ComfyUI's own /scripts/api.js at runtime).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import vm from "node:vm";

const files = ["web/main.js", "web/api/yue2.js"];
let failed = 0;

for (const file of files) {
  const source = readFileSync(resolve(file), "utf8");
  try {
    // vm.SourceTextModule parses ESM syntax without resolving specifiers.
    if (typeof vm.SourceTextModule === "function") {
      new vm.SourceTextModule(source, { identifier: file });
    } else {
      // Fallback: rewriting the bare specifiers lets the parser accept the file.
      const rewritten = source.replace(/(from\s+)"\/scripts\/[^"]*"/g, '$1"./stub.js"');
      new vm.Script(`(async()=>{${rewritten.replace(/^import[^;]*;/gm, "")}})()`, { filename: file });
    }
    console.log(`  ok   ${file} parses as an ES module`);
  } catch (error) {
    failed += 1;
    console.log(`  FAIL ${file}: ${error.message}`);
  }
}

// The markup strings must be balanced, since they are assembled by hand.
for (const file of ["web/main.js"]) {
  const source = readFileSync(resolve(file), "utf8");
  const templateLiterals = (source.match(/`/g) || []).length;
  if (templateLiterals % 2 !== 0) {
    failed += 1;
    console.log(`  FAIL ${file}: unbalanced backticks (${templateLiterals})`);
  } else {
    console.log(`  ok   ${file}: template literals balanced`);
  }
}

// The CSS must not have obviously unbalanced braces.
const css = readFileSync(resolve("web/styles/yue2.css"), "utf8");
const open = (css.match(/\{/g) || []).length;
const close = (css.match(/\}/g) || []).length;
if (open !== close) {
  failed += 1;
  console.log(`  FAIL web/styles/yue2.css: ${open} '{' vs ${close} '}'`);
} else {
  console.log(`  ok   web/styles/yue2.css: braces balanced (${open} rules)`);
}

if (failed) {
  console.log(`\n${failed} FAILURE(S)`);
  process.exit(1);
}
console.log("\nfrontend checks passed");
