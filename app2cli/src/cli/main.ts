#!/usr/bin/env node

import { Command } from "commander";
import {
  createClickCommand,
  createScreenshotCommand,
  createTypeCommand,
} from "./commands/action.js";
import { createAndroidCommand } from "./commands/android.js";
import { createBrowseCommand } from "./commands/browse.js";
import { createExportCommand } from "./commands/export.js";
import { createInspectCommand } from "./commands/inspect.js";
import { createIntentsCommand } from "./commands/intents.js";
import { createNavigateCommand } from "./commands/navigate.js";
import { createQueryCommand } from "./commands/query.js";
import { createSessionCommand } from "./commands/session.js";
import { createShellCommand } from "./commands/shell.js";
import { createWebCommand } from "./commands/web.js";
import { cliState } from "./state.js";

const program = new Command();

program
  .name("app2cli")
  .description(
    "Convert live web apps and Android APKs into structured, machine-readable UI representations.\n\n" +
    "For multi-command workflows, use 'app2cli shell' to start an interactive session.",
  )
  .version("0.1.0");

// Platform commands
program.addCommand(createWebCommand());
program.addCommand(createAndroidCommand());

// Inspection and query
program.addCommand(createInspectCommand());
program.addCommand(createQueryCommand());

// Actions
program.addCommand(createClickCommand());
program.addCommand(createTypeCommand());
program.addCommand(createScreenshotCommand());
program.addCommand(createNavigateCommand());

// Interactive browsing
program.addCommand(createBrowseCommand());

// Intents
program.addCommand(createIntentsCommand());

// Session management
program.addCommand(createSessionCommand());

// Export
program.addCommand(createExportCommand());

// Interactive shell (keeps session alive across commands)
program.addCommand(createShellCommand(program));

// Cleanup on exit
process.on("beforeExit", () => {
  void cliState.cleanup();
});

program.parse();
