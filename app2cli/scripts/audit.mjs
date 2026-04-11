#!/usr/bin/env node

/**
 * Deterministic repository audit runner.
 *
 * Exit codes:
 * 0 = all selected required checks passed
 * 1 = one or more selected required checks failed
 * 2 = invalid usage or invalid config
 */

import { spawn } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import { delimiter, join, resolve } from "node:path";
import process from "node:process";
import { z } from "zod/v4";

const CHECK_SCHEMA = z
  .object({
    id: z.string().min(1),
    description: z.string().min(1),
    kind: z.enum(["command", "files"]),
    enabled: z.boolean(),
    required: z.boolean(),
    workingDirectory: z.string().min(1),
    command: z.string().min(1).optional(),
    args: z.array(z.string()).default([]),
    timeoutMs: z.number().int().positive(),
    tags: z.array(z.string()),
    prerequisiteFiles: z.array(z.string()),
    prerequisiteCommands: z.array(z.string()),
    missingPrerequisitePolicy: z.enum(["fail", "skip"]),
    paths: z.array(z.string()).optional(),
  })
  .superRefine((check, ctx) => {
    if (check.kind === "command" && check.command === undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "command checks require a command field",
        path: ["command"],
      });
    }

    if (check.kind === "files" && (check.paths ?? []).length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "files checks require at least one path",
        path: ["paths"],
      });
    }
  });

const CONFIG_SCHEMA = z.object({
  version: z.literal(1),
  checks: z.array(CHECK_SCHEMA).min(1),
});

/**
 * @typedef {z.infer<typeof CHECK_SCHEMA>} AuditCheck
 */

/**
 * @typedef {ReturnType<typeof parseCliArgs>} ParsedCliArgs
 */

const STATUS_LABELS = {
  passed: "PASS",
  failed: "FAIL",
  skipped: "SKIP",
  "dry-run": "DRY",
};

function parseCliArgs(argv) {
  const parsed = {
    configPath: "audit.config.json",
    list: false,
    only: new Set(),
    skip: new Set(),
    failFast: false,
    dryRun: false,
    json: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (arg === "--list") {
      parsed.list = true;
      continue;
    }

    if (arg === "--fail-fast") {
      parsed.failFast = true;
      continue;
    }

    if (arg === "--dry-run") {
      parsed.dryRun = true;
      continue;
    }

    if (arg === "--json") {
      parsed.json = true;
      continue;
    }

    if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }

    if (arg === "--config") {
      const value = argv[index + 1];
      if (value === undefined) {
        throw new Error("--config requires a path");
      }
      parsed.configPath = value;
      index += 1;
      continue;
    }

    if (arg === "--only") {
      const value = argv[index + 1];
      if (value === undefined) {
        throw new Error("--only requires a comma-separated list");
      }
      addCsvValues(parsed.only, value);
      index += 1;
      continue;
    }

    if (arg === "--skip") {
      const value = argv[index + 1];
      if (value === undefined) {
        throw new Error("--skip requires a comma-separated list");
      }
      addCsvValues(parsed.skip, value);
      index += 1;
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return parsed;
}

function addCsvValues(target, rawValue) {
  const values = rawValue
    .split(",")
    .map((value) => value.trim())
    .filter((value) => value.length > 0);

  for (const value of values) {
    target.add(value);
  }
}

function printHelp() {
  const helpText = [
    "Usage: node scripts/audit.mjs [options]",
    "",
    "Options:",
    "  --config <path>   Path to audit config (default: audit.config.json)",
    "  --list            List checks without running them",
    "  --only <ids>      Run only the comma-separated check ids",
    "  --skip <ids>      Skip the comma-separated check ids",
    "  --fail-fast       Stop after the first required failure",
    "  --dry-run         Show what would run without executing checks",
    "  --json            Emit machine-readable JSON",
    "  --help            Show this help output",
  ];
  console.log(helpText.join("\n"));
}

async function loadConfig(configPath) {
  const absolutePath = resolve(configPath);
  const raw = await readFile(absolutePath, "utf-8");
  const parsed = JSON.parse(raw);
  return CONFIG_SCHEMA.parse(parsed);
}

function selectChecks(checks, args) {
  const knownIds = new Set(checks.map((check) => check.id));
  const unknownOnly = [...args.only].filter((id) => !knownIds.has(id));
  const unknownSkip = [...args.skip].filter((id) => !knownIds.has(id));

  if (unknownOnly.length > 0) {
    throw new Error(`Unknown check id(s) for --only: ${unknownOnly.join(", ")}`);
  }

  if (unknownSkip.length > 0) {
    throw new Error(`Unknown check id(s) for --skip: ${unknownSkip.join(", ")}`);
  }

  const selected = checks.filter((check) => {
    if (args.only.size > 0) {
      return args.only.has(check.id) && !args.skip.has(check.id);
    }

    return check.enabled && !args.skip.has(check.id);
  });

  if (selected.length === 0) {
    throw new Error("No checks selected");
  }

  return selected;
}

async function pathExists(path) {
  try {
    await access(path, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function commandExists(command) {
  const pathValue = process.env.PATH ?? "";
  const pathEntries = pathValue
    .split(delimiter)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);

  const extensions =
    process.platform === "win32"
      ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT;.COM")
          .split(";")
          .filter((entry) => entry.length > 0)
      : [""];

  for (const entry of pathEntries) {
    for (const extension of extensions) {
      const candidate = process.platform === "win32" ? `${command}${extension}` : command;
      if (await pathExists(join(entry, candidate))) {
        return true;
      }
    }
  }

  return false;
}

async function collectMissingPrerequisites(check) {
  const cwd = resolve(check.workingDirectory);
  const missingFiles = [];
  const missingCommands = [];

  for (const file of check.prerequisiteFiles) {
    const fullPath = resolve(cwd, file);
    if (!(await pathExists(fullPath))) {
      missingFiles.push(file);
    }
  }

  for (const command of check.prerequisiteCommands) {
    if (!(await commandExists(command))) {
      missingCommands.push(command);
    }
  }

  return { missingFiles, missingCommands };
}

async function runFilesCheck(check) {
  const cwd = resolve(check.workingDirectory);
  const missingPaths = [];

  for (const relativePath of check.paths ?? []) {
    const fullPath = resolve(cwd, relativePath);
    if (!(await pathExists(fullPath))) {
      missingPaths.push(relativePath);
    }
  }

  return {
    status: missingPaths.length === 0 ? "passed" : "failed",
    durationMs: 0,
    details:
      missingPaths.length === 0
        ? `Verified ${String((check.paths ?? []).length)} path(s)`
        : `Missing path(s): ${missingPaths.join(", ")}`,
    exitCode: missingPaths.length === 0 ? 0 : 1,
    stdout: "",
    stderr: "",
  };
}

async function runCommandCheck(check) {
  const cwd = resolve(check.workingDirectory);
  const startedAt = Date.now();

  return await new Promise((resolveResult) => {
    let stdout = "";
    let stderr = "";
    let finished = false;
    let timedOut = false;

    const child = spawn(check.command, check.args, {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const timeoutId = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 5000).unref();
    }, check.timeoutMs);

    const finish = (result) => {
      if (finished) {
        return;
      }

      finished = true;
      clearTimeout(timeoutId);
      resolveResult(result);
    };

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", (error) => {
      finish({
        status: "failed",
        durationMs: Date.now() - startedAt,
        details: error.message,
        exitCode: 1,
        stdout,
        stderr,
      });
    });

    child.on("close", (code, signal) => {
      const durationMs = Date.now() - startedAt;
      const success = code === 0 && !timedOut;
      const details = timedOut
        ? `Timed out after ${String(check.timeoutMs)}ms`
        : signal !== null
          ? `Exited via signal ${signal}`
          : `Exited with code ${String(code ?? 1)}`;

      finish({
        status: success ? "passed" : "failed",
        durationMs,
        details,
        exitCode: success ? 0 : (code ?? 1),
        stdout,
        stderr,
      });
    });
  });
}

async function executeCheck(check, args) {
  const missing = await collectMissingPrerequisites(check);
  const missingPrerequisites = [
    ...missing.missingFiles.map((file) => `file:${file}`),
    ...missing.missingCommands.map((command) => `command:${command}`),
  ];

  if (missingPrerequisites.length > 0) {
    const status = check.missingPrerequisitePolicy === "skip" ? "skipped" : "failed";
    return {
      id: check.id,
      description: check.description,
      kind: check.kind,
      enabled: check.enabled,
      required: check.required,
      tags: check.tags,
      workingDirectory: check.workingDirectory,
      command: check.command ?? null,
      args: check.args,
      timeoutMs: check.timeoutMs,
      status,
      details: `Missing prerequisites: ${missingPrerequisites.join(", ")}`,
      missingPrerequisites,
      durationMs: 0,
      exitCode: status === "skipped" ? 0 : 1,
      stdout: "",
      stderr: "",
      dryRun: false,
    };
  }

  if (args.dryRun) {
    return {
      id: check.id,
      description: check.description,
      kind: check.kind,
      enabled: check.enabled,
      required: check.required,
      tags: check.tags,
      workingDirectory: check.workingDirectory,
      command: check.command ?? null,
      args: check.args,
      timeoutMs: check.timeoutMs,
      status: "dry-run",
      details:
        check.kind === "command"
          ? `Would run ${check.command} ${check.args.join(" ").trim()}`.trim()
          : `Would verify ${(check.paths ?? []).length} path(s)`,
      missingPrerequisites: [],
      durationMs: 0,
      exitCode: 0,
      stdout: "",
      stderr: "",
      dryRun: true,
    };
  }

  const result =
    check.kind === "command"
      ? await runCommandCheck(check)
      : await runFilesCheck(check);

  return {
    id: check.id,
    description: check.description,
    kind: check.kind,
    enabled: check.enabled,
    required: check.required,
    tags: check.tags,
    workingDirectory: check.workingDirectory,
    command: check.command ?? null,
    args: check.args,
    timeoutMs: check.timeoutMs,
    status: result.status,
    details: result.details,
    missingPrerequisites: [],
    durationMs: result.durationMs,
    exitCode: result.exitCode,
    stdout: result.stdout,
    stderr: result.stderr,
    dryRun: false,
  };
}

function summarize(results) {
  const summary = {
    selected: results.length,
    passed: 0,
    failedRequired: 0,
    failedOptional: 0,
    skipped: 0,
    dryRun: 0,
  };

  for (const result of results) {
    if (result.status === "passed") {
      summary.passed += 1;
      continue;
    }

    if (result.status === "failed") {
      if (result.required) {
        summary.failedRequired += 1;
      } else {
        summary.failedOptional += 1;
      }
      continue;
    }

    if (result.status === "skipped") {
      summary.skipped += 1;
      continue;
    }

    if (result.status === "dry-run") {
      summary.dryRun += 1;
    }
  }

  return summary;
}

function printList(checks) {
  for (const check of checks) {
    const fields = [
      check.id,
      check.enabled ? "enabled" : "disabled",
      check.required ? "required" : "optional",
      check.tags.join(","),
      check.description,
    ];
    console.log(fields.join(" | "));
  }
}

function printResults(results, summary) {
  for (const result of results) {
    const header = [
      STATUS_LABELS[result.status],
      result.id,
      result.required ? "(required)" : "(optional)",
      `- ${result.description}`,
    ].join(" ");

    console.log(header);
    console.log(`  ${result.details}`);

    if (result.command !== null) {
      const commandLine = [result.command, ...result.args].join(" ");
      console.log(`  command: ${commandLine}`);
    }

    if (result.durationMs > 0) {
      console.log(`  duration: ${String(result.durationMs)}ms`);
    }

    if (result.status === "failed") {
      const stdout = result.stdout.trim();
      const stderr = result.stderr.trim();

      if (stdout.length > 0) {
        console.log("  stdout:");
        console.log(indentBlock(stdout, 4));
      }

      if (stderr.length > 0) {
        console.log("  stderr:");
        console.log(indentBlock(stderr, 4));
      }
    }
  }

  console.log("");
  console.log(
    [
      `selected=${String(summary.selected)}`,
      `passed=${String(summary.passed)}`,
      `failed_required=${String(summary.failedRequired)}`,
      `failed_optional=${String(summary.failedOptional)}`,
      `skipped=${String(summary.skipped)}`,
      `dry_run=${String(summary.dryRun)}`,
    ].join(" "),
  );
}

function indentBlock(block, spaces) {
  const prefix = " ".repeat(spaces);
  return block
    .split("\n")
    .map((line) => `${prefix}${line}`)
    .join("\n");
}

async function main() {
  const startedAt = new Date().toISOString();
  const args = parseCliArgs(process.argv.slice(2));
  const config = await loadConfig(args.configPath);
  const selectedChecks = selectChecks(config.checks, args);

  if (args.list) {
    if (args.json) {
      console.log(
        JSON.stringify(
          {
            mode: "list",
            configPath: resolve(args.configPath),
            checks: selectedChecks,
          },
          null,
          2,
        ),
      );
      return;
    }

    printList(selectedChecks);
    return;
  }

  const results = [];

  for (const check of selectedChecks) {
    const result = await executeCheck(check, args);
    results.push(result);

    if (args.failFast && result.status === "failed" && result.required) {
      break;
    }
  }

  const summary = summarize(results);
  const finishedAt = new Date().toISOString();
  const exitCode = summary.failedRequired > 0 ? 1 : 0;

  if (args.json) {
    console.log(
      JSON.stringify(
        {
          mode: "run",
          configPath: resolve(args.configPath),
          startedAt,
          finishedAt,
          failFast: args.failFast,
          dryRun: args.dryRun,
          only: [...args.only],
          skip: [...args.skip],
          summary: {
            ...summary,
            exitCode,
          },
          results,
        },
        null,
        2,
      ),
    );
  } else {
    printResults(results, summary);
  }

  process.exitCode = exitCode;
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  if (process.argv.includes("--json")) {
    console.log(
      JSON.stringify(
        {
          mode: "error",
          error: message,
          exitCode: 2,
        },
        null,
        2,
      ),
    );
  } else {
    console.error(`audit error: ${message}`);
  }
  process.exitCode = 2;
});
