import { Command } from "commander";
import { listIntentNames, resolveIntent } from "../../core/intents/index.js";
import { cliState } from "../state.js";

export function createIntentsCommand(): Command {
  const cmd = new Command("intents").description(
    "List or resolve intent shortcuts (login, dismiss, search, etc.)",
  );

  cmd
    .command("list")
    .description("List all available intent shortcuts")
    .action(() => {
      const names = listIntentNames();
      for (const name of names) {
        process.stdout.write(`  ${name}\n`);
      }
    });

  cmd
    .command("resolve")
    .description("Resolve an intent against the current screen")
    .argument("<intent>", "Intent name (e.g. login, dismiss, search)")
    .action((intentName: string) => {
      const nodes = cliState.getNodes();
      if (nodes.length === 0) {
        throw new Error("No nodes available. Run 'app2cli inspect' first.");
      }

      const match = resolveIntent(intentName, nodes);
      if (match === null) {
        process.stderr.write(`intent "${intentName}" does not apply to the current screen\n`);
        process.exitCode = 1;
        return;
      }

      process.stdout.write(
        [
          `intent: ${match.intentName}`,
          `node: ${match.node.id}`,
          `score: ${match.score.toFixed(2)}`,
          `action: ${match.action}`,
          `reason: ${match.reason}`,
        ].join("\n") + "\n",
      );
    });

  return cmd;
}
