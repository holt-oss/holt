// The profile form: the same questions in settings and in the onboarding card.
// Every question changes what /find and /hacktoberfest show (lib/profile.ts).
import { save } from "@/app/profile/actions";
import { ProfileLangs } from "@/components/profile-langs";
import { CONTRIBUTIONS, LEVELS, TIME } from "@/lib/profile";
import type { ProfilePrefs } from "@/lib/types";

const CHIP =
  "chip min-h-11 cursor-pointer select-none px-3.5 text-[0.82rem] transition-colors sm:min-h-9 hover:border-blue has-[:checked]:picked has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blue";
const BOX =
  "flex min-h-11 cursor-pointer items-center justify-center border border-line-strong px-3 text-center text-[0.84rem] transition-colors hover:border-blue has-[:checked]:picked has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blue";
const LEGEND = "mb-2.5 text-[0.78rem] uppercase tracking-[0.08em] text-faint";

export function ProfileForm({
  prefs,
  adultConfirmed,
  back,
  submitLabel = "save my profile",
  children,
}: {
  prefs: ProfilePrefs | null;
  adultConfirmed: boolean;
  back: string;
  submitLabel?: string;
  /** Extra buttons next to save (the card's "skip"). */
  children?: React.ReactNode;
}) {
  const days = prefs?.days ?? 7;
  const level = prefs?.level ?? "newcomer";
  const types = new Set(prefs?.contributions ?? []);

  return (
    <form action={save} className="space-y-6">
      <input type="hidden" name="back" value={back} />
      <fieldset>
        <legend className={LEGEND}>Languages you can read</legend>
        <ProfileLangs saved={prefs?.languages ?? []} chip={CHIP} />
      </fieldset>

      <fieldset>
        <legend className={LEGEND}>How long you&apos;d wait for a first reply</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {TIME.map((t) => (
            <label key={t.days} className={BOX}>
              <input type="radio" name="days" value={t.days} defaultChecked={days === t.days} className="sr-only" />
              {t.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className={LEGEND}>What you&apos;d like to work on</legend>
        <div className="flex flex-wrap gap-2">
          {CONTRIBUTIONS.map((c) => (
            <label key={c.id} className={CHIP}>
              <input type="checkbox" name="type" value={c.id} defaultChecked={types.has(c.id)} className="sr-only" />
              {c.label}
            </label>
          ))}
        </div>
        <p className="mt-2 font-sans text-[0.88rem] text-faint">Issues like these come first. Pick none for no preference.</p>
      </fieldset>

      <fieldset>
        <legend className={LEGEND}>Your experience</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {LEVELS.map((l) => (
            <label key={l.id} className={`${BOX} group flex-col !items-start gap-1 py-3 text-left`}>
              <input type="radio" name="level" value={l.id} defaultChecked={level === l.id} className="sr-only" />
              <span className="font-semibold">{l.label}</span>
              {/* On the selected card the hint takes the card's text colour: muted grey on green can't be read. */}
              <span className="font-sans text-[0.8rem] font-normal text-muted group-has-[:checked]:text-on-accent">{l.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block">
        <span className={`block ${LEGEND}`}>Topics you care about <span className="normal-case tracking-normal">(optional)</span></span>
        <input
          type="text"
          name="topics"
          defaultValue={(prefs?.topics ?? []).join(", ")}
          placeholder="e.g. web, cli, machine-learning"
          maxLength={300}
          className="min-h-11 w-full border border-line-strong bg-bg px-3 font-sans text-[0.95rem] outline-none focus-visible:border-blue"
        />
        <span className="mt-2 block font-sans text-[0.88rem] text-faint">GitHub topics, comma-separated. Each one narrows the search a lot. Leave it empty to see more.</span>
      </label>

      {!adultConfirmed && (
        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[0.95rem]">
          <input type="checkbox" name="adult" required className="mt-1 size-4 accent-blue" />
          <span>
            <strong>I&apos;m 18 or older</strong>
            <span className="block text-[0.89rem] text-muted">Profiles are for adults. Everything else on Holt works without one.</span>
          </span>
        </label>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" className="btn-primary">{submitLabel}</button>
        {children}
      </div>
    </form>
  );
}
