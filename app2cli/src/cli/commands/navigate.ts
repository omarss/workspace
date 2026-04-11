import { Command } from "commander";
import { cliState } from "../state.js";

export function createNavigateCommand(): Command {
  return new Command("navigate")
    .alias("goto")
    .alias("nav")
    .description("Navigate to a URL in the current session")
    .argument("<url>", "URL to navigate to")
    .action(async (url: string) => {
      const adapter = cliState.getAdapter();

      if (adapter.navigate === undefined) {
        throw new Error("Navigate is not supported on this adapter");
      }

      await adapter.navigate(url);

      const nodes = await adapter.getNodes();
      cliState.setNodes(nodes);
      const screen = await adapter.getScreen();

      process.stdout.write(
        `navigated: ${screen.url ?? url}\ntitle: ${screen.title}\nnodes: ${String(nodes.length)}\n`,
      );
    });
}
