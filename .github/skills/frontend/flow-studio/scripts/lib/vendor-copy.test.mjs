import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { vendorCopy } from "../vendor-copy.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");

function walkFiles(dir, base = dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkFiles(full, base));
    else if (entry.isFile()) out.push(relative(base, full).replace(/\\/g, "/"));
  }
  return out.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

function runCli(...args) {
  return spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--no-warnings", join(root, "scripts/vendor-copy.mjs"), ...args],
    { encoding: "utf8" },
  );
}

test("vendor-copy works on an empty folder and re-vendors a folder that has vendor.manifest.json", () => {
  const dest = mkdtempSync(join(tmpdir(), "fs-vendor-copy-"));
  try {
    // 1. Empty folder succeeds
    const first = runCli(dest, "--sha", "HEAD");
    assert.equal(first.status, 0, first.stderr);
    assert.match(first.stdout, /commits under \.github\/skills\/frontend\/flow-studio on origin\/main are newer than HEAD|newer-commit count unknown/);

    const manifestPath = join(dest, "vendor.manifest.json");
    assert.equal(existsSync(manifestPath), true, "writes vendor.manifest.json");

    // 2. Folder with vendor.manifest.json succeeds, preserves top-level README.md, and removes stale managed files
    writeFileSync(join(dest, "README.md"), "# Vendor copy\n", "utf8");
    writeFileSync(join(dest, "src/stale-removed-file.ts"), "export const stale = true;\n", "utf8");

    const r = runCli(dest, "--sha", "HEAD");
    assert.equal(r.status, 0, r.stderr);

    assert.equal(existsSync(join(dest, "README.md")), true, "preserves top-level README.md");
    assert.equal(existsSync(join(dest, "src/stale-removed-file.ts")), false, "removes stale file under managed src/");

    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifest.source_path, ".github/skills/frontend/flow-studio");
    assert.equal(typeof manifest.source_repo, "string");
    assert.ok(manifest.source_repo.length > 0);
    assert.equal(manifest.source_sha, "HEAD");

    const keys = Object.keys(manifest.files);
    const sorted = [...keys].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    assert.deepEqual(keys, sorted, "manifest.files keys are lexicographically sorted");

    for (const reqFile of [
      "templates/flow-studio.lib.mjs",
      "templates/flow-studio.lib.d.mts",
      "templates/flow-studio.css",
      "templates/flow-studio.scoped.css",
    ]) {
      assert.ok(keys.includes(reqFile), `manifest lists ${reqFile}`);
      assert.equal(existsSync(join(dest, reqFile)), true, `copied ${reqFile}`);
    }
    assert.ok(keys.some(k => k.startsWith("react/")), "copies react/ files");
    assert.ok(keys.some(k => k.startsWith("src/")), "copies src/ files");

    const onDisk = walkFiles(dest).filter(f => f !== "README.md" && f !== "vendor.manifest.json");
    assert.deepEqual(onDisk, sorted, "every copied file is listed in manifest and vice versa");
    assert.equal(onDisk.some(f => /\.test\./.test(f)), false, "no *.test.* file is copied");

    for (const rel of keys) {
      const actual = createHash("sha256").update(readFileSync(join(dest, rel))).digest("hex");
      assert.equal(manifest.files[rel], actual, `sha256 matches copied bytes for ${rel}`);
    }
  } finally {
    rmSync(dest, { recursive: true, force: true });
  }
});

test("vendor-copy works when destination folder does not exist yet", () => {
  const base = mkdtempSync(join(tmpdir(), "fs-vendor-new-"));
  try {
    const dest = join(base, "src", "vendor", "flow-studio");
    const r = runCli(dest, "--sha", "HEAD");
    assert.equal(r.status, 0, r.stderr);
    assert.equal(existsSync(join(dest, "vendor.manifest.json")), true);
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
});

test("vendor-copy refuses (exit 2) on a folder with src/ and no manifest, leaving app files untouched", () => {
  const appDir = mkdtempSync(join(tmpdir(), "fs-vendor-app-"));
  try {
    mkdirSync(join(appDir, "src"), { recursive: true });
    mkdirSync(join(appDir, "templates"), { recursive: true });
    writeFileSync(join(appDir, "src/main.tsx"), "export const app = 42;\n", "utf8");
    writeFileSync(join(appDir, "templates/index.html"), "<h1>App</h1>\n", "utf8");

    const r = runCli(appDir);
    assert.equal(r.status, 2, `expected exit 2, got ${r.status}: ${r.stderr}`);
    assert.ok(r.stderr.includes(appDir), `error message must name ${appDir}: ${r.stderr}`);
    assert.match(r.stderr, /vendor subfolder/i, `error message must advise passing the vendor subfolder: ${r.stderr}`);

    assert.equal(readFileSync(join(appDir, "src/main.tsx"), "utf8"), "export const app = 42;\n", "app src/main.tsx untouched");
    assert.equal(readFileSync(join(appDir, "templates/index.html"), "utf8"), "<h1>App</h1>\n", "app templates/index.html untouched");
    assert.equal(existsSync(join(appDir, "vendor.manifest.json")), false, "no manifest written");
    assert.equal(existsSync(join(appDir, "react")), false, "no react/ created");
  } finally {
    rmSync(appDir, { recursive: true, force: true });
  }
});

test("vendor-copy refuses (exit 2) when destination is the skill root or inside it", () => {
  const rRoot = runCli(root);
  assert.equal(rRoot.status, 2, `expected exit 2 on skill root, got ${rRoot.status}`);
  assert.match(rRoot.stderr, /skill folder/i);
  assert.equal(existsSync(join(root, "src/engine.ts")), true, "skill src/engine.ts untouched");
  assert.equal(existsSync(join(root, "src/engine.test.ts")), true, "skill test files untouched");
  assert.equal(existsSync(join(root, "vendor.manifest.json")), false, "no manifest written in skill root");

  const inside = join(root, "out", "nested-vendor-refused");
  const rInside = runCli(inside);
  assert.equal(rInside.status, 2, `expected exit 2 inside skill root, got ${rInside.status}`);
  assert.match(rInside.stderr, /skill folder/i);
  assert.equal(existsSync(inside), false, "nothing created inside skill root");
});

test("vendorCopy fails before deleting anything when a source file is missing", () => {
  const tmp = mkdtempSync(join(tmpdir(), "fs-vendor-missing-src-"));
  try {
    const fakeSkill = join(tmp, "skill");
    const dest = join(tmp, "dest");
    mkdirSync(join(fakeSkill, "src"), { recursive: true });
    mkdirSync(join(fakeSkill, "react"), { recursive: true });
    mkdirSync(join(fakeSkill, "templates"), { recursive: true });
    writeFileSync(join(fakeSkill, "src/a.ts"), "export const a = 1;\n", "utf8");
    writeFileSync(join(fakeSkill, "react/b.tsx"), "export const b = 2;\n", "utf8");
    // Copy 3 of the 4 required template files; omit templates/flow-studio.scoped.css
    cpSync(join(root, "templates/flow-studio.lib.mjs"), join(fakeSkill, "templates/flow-studio.lib.mjs"));
    cpSync(join(root, "templates/flow-studio.lib.d.mts"), join(fakeSkill, "templates/flow-studio.lib.d.mts"));
    cpSync(join(root, "templates/flow-studio.css"), join(fakeSkill, "templates/flow-studio.css"));

    // Populate dest with an existing valid manifest and files that would be wiped if deletion ran early
    mkdirSync(join(dest, "src"), { recursive: true });
    mkdirSync(join(dest, "react"), { recursive: true });
    mkdirSync(join(dest, "templates"), { recursive: true });
    writeFileSync(join(dest, "vendor.manifest.json"), '{"files":{}}\n', "utf8");
    writeFileSync(join(dest, "src/keep.ts"), "export const keep = 'intact';\n", "utf8");
    writeFileSync(join(dest, "react/keep.tsx"), "export const keepReact = 'intact';\n", "utf8");
    writeFileSync(join(dest, "templates/keep.css"), ".keep {}\n", "utf8");

    assert.throws(
      () => vendorCopy(dest, { rootDir: fakeSkill, sha: "abc1234", runGit: () => ({ status: 1, stdout: "" }), log: () => {} }),
      /missing source file templates\/flow-studio\.scoped\.css/,
    );

    assert.equal(readFileSync(join(dest, "src/keep.ts"), "utf8"), "export const keep = 'intact';\n", "dest src/keep.ts was not deleted");
    assert.equal(readFileSync(join(dest, "react/keep.tsx"), "utf8"), "export const keepReact = 'intact';\n", "dest react/keep.tsx was not deleted");
    assert.equal(readFileSync(join(dest, "templates/keep.css"), "utf8"), ".keep {}\n", "dest templates/keep.css was not deleted");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("vendorCopy prints 'newer-commit count unknown' and exits cleanly when git is unavailable", () => {
  const dest = mkdtempSync(join(tmpdir(), "fs-vendor-nogit-"));
  try {
    const logs = [];
    const manifest = vendorCopy(dest, {
      sha: "abc1234",
      runGit: () => ({ status: 1, stdout: "" }),
      log: msg => logs.push(msg),
    });
    assert.equal(manifest.source_sha, "abc1234");
    assert.ok(logs.some(l => l.includes("newer-commit count unknown")), `expected unknown message, got: ${logs.join("\n")}`);
  } finally {
    rmSync(dest, { recursive: true, force: true });
  }
});

test("vendorCopy prints exact newer-commit count from git rev-list and resolves HEAD when --sha is omitted", () => {
  const dest = mkdtempSync(join(tmpdir(), "fs-vendor-gitmock-"));
  try {
    const logs = [];
    const manifest = vendorCopy(dest, {
      runGit: args => {
        if (args[0] === "remote") return { status: 0, stdout: "https://github.com/example-org/caddis.git\n" };
        if (args[0] === "rev-parse") return { status: 0, stdout: "0123456789abcdef0123456789abcdef01234567\n" };
        if (args[0] === "rev-list") return { status: 0, stdout: "4\n" };
        return { status: 1, stdout: "" };
      },
      log: msg => logs.push(msg),
    });
    assert.equal(manifest.source_repo, "example-org/caddis");
    assert.equal(manifest.source_sha, "0123456789abcdef0123456789abcdef01234567");
    assert.deepEqual(logs, [
      "4 commits under .github/skills/frontend/flow-studio on origin/main are newer than 0123456789abcdef0123456789abcdef01234567",
    ]);
  } finally {
    rmSync(dest, { recursive: true, force: true });
  }
});
