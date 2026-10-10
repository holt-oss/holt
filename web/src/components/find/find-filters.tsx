"use client";

import { useEffect, useId, useRef, useState } from "react";
import { extraCount, type Picks } from "@/lib/find-picks";
import { langColor } from "@/lib/repo-card";
import { CONTRIBUTIONS, LANGS, langName, LEVELS, MORE_LANGS, POPULAR_TOPICS, TIME, topics as topicsOf } from "@/lib/profile";
import { LangDot } from "../repo-card/repo-avatar";
import { SuggestInput } from "./suggest-input";

// Every choice is one tap and applies at once; the rare ones sit behind "more filters".
// Case, above the results: names and choices (tabs, labels, chips, options)
// start with a capital (GitHub topics keep their own lowercase spelling);
// actions (check, add, more filters, reset filters)
// are lowercase; notes and hints in brackets or after "·" run on in lowercase.
// On a phone the label and all four options share one line, so the options are short there; the words stay for screen readers.
const TIME_SHORT: Record<number, string> = { 1: "1d", 3: "3d", 7: "1w", 30: "1mo" };

// Controls are 40px tall on a phone and 32px from tablets up, so the bar that holds them stays thin.
// Typeface: names (languages, topics, kinds of work) are chips in the mono face, as on the cards;
// the phrases you read (how long, how experienced, the switch) are in the sans face.
const seg = "flex h-10 items-center justify-center whitespace-nowrap border px-2 font-sans text-[0.8rem] transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue sm:h-8 sm:px-3 sm:text-[0.84rem]";
const segOn = "picked";
const segOff = "border-line-strong text-muted hover:border-blue hover:text-ink";
const chipOn = "picked";
const chipOff = "border-line-strong text-muted hover:border-blue hover:text-ink";
// Languages you type in: any name GitHub knows (find-picks.ts keeps up to 10, each up to 40 characters).
const MAX_LANGS = 10;
const MAX_TOPICS = 10;
const KNOWN = new Set(LANGS.map((l) => l.toLowerCase()));
const chip = "inline-flex h-10 shrink-0 select-none items-center whitespace-nowrap border px-3 text-[0.8rem] transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue sm:h-8";

export function FindFilters({ picks, onChange, hf, busy = false }: {
  picks: Picks;
  onChange: (p: Picks) => void;
  hf: { note: string } | null;
  /** A search with these picks is on its way. */
  busy?: boolean;
}) {
  const extras = extraCount(picks);
  // The rare filters open under the bar, over the results; Escape or a tap elsewhere closes them.
  const [more, setMore] = useState(false);
  const tray = useRef<HTMLDivElement>(null);
  const moreButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!more) return;
    const away = (e: PointerEvent) => {
      if (e.target instanceof Node && !tray.current?.contains(e.target)) setMore(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [more]);
  const onTrayKey = (e: React.KeyboardEvent) => {
    // Not when Escape just closed a suggestion list (suggest-input.tsx).
    if (e.key !== "Escape" || !more || e.defaultPrevented) return;
    setMore(false);
    moreButton.current?.focus();
  };
  // Only what's being typed; the applied topics show as chips.
  const [topicText, setTopicText] = useState("");
  const panelId = useId();
  // The language row scrolls sideways: bring the first picked one into view once.
  const langRow = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = langRow.current;
    const on = row?.querySelector<HTMLElement>("[data-lang][aria-pressed=true]");
    if (row && on && row.scrollWidth > row.clientWidth) row.scrollLeft = on.offsetLeft - row.offsetLeft - 12;
  }, []);
  const set = (patch: Partial<Picks>) => onChange({ ...picks, ...patch });
  const toggle = <T,>(xs: T[], x: T) => (xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x]);
  const [langText, setLangText] = useState("");
  const custom = picks.langs.filter((l) => !KNOWN.has(l));
  const full = picks.langs.length >= MAX_LANGS;
  const addLangs = (text = langText) => {
    const typed = text.split(",").map((l) => l.trim().toLowerCase()).filter((l) => l && l.length <= 40);
    const langs = [...new Set([...picks.langs, ...typed])].slice(0, MAX_LANGS);
    setLangText("");
    if (langs.length !== picks.langs.length) set({ langs });
  };
  // Backspace in an empty box takes off the chip just before it, as tag boxes do.
  const onLangKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !langText && custom.length) set({ langs: picks.langs.filter((l) => l !== custom.at(-1)) });
  };
  const onTopicKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !topicText && picks.topics.length) set({ topics: picks.topics.slice(0, -1) });
  };
  const topicsFull = picks.topics.length >= MAX_TOPICS;
  const addTopics = (text = topicText) => {
    const t = topicsOf([...picks.topics, topicsOf(text)].join(","));
    setTopicText("");
    if (t.length !== picks.topics.length) set({ topics: t });
  };
  // The applied topics, each one tap to remove.
  const topicChips = picks.topics.map((t) => (
    <button key={t} type="button" aria-pressed="true" aria-label={`Topic ${t}, remove`} onClick={() => set({ topics: picks.topics.filter((x) => x !== t) })} className={`${chip} ${chipOn} gap-1.5`}>
      {t}
      <span aria-hidden="true" className="opacity-70">×</span>
    </button>
  ));

  const hfLabel = "Hacktoberfest only";

  return (
    <div ref={tray} className="find-tray" onKeyDown={onTrayKey}>
      {/* One row once the bar is wide enough for it; before that, languages over time. */}
      <div className="find-bar flex flex-wrap items-center gap-x-4 gap-y-1.5 py-1.5 @5xl:flex-nowrap">
        {/* Positioned, so the hidden label inside scrolls with the row instead of widening the page. */}
        <div ref={langRow} className="relative flex w-full min-w-0 gap-1.5 overflow-x-auto pr-6 [mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)] [scrollbar-width:none] @5xl:w-auto @5xl:flex-1">
          {/* Below one row there's no room beside Time, so the switch leads the chips. */}
          {hf && (
            <button type="button" role="switch" aria-checked={picks.hf} aria-label={hfLabel} onClick={() => set({ hf: !picks.hf })} className={`${chip} @5xl:hidden ${picks.hf ? "tint-hf picked" : chipOff}`}>
              Hacktoberfest
            </button>
          )}
          <div role="group" aria-label="Languages you can read" className="contents">
            <button type="button" aria-pressed={!picks.langs.length} onClick={() => set({ langs: [] })} className={`${chip} ${!picks.langs.length ? chipOn : chipOff}`}>
              Any language
            </button>
            {LANGS.map((l) => {
              const id = l.toLowerCase();
              const on = picks.langs.includes(id);
              return (
                <button key={id} type="button" data-lang aria-pressed={on} onClick={() => set({ langs: toggle(picks.langs, id) })} className={`${chip} ${on ? chipOn : chipOff} gap-2`}>
                  <LangDot color={langColor(l)} />
                  {l}
                </button>
              );
            })}
            {custom.map((id) => (
              <button key={id} type="button" data-lang aria-pressed="true" aria-label={`${langName(id)}, remove`} onClick={() => set({ langs: toggle(picks.langs, id) })} className={`${chip} ${chipOn} gap-2`}>
                <LangDot color={langColor(langName(id))} />
                {langName(id)}
                <span aria-hidden="true" className="opacity-70">×</span>
              </button>
            ))}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                addLangs();
              }}
              data-suggest-anchor
              className="flex h-10 w-40 shrink-0 items-center border border-line-strong bg-bg transition-colors focus-within:border-blue sm:h-8"
            >
              <label htmlFor={`${panelId}-lang`} className="sr-only">Add a language</label>
              <span aria-hidden="true" className="pl-2.5 text-[0.8rem] text-faint">+</span>
              <SuggestInput
                id={`${panelId}-lang`}
                type="text"
                value={langText}
                onChange={setLangText}
                onPick={addLangs}
                options={MORE_LANGS.filter((l) => !picks.langs.includes(l.toLowerCase()))}
                onKeyDown={onLangKey}
                placeholder={full ? "10 languages at most" : "add a language"}
                readOnly={full}
                maxLength={40}
                spellCheck={false}
                enterKeyHint="done"
                className="min-w-0 flex-1 bg-transparent px-1.5 text-[0.8rem] outline-none placeholder:text-faint read-only:cursor-not-allowed"
              />
              {langText.trim() && <button type="submit" className="self-stretch px-2.5 text-[0.8rem] text-muted hover:text-ink">add</button>}
            </form>
          </div>
        </div>

        <div className="flex w-full min-w-0 items-center gap-x-3 sm:gap-x-4 @5xl:w-auto @5xl:shrink-0">
          <span id={`${panelId}-time`} className="shrink-0 whitespace-nowrap font-sans text-[0.8rem] text-faint sm:text-[0.84rem]">Replies within</span>
          <div role="radiogroup" aria-labelledby={`${panelId}-time`} className="-ml-1 grid min-w-0 flex-1 grid-cols-4 sm:-ml-2 sm:flex sm:flex-none">
            {TIME.map((t, i) => {
              const on = picks.days === t.days;
              return (
                <button
                  key={t.days}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => set({ days: t.days })}
                  className={`${seg} ${on ? segOn : segOff} ${i ? "-ml-px" : ""} relative ${on ? "z-10" : ""}`}
                >
                  <span aria-hidden="true" className="sm:hidden">{TIME_SHORT[t.days]}</span>
                  <span className="max-sm:sr-only">{t.label}</span>
                </button>
              );
            })}
          </div>

          {hf && (
            <button type="button" role="switch" aria-checked={picks.hf} onClick={() => set({ hf: !picks.hf })} className={`group hidden h-8 shrink-0 items-center gap-2 text-left font-sans text-[0.84rem] @5xl:flex ${picks.hf ? "font-semibold" : "text-muted hover:text-ink"}`}>
              <span
                aria-hidden="true"
                className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors after:absolute after:left-0.5 after:top-0.5 after:size-3.5 after:rounded-full after:transition-transform group-focus-visible:outline-2 group-focus-visible:outline-blue ${picks.hf ? "tint-hf border-sel bg-sel-bg after:translate-x-4 after:bg-sel" : "border-line-strong bg-panel-2 after:bg-faint"}`}
              />
              <span>
                {hfLabel} <span className="hidden font-normal text-faint @7xl:inline">· {hf.note}</span>
              </span>
            </button>
          )}

          <button
            ref={moreButton}
            type="button"
            aria-expanded={more}
            aria-controls={panelId}
            onClick={() => setMore(!more)}
            className="ml-auto flex h-10 shrink-0 items-center gap-1.5 text-[0.8rem] text-muted hover:text-ink sm:h-8"
          >
            {/* Lit while a search with the new picks is on its way; its room is always kept, so nothing shifts. */}
            <span aria-hidden="true" className={`size-1.5 rounded-full bg-blue ${busy ? "animate-pulse" : "invisible"}`} />
            <span className="max-sm:hidden">more</span> filters{extras > 0 && <span className="rounded-full bg-blue px-1.5 text-[0.72rem] text-on-accent">{extras}</span>}
            <span aria-hidden="true" className={`transition-transform ${more ? "rotate-180" : ""}`}>▾</span>
          </button>
        </div>
      </div>

      {more && (
        <div id={panelId} className="find-more grid gap-5 py-3 sm:grid-cols-[auto_1fr] sm:gap-x-8 sm:py-4 lg:grid-cols-[auto_minmax(0,1fr)_minmax(16rem,24rem)]">
          <div role="radiogroup" aria-label="Your experience">
            <p className="mb-2 text-[0.82rem] text-faint">Your experience</p>
            <div className="flex">
              {LEVELS.map((l, i) => {
                const on = picks.level === l.id;
                return (
                  <button key={l.id} type="button" role="radio" aria-checked={on} title={l.hint} onClick={() => set({ level: l.id })} className={`${seg} ${on ? segOn : segOff} ${i ? "-ml-px" : ""} relative flex-1 ${on ? "z-10" : ""}`}>
                    {l.label}
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 font-sans text-[0.82rem] text-faint">{LEVELS.find((l) => l.id === picks.level)?.hint}</p>
          </div>
          <div role="group" aria-label="What you'd like to work on">
            <p className="mb-2 text-[0.82rem] text-faint">Work on <span className="font-sans">(these issues come first)</span></p>
            <div className="flex flex-wrap gap-2">
              {CONTRIBUTIONS.map((c) => {
                const on = picks.types.includes(c.id);
                return (
                  <button key={c.id} type="button" aria-pressed={on} onClick={() => set({ types: toggle(picks.types, c.id) })} className={`${chip} ${on ? chipOn : chipOff}`}>
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>
          <form
            className="sm:col-span-2 lg:col-span-1"
            onSubmit={(e) => {
              e.preventDefault();
              addTopics();
            }}
          >
            <label htmlFor={`${panelId}-topics`} className="mb-2 block text-[0.82rem] text-faint">
              Topics <span className="font-sans">(GitHub topics, separated by commas)</span>
            </label>
            <div className="flex gap-2">
              <SuggestInput
                id={`${panelId}-topics`}
                type="text"
                value={topicText}
                onChange={setTopicText}
                onPick={addTopics}
                options={POPULAR_TOPICS.filter((t) => !picks.topics.includes(t))}
                onBlur={() => topicText.trim() && addTopics()}
                onKeyDown={onTopicKey}
                placeholder={topicsFull ? "10 topics at most" : "e.g. web, cli, machine-learning"}
                readOnly={topicsFull}
                maxLength={300}
                enterKeyHint="search"
                className="h-10 min-w-0 flex-1 border border-line-strong bg-bg px-3 text-[0.82rem] outline-none focus-visible:border-blue read-only:cursor-not-allowed sm:h-8"
              />
              <button type="submit" disabled={topicsFull} className="btn-ghost h-10 min-h-0 text-[0.82rem] sm:h-8">add</button>
            </div>
            {topicChips.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{topicChips}</div>}
          </form>
        </div>
      )}
    </div>
  );
}
