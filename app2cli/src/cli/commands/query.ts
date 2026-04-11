import { Command } from "commander";
import { classifyConfidence } from "../../core/confidence.js";
import { parsePositiveInt } from "../validate.js";
import { queryBestMatch, queryNodes } from "../../core/query/index.js";
import { cliState } from "../state.js";
import { formatQueryResults } from "../output.js";

export function createQueryCommand(): Command {
  return new Command("query")
    .description("Query UI nodes using natural-language selectors")
    .argument("<selector>", "Selector string (e.g. 'button named sign in')")
    .option("--id-only", "Output only the matched node ID")
    .option("--all", "Show all matches instead of just the best")
    .option("--limit <n>", "Maximum number of results", "5")
    .action((selector: string, opts: QueryOptions) => {
      const nodes = cliState.getNodes();
      if (nodes.length === 0) {
        throw new Error(
          "No nodes available. Run 'app2cli inspect' first.",
        );
      }

      if (opts.idOnly === true) {
        const best = queryBestMatch(nodes, selector);
        if (best === null) {
          process.exitCode = 1;
          process.stderr.write("no match found\n");
          return;
        }

        // Warn if match confidence is low
        const level = classifyConfidence(best.score);
        if (level === "ambiguous") {
          process.stderr.write(
            `warning: match confidence ${best.score.toFixed(2)} is ambiguous (below 0.85)\n`,
          );
        }

        process.stdout.write(best.node.id + "\n");
        return;
      }

      const allMatches = queryNodes(nodes, selector);
      const limit = opts.all === true ? allMatches.length : parsePositiveInt(opts.limit, "--limit");
      const results = allMatches.slice(0, limit);

      process.stdout.write(formatQueryResults(results) + "\n");
    });
}

interface QueryOptions {
  idOnly?: boolean;
  all?: boolean;
  limit: string;
}
