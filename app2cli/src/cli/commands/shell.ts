import { createInterface } from "node:readline";
import { Command } from "commander";
import { cliState } from "../state.js";

/**
 * Interactive shell — runs a REPL that keeps the session alive
 * so multi-command workflows (open -> inspect -> query -> click) work.
 *
 * Uses a sequential question loop (not rl.on("line")) so that
 * subcommands like browse can reuse the same readline without conflict.
 */
export function createShellCommand(program: Command): Command {
  return new Command("shell")
    .description("Start an interactive session (keeps the session alive between commands)")
    .action(async () => {
      const rl = createInterface({
        input: process.stdin,
        output: process.stdout,
      });

      // Share the readline with subcommands (browse, etc.)
      cliState.setReadline(rl);

      process.stdout.write(
        "Interactive mode. Type commands without 'app2cli' prefix.\n" +
        "Example: web open https://example.com\n" +
        "Type 'exit' or Ctrl+D to quit.\n\n",
      );

      const question = (msg: string): Promise<string> =>
        new Promise((resolve) => {
          rl.question(msg, resolve);
        });

      let running = true;

      rl.on("close", () => {
        running = false;
      });

      // Sequential question loop — only one readline consumer at a time
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
      while (running) {
        let line: string;
        try {
          line = await question("app2cli> ");
        } catch {
          break;
        }

        const trimmed = line.trim();
        if (trimmed === "exit" || trimmed === "quit") {
          break;
        }
        if (trimmed === "") continue;

        // Parse and execute the command within the same process
        const args = splitArgs(trimmed);
        const cloned = createFreshProgram(program);
        cloned.exitOverride();

        try {
          await cloned.parseAsync(["node", "app2cli", ...args]);
        } catch (err) {
          if (err instanceof Error && err.message !== "(outputHelp)") {
            process.stderr.write(`error: ${err.message}\n`);
          }
        }
      }

      await cliState.cleanup();
      rl.close();
      process.stdout.write("\n");
    });
}

/**
 * Clone the program's command structure for re-parsing within the REPL.
 */
function createFreshProgram(source: Command): Command {
  const clone = new Command();
  clone.name("app2cli");

  for (const cmd of source.commands) {
    clone.addCommand(cmd);
  }

  return clone;
}

/**
 * Split a command line string into arguments, respecting quotes.
 */
function splitArgs(input: string): string[] {
  const args: string[] = [];
  let current = "";
  let inQuote: string | null = null;

  for (const ch of input) {
    if (inQuote !== null) {
      if (ch === inQuote) {
        inQuote = null;
      } else {
        current += ch;
      }
    } else if (ch === '"' || ch === "'") {
      inQuote = ch;
    } else if (ch === " " || ch === "\t") {
      if (current.length > 0) {
        args.push(current);
        current = "";
      }
    } else {
      current += ch;
    }
  }

  if (current.length > 0) {
    args.push(current);
  }

  return args;
}
