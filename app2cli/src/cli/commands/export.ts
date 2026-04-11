import { Command } from "commander";
import { cliState } from "../state.js";
import { formatSnapshotJson } from "../output.js";

export function createExportCommand(): Command {
  return new Command("export")
    .description("Export the current snapshot")
    .option("--format <fmt>", "Output format: json", "json")
    .action((opts: ExportOptions) => {
      const snapshot = cliState.getSnapshot();
      if (snapshot === null) {
        throw new Error(
          "No snapshot available. Run 'app2cli inspect' first.",
        );
      }

      switch (opts.format) {
        case "json":
          process.stdout.write(formatSnapshotJson(snapshot) + "\n");
          break;
        default:
          process.stdout.write(formatSnapshotJson(snapshot) + "\n");
          break;
      }
    });
}

interface ExportOptions {
  format: string;
}
