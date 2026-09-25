import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { deleteByok, me, putByok } from "@/lib/api";
import { CancelPlan } from "@/components/billing/cancel-plan";
import { shortDate } from "@/lib/format";
import { currentUser } from "@/lib/session";
import type { ByokProvider } from "@/lib/types";

export const metadata: Metadata = { title: "Settings", robots: { index: false } };

const PROVIDERS: { id: ByokProvider; name: string; model: string; keyHint: string; url: string }[] = [
  { id: "openrouter", name: "OpenRouter", model: "anthropic/claude-sonnet-5", keyHint: "sk-or-…", url: "https://openrouter.ai/keys" },
  { id: "anthropic", name: "Anthropic", model: "claude-sonnet-5", keyHint: "sk-ant-…", url: "https://console.anthropic.com/settings/keys" },
  { id: "openai", name: "OpenAI", model: "gpt-5-mini", keyHint: "sk-…", url: "https://platform.openai.com/api-keys" },
  { id: "gemini", name: "Google Gemini", model: "gemini-2.5-flash", keyHint: "AIza…", url: "https://aistudio.google.com/apikey" },
];

async function saveKey(form: FormData) {
  "use server";
  const user = await currentUser();
  if (!user) redirect("/signin?callbackUrl=/settings");
  const provider = String(form.get("provider")) as ByokProvider;
  const apiKey = String(form.get("api_key") || "").trim();
  const p = PROVIDERS.find((x) => x.id === provider);
  if (!p || apiKey.length < 8) redirect("/settings?error=key");
  const model = String(form.get("model") || "").trim() || p.model;
  const r = await putByok(user.id, provider, apiKey, model);
  revalidatePath("/settings");
  redirect(r.ok ? "/settings?saved=1" : "/settings?error=save");
}

async function removeKey() {
  "use server";
  const user = await currentUser();
  if (!user) redirect("/signin?callbackUrl=/settings");
  await deleteByok(user.id);
  revalidatePath("/settings");
  redirect("/settings?removed=1");
}

export default async function SettingsPage({ searchParams }: PageProps<"/settings">) {
  const user = await currentUser();
  if (!user) redirect("/signin?callbackUrl=/settings");
  const sp = await searchParams;
  const account = await me(user.id);
  const m = account.ok ? account.data : null;
  const byok = m?.byok?.set ? m.byok : null;
  const current = PROVIDERS.find((p) => p.id === byok?.provider);

  const notice =
    sp.saved ? { tone: "text-green border-green/50 bg-green/10", text: "Key saved. It's encrypted and we'll never show it again." }
    : sp.removed ? { tone: "text-muted border-line-strong", text: "Key removed." }
    : sp.error === "key" ? { tone: "text-orange border-orange/50 bg-orange/10", text: "That key looks too short. Paste the whole key." }
    : sp.error ? { tone: "text-orange border-orange/50 bg-orange/10", text: "We couldn't save the key. Try again in a minute." }
    : null;

  return (
    <div className="wrap max-w-3xl py-10 sm:py-14">
      <p className="rail mb-4 flex gap-2"><strong className="m-0">settings</strong><span>{user.name || user.email}</span></p>
      <h1 className="display text-[clamp(2rem,6vw,3rem)]">Your AI reports</h1>

      {notice && <p role="status" className={`mt-6 border px-4 py-3 font-sans text-[0.9rem] ${notice.tone}`}>{notice.text}</p>}
      {!account.ok && <p role="alert" className="mt-6 border border-orange/50 px-4 py-3 font-sans text-[0.9rem] text-orange">{account.error.message}</p>}

      {m && (
        <section aria-labelledby="plan" className="mt-8 border border-line-strong bg-panel" data-plan-card>
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line p-5 sm:p-6">
            <div>
              <p className="text-[0.72rem] uppercase tracking-[0.08em] text-faint">Your plan</p>
              <h2 id="plan" className="mt-1 text-[1.6rem] font-semibold tracking-tight">{m.plan_name}</h2>
              <p className="mt-1 text-[0.82rem] text-muted">
                {m.renews_at
                  ? `Renews ${shortDate(m.renews_at)}. Cancel anytime; you keep access until the period ends.`
                  : m.ends_at
                    ? `Cancelled. You keep ${m.plan_name} until ${shortDate(m.ends_at)}, then move to Free.`
                    : "Free forever. Upgrade only if you want AI reports without your own key."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {m.renews_at && <CancelPlan planName={m.plan_name} until={shortDate(m.renews_at)} />}
              <Link href="/pricing" className="btn-ghost">{m.plan === "free" ? "see plans" : "plans & packs"}</Link>
            </div>
          </div>
          <div className="grid gap-px bg-line sm:grid-cols-2">
            <div className="bg-panel p-5 sm:p-6">
              <p className="text-[0.72rem] uppercase tracking-[0.08em] text-faint">AI reports this {m.plan === "free" ? "month" : "billing period"}</p>
              <p className="mt-1 text-[1.3rem] font-semibold">
                {m.quota.ai_used} <span className="text-[0.9rem] font-normal text-muted">of {m.quota.ai_limit} used</span>
              </p>
              <div className="meter mt-2" aria-hidden="true">
                <span className="bg-blue" style={{ width: `${m.quota.ai_limit ? Math.min(100, (m.quota.ai_used / m.quota.ai_limit) * 100) : 0}%` }} />
              </div>
              <p className="mt-2 text-[0.75rem] text-faint">Resets {shortDate(m.quota.resets_at)}</p>
            </div>
            <div className="bg-panel p-5 sm:p-6">
              <p className="text-[0.72rem] uppercase tracking-[0.08em] text-faint">Pack credits</p>
              <p className="mt-1 text-[1.3rem] font-semibold">{m.pack_credits}</p>
              <p className="mt-2 text-[0.75rem] text-faint">Never expire. Used after your monthly allowance.</p>
            </div>
          </div>
        </section>
      )}

      <section id="byok" aria-labelledby="byok-title" className="mt-10 scroll-mt-24 border border-line-strong bg-panel p-5 sm:p-8">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="byok-title" className="text-[1.3rem] font-semibold tracking-tight">Bring your own key</h2>
          <span className="chip border-green/60 text-green">free, unlimited</span>
        </div>
        <p className="prose-sans mt-2 text-[0.95rem]">
          Use your own model provider for unlimited AI reports. Always free on Holt; you pay your provider directly
          (a report is usually well under $0.05). Keys are encrypted at rest and never shown again, not even to you.
        </p>

        {byok && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border border-green/50 bg-green/10 p-4">
            <div className="text-[0.85rem]">
              <p className="text-green">● key saved for {current?.name ?? byok.provider}</p>
              <p className="mt-1 text-muted">model: <code className="text-ink">{byok.model}</code> · key: <span aria-label="hidden">••••••••••••</span></p>
            </div>
            <form action={removeKey}>
              <button type="submit" className="btn-ghost text-orange">remove key</button>
            </form>
          </div>
        )}

        <form action={saveKey} className="mt-6 space-y-5">
          <fieldset>
            <legend className="mb-2 text-[0.78rem] uppercase tracking-[0.08em] text-faint">Provider</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PROVIDERS.map((p) => (
                <label key={p.id} className="flex min-h-12 cursor-pointer items-center justify-center border border-line-strong px-2 text-center text-[0.82rem] transition-colors hover:border-blue has-[:checked]:border-blue has-[:checked]:bg-blue/10 has-[:checked]:text-blue has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blue">
                  <input type="radio" name="provider" value={p.id} required defaultChecked={(byok?.provider ?? "openrouter") === p.id} className="sr-only" />
                  {p.name}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="api_key" className="mb-2 block text-[0.78rem] uppercase tracking-[0.08em] text-faint">API key</label>
            <input
              id="api_key"
              name="api_key"
              type="password"
              required
              minLength={8}
              autoComplete="off"
              spellCheck={false}
              placeholder={byok ? "paste a new key to replace the saved one" : "sk-…"}
              className="h-12 w-full border border-line-strong bg-bg px-3 text-[0.9rem] outline-none focus:border-blue"
            />
            <p className="mt-1.5 font-sans text-[0.8rem] text-faint">
              Get one from{" "}
              {PROVIDERS.map((p, i) => (
                <span key={p.id}>
                  <a className="text-link" href={p.url} target="_blank" rel="noopener noreferrer">{p.name}</a>
                  {i < PROVIDERS.length - 1 ? ", " : "."}
                </span>
              ))}
            </p>
          </div>
          <div>
            <label htmlFor="model" className="mb-2 block text-[0.78rem] uppercase tracking-[0.08em] text-faint">Model <span className="normal-case tracking-normal">(optional)</span></label>
            <input
              id="model"
              name="model"
              list="models"
              defaultValue={byok?.model ?? ""}
              placeholder="leave empty for a good default"
              autoComplete="off"
              spellCheck={false}
              className="h-12 w-full border border-line-strong bg-bg px-3 text-[0.9rem] outline-none focus:border-blue"
            />
            <datalist id="models">
              {PROVIDERS.map((p) => <option key={p.id} value={p.model} />)}
            </datalist>
          </div>
          <button type="submit" className="btn-primary">{byok ? "replace key" : "save key"}</button>
        </form>
      </section>
    </div>
  );
}
