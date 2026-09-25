// Friendly progress copy. Server stage strings are plain English already;
// these add a line of context for someone waiting on a phone.
const FRIENDLY: [RegExp, string, string][] = [
  [/queue/i, "Getting in line", "Someone else's report is running. Yours is next."],
  [/fetch|pull request/i, "Fetching pull requests", "Reading the last few months of pull requests from people outside the project."],
  [/thread|read/i, "Reading threads", "Who replied, how fast, and what happened to each pull request."],
  [/check|verif|evidence/i, "Checking evidence", "Every claim has to link to a real GitHub page, or it's dropped."],
  [/writ|report|verdict/i, "Writing the report", "Applying the same fixed rules to every repository."],
];

export function friendlyStage(stage: string | undefined): { title: string; detail: string } {
  if (!stage) return { title: "Starting", detail: "Warming up." };
  for (const [re, title, detail] of FRIENDLY) if (re.test(stage)) return { title, detail };
  return { title: stage, detail: "" };
}

export const STAGE_ORDER = ["Fetching pull requests", "Reading threads", "Checking evidence", "Writing the report"];
