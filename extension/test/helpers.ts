import type { Report } from "../src/types";

/** Trimmed-down markup of GitHub's repo header, current (2025–26) layout. */
export function repoHeader(owner = "pallets", repo = "flask"): string {
  return `
    <div id="repository-container-header">
      <div id="repo-title-component" class="d-flex flex-items-center">
        <img alt="" class="avatar" src="" />
        <strong itemprop="name" class="mr-1"><a href="/${owner}/${repo}">${repo}</a></strong>
        <span class="Label">Public</span>
      </div>
    </div>`;
}

/** Older layout without #repo-title-component. */
export function legacyRepoHeader(owner = "pallets", repo = "flask"): string {
  return `
    <div id="repository-container-header">
      <h1>
        <span class="author"><a href="/${owner}">${owner}</a></span> /
        <strong itemprop="name"><a href="/${owner}/${repo}">${repo}</a></strong>
      </h1>
    </div>`;
}

export function report(over: Partial<Report> = {}): Report {
  return {
    repo: "pallets/flask",
    verdict: "viable",
    headline: "Worth your time",
    stats: { outsider_attempts: 100, outsider_merged: 15 },
    ...over,
  };
}
