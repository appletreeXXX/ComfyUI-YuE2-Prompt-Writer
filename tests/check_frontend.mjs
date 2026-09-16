// Syntax-check the frontend modules by parsing them, without executing the
// imports (which resolve to ComfyUI's own /scripts/api.js at runtime).
//
// vm.SourceTextModule only exists under --experimental-vm-modules, so the
// primary path shells out to `node --check` with an explicit .mjs extension:
// that parses the file as ESM for real, keeps import.meta legal, and needs no
// flag. The vm path stays as a fallback for when spawning is unavailable.
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { resolve, join } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import vm from "node:vm";

const files = ["web/main.js", "web/api/yue2.js"];
const css = readFileSync(resolve("web/styles/yue2.css"), "utf8");
let failed = 0;

function parseWithNodeCheck(source, file) {
  const dir = mkdtempSync(join(tmpdir(), "yue2-check-"));
  const target = join(dir, "module.mjs");
  try {
    writeFileSync(target, source, "utf8");
    execFileSync(process.execPath, ["--check", target], { stdio: "pipe" });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

for (const file of files) {
  const source = readFileSync(resolve(file), "utf8");
  try {
    parseWithNodeCheck(source, file);
    console.log(`  ok   ${file} parses as an ES module`);
  } catch (error) {
    // Fall back to the in-process parser before declaring failure.
    try {
      if (typeof vm.SourceTextModule === "function") {
        new vm.SourceTextModule(source, { identifier: file });
      } else {
        throw error;
      }
      console.log(`  ok   ${file} parses as an ES module`);
    } catch {
      failed += 1;
      const detail = (error.stderr || Buffer.from("")).toString().trim() ||
        error.message;
      console.log(`  FAIL ${file}: ${detail.split("\n")[0]}`);
    }
  }
}

// The markup strings must be balanced, since they are assembled by hand.
const mainSource = readFileSync(resolve("web/main.js"), "utf8");
const templateLiterals = (mainSource.match(/`/g) || []).length;
if (templateLiterals % 2 !== 0) {
  failed += 1;
  console.log(`  FAIL web/main.js: unbalanced backticks (${templateLiterals})`);
} else {
  console.log("  ok   web/main.js: template literals balanced");
}

// Regression guards for the two problems this file's fixes address.
//
// 1. The copy button must carry visible text. A bare icon left the button
//    unreadable because ComfyUI's global button reset was winning.
if (!/>\s*复制\s*</.test(mainSource)) {
  failed += 1;
  console.log("  FAIL web/main.js: copy button has no 复制 label");
} else {
  console.log("  ok   web/main.js: copy button carries a 复制 label");
}
for (const rule of [".yue2-copy", ".yue2-toggle"]) {
  const block = css.match(
    new RegExp(`\\${rule}\\s*\\{[^}]*\\}`, "s"),
  );
  if (!block) {
    failed += 1;
    console.log(`  FAIL web/styles/yue2.css: ${rule} rule is missing`);
    continue;
  }
  if (!/color\s*:/.test(block[0]) || !/font\s*:|font-size\s*:/.test(block[0])) {
    failed += 1;
    console.log(
      `  FAIL web/styles/yue2.css: ${rule} must set color and a font size`,
    );
  } else {
    console.log(`  ok   web/styles/yue2.css: ${rule} sets color and font`);
  }
}

// 2. Output must be able to grow: the old fixed max-height cut long previews
//    off, and nothing offered a way to reveal the rest.
if (/\.yue2-output pre\s*\{[^}]*max-height:\s*300px/s.test(css)) {
  failed += 1;
  console.log("  FAIL web/styles/yue2.css: output is clamped to 300px again");
} else {
  console.log("  ok   web/styles/yue2.css: output is not clamped to 300px");
}

// Every block collapses, not just the long ones, so the panel reads as a tidy
// list of the six outputs. The toggle must be rendered unconditionally and the
// collapsed state must actually hide the body.
if (!/state\.expanded/.test(mainSource)) {
  failed += 1;
  console.log("  FAIL web/main.js: expanded-state tracking is missing");
} else {
  console.log("  ok   web/main.js: tracks which blocks are expanded");
}
if (/value\.length\s*>\s*COLLAPSE_THRESHOLD/.test(mainSource) ||
    /COLLAPSE_THRESHOLD/.test(mainSource)) {
  failed += 1;
  console.log("  FAIL web/main.js: collapse is still decided by length");
} else {
  console.log("  ok   web/main.js: every block collapses regardless of length");
}
if (!/class="yue2-toggle"/.test(mainSource)) {
  failed += 1;
  console.log("  FAIL web/main.js: blocks are not given a toggle control");
} else {
  console.log("  ok   web/main.js: every block renders a toggle control");
}
if (!/\.yue2-output\[data-collapsed="true"\]\s*pre\s*\{[^}]*display:\s*none/s.test(css)) {
  failed += 1;
  console.log("  FAIL web/styles/yue2.css: collapsed blocks do not hide their body");
} else {
  console.log("  ok   web/styles/yue2.css: collapsed blocks hide their body");
}
if (!/\.yue2-chevron/.test(css) || !/yue2-chevron/.test(mainSource)) {
  failed += 1;
  console.log("  FAIL web/styles/yue2.css: the expand affordance (chevron) is missing");
} else {
  console.log("  ok   collapsible headers show a chevron affordance");
}
if (!/min-width:\s*0/.test(
  (css.match(/\.yue2-column\s*\{[^}]*\}/s) || [""])[0],
)) {
  failed += 1;
  console.log("  FAIL web/styles/yue2.css: .yue2-column needs min-width: 0");
} else {
  console.log("  ok   web/styles/yue2.css: .yue2-column can shrink (min-width: 0)");
}

// 3. Blocks stacked in a fixed-height flex column must refuse to shrink.
//    Without flex-shrink: 0, a column whose content is taller than the panel
//    squashes every block into a few pixels and they visually overlap; the
//    column's own scrollbar is what should absorb the overflow.
function ruleBody(selector) {
  const match = css.match(
    new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`, "s"),
  );
  return match ? match[1] : null;
}

for (const selector of [".yue2-output", ".yue2-section"]) {
  const body = ruleBody(selector);
  if (body === null) {
    failed += 1;
    console.log(`  FAIL web/styles/yue2.css: ${selector} rule is missing`);
  } else if (!/flex:\s*0\s+0\s+auto|flex-shrink:\s*0/.test(body)) {
    failed += 1;
    console.log(
      `  FAIL web/styles/yue2.css: ${selector} must set flex: 0 0 auto (or flex-shrink: 0)`,
    );
  } else {
    console.log(`  ok   web/styles/yue2.css: ${selector} resists flex squashing`);
  }
}

// The CSS must not have obviously unbalanced braces.
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
