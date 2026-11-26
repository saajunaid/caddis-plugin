// Copy the embeddable flow-studio files into an application vendor folder and write vendor.manifest.json.
//   node --experimental-strip-types scripts/vendor-copy.mjs <app-vendor-dir> [--sha <commit>]

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const defaultRoot = resolve(here, "..");
const SOURCE_PATH = ".github/skills/frontend/flow-studio";

const TEMPLATE_FILES = [
  "templates/flow-studio.lib.mjs",
  "templates/flow-studio.lib.d.mts",
  "templates/flow-studio.css",
  "templates/flow-studio.scoped.css",
];
const SOURCE_DIRS = ["react", "src"];

const isTestFile = name => /\.test\.[^/\\]+$/.test(name);

function usageError(message) {
  return Object.assign(new Error(message), { exitCode: 2 });
}

function canonicalPath(p) {
  const abs = resolve(p);
  const tail = [];
  let cur = abs;
  while (!existsSync(cur)) {
    const parent = dirname(cur);
    if (parent === cur) break;
    tail.unshift(cur.slice(parent.length).replace(/^[/\\]+/, ""));
    cur = parent;
  }
  const base = existsSync(cur) ? realpathSync(cur) : cur;
  const full = tail.length ? join(base, ...tail) : base;
  return process.platform === "win32" ? full.toLowerCase() : full;
}

function isSameOrInside(candidate, parentDir) {
  const rel = relative(canonicalPath(parentDir), canonicalPath(candidate));
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function collectDirFiles(baseDir, subDir) {
  const start = join(baseDir, subDir);
  if (!existsSync(start) || !statSync(start).isDirectory()) {
    throw new Error(`vendor-copy: missing source directory ${subDir}`);
  }
  const results = [];
  function walk(current) {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const full = join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile() && !isTestFile(entry.name)) {
        results.push(relative(baseDir, full).replace(/\\/g, "/"));
      }
    }
  }
  walk(start);
  return results;
}

export function parseRepoSlug(remoteUrl) {
  const trimmed = String(remoteUrl ?? "").trim();
  const match = trimmed.match(/[:/]([^/:]+\/[^/\s]+?)(?:\.git)?$/);
  return match ? match[1] : "";
}

function defaultRunGit(cwd, args) {
  const res = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  if (res.error) return { status: 1, stdout: "" };
  return { status: res.status ?? 1, stdout: res.stdout ?? "" };
}

export function vendorCopy(destDir, opts = {}) {
  const rootDir = resolve(opts.rootDir ?? defaultRoot);
  const runGit = opts.runGit ?? (args => defaultRunGit(rootDir, args));
  const log = opts.log ?? console.log;

  const targetRoot = resolve(destDir);
  if (isSameOrInside(targetRoot, rootDir)) {
    throw usageError(
      `vendor-copy: refusing to write to ${targetRoot} because it is the flow-studio skill folder or inside it; pass the application's vendor subfolder outside ${rootDir}.`,
    );
  }

  if (existsSync(targetRoot)) {
    if (!statSync(targetRoot).isDirectory()) {
      throw usageError(`vendor-copy: refusing to write to ${targetRoot} because it is not a folder; pass the vendor subfolder.`);
    }
    const entries = readdirSync(targetRoot);
    const manifestPath = join(targetRoot, "vendor.manifest.json");
    const hasManifest = existsSync(manifestPath) && statSync(manifestPath).isFile();
    if (entries.length > 0 && !hasManifest) {
      throw usageError(
        `vendor-copy: refusing to overwrite ${targetRoot} because it is non-empty and has no vendor.manifest.json; pass the vendor subfolder (for example <app>/src/vendor/flow-studio).`,
      );
    }
  }

  const relPaths = [
    ...TEMPLATE_FILES,
    ...SOURCE_DIRS.flatMap(dir => collectDirFiles(rootDir, dir)),
  ].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));

  const prepared = [];
  const files = {};
  for (const rel of relPaths) {
    const srcPath = join(rootDir, rel);
    if (!existsSync(srcPath) || !statSync(srcPath).isFile()) {
      throw new Error(`vendor-copy: missing source file ${rel}`);
    }
    const normalised = readFileSync(srcPath, "utf8").replace(/\r\n/g, "\n");
    const buf = Buffer.from(normalised, "utf8");
    prepared.push({ rel, buf });
    files[rel] = createHash("sha256").update(buf).digest("hex");
  }

  mkdirSync(targetRoot, { recursive: true });
  for (const managed of ["templates", ...SOURCE_DIRS]) {
    const sub = join(targetRoot, managed);
    if (existsSync(sub)) rmSync(sub, { recursive: true, force: true });
  }
  for (const { rel, buf } of prepared) {
    const outPath = join(targetRoot, rel);
    mkdirSync(dirname(outPath), { recursive: true });
    writeFileSync(outPath, buf);
  }

  const originRes = runGit(["remote", "get-url", "origin"]);
  const sourceRepo = opts.sourceRepo ?? ((originRes.status === 0 ? parseRepoSlug(originRes.stdout) : "") || "unknown");

  let sourceSha = opts.sha;
  if (!sourceSha) {
    const headRes = runGit(["rev-parse", "HEAD"]);
    sourceSha = headRes.status === 0 && headRes.stdout.trim() ? headRes.stdout.trim() : "unknown";
  }

  const manifest = {
    source_repo: sourceRepo,
    source_path: SOURCE_PATH,
    source_sha: sourceSha,
    files,
  };
  writeFileSync(join(targetRoot, "vendor.manifest.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");

  if (sourceSha && sourceSha !== "unknown") {
    const countRes = runGit(["rev-list", "--count", `${sourceSha}..origin/main`, "--", "."]);
    const countText = countRes.stdout.trim();
    if (countRes.status === 0 && /^\d+$/.test(countText)) {
      log(`${countText} commits under ${SOURCE_PATH} on origin/main are newer than ${sourceSha}`);
      return manifest;
    }
  }
  log("newer-commit count unknown");
  return manifest;
}

function parseCliArgs(argv) {
  let destDir = null;
  let sha;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--sha") {
      const val = argv[++i];
      if (!val || val.startsWith("--")) return null;
      sha = val;
    } else if (arg.startsWith("--sha=")) {
      const val = arg.slice(6);
      if (!val) return null;
      sha = val;
    } else if (arg.startsWith("--")) {
      return null;
    } else if (destDir === null) {
      destDir = arg;
    } else {
      return null;
    }
  }
  return destDir ? { destDir, sha } : null;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const parsed = parseCliArgs(process.argv.slice(2));
  if (!parsed) {
    console.error("usage: node --experimental-strip-types scripts/vendor-copy.mjs <app-vendor-dir> [--sha <commit>]");
    process.exit(2);
  }
  try {
    vendorCopy(parsed.destDir, { sha: parsed.sha });
  } catch (err) {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(typeof err?.exitCode === "number" ? err.exitCode : 1);
  }
}
