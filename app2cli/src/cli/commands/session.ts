import { Command } from "commander";
import { SessionStore } from "../../core/session-store.js";
import { parsePositiveInt } from "../validate.js";

export function createSessionCommand(): Command {
  const cmd = new Command("session").description("Manage sessions");

  cmd
    .command("list")
    .description("List all sessions")
    .option("--active", "Show only active sessions")
    .action(async (opts: { active?: boolean }) => {
      const store = new SessionStore();
      const sessions = await store.list(opts.active === true);

      if (sessions.length === 0) {
        process.stdout.write("no sessions found\n");
        return;
      }

      for (const s of sessions) {
        const status = s.active ? "active" : "inactive";
        const expired = store.isExpired(s) ? " (expired)" : "";
        process.stdout.write(
          `${s.id}  ${s.platform.padEnd(8)}  ${status}${expired}  ${s.target}\n`,
        );
      }
    });

  cmd
    .command("cleanup")
    .description("Deactivate expired sessions and optionally purge old ones")
    .option("--purge-days <n>", "Delete sessions older than N days")
    .action(async (opts: { purgeDays?: string }) => {
      const store = new SessionStore();
      const expired = await store.cleanupExpired();
      process.stdout.write(`deactivated ${String(expired)} expired session(s)\n`);

      if (opts.purgeDays !== undefined) {
        const days = parsePositiveInt(opts.purgeDays, "--purge-days");
        const purged = await store.purgeOlderThan(days * 24 * 60 * 60 * 1000);
        process.stdout.write(`purged ${String(purged)} session(s) older than ${String(days)} day(s)\n`);
      }
    });

  cmd
    .command("delete")
    .description("Delete a specific session")
    .argument("<session-id>", "Session ID to delete")
    .action(async (sessionId: string) => {
      const store = new SessionStore();
      await store.delete(sessionId);
      process.stdout.write(`deleted: ${sessionId}\n`);
    });

  return cmd;
}
