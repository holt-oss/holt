// The parts every settings section is made of. The lit tab names the section,
// so its heading is for screen readers; a line under the tabs only when it
// adds a fact. Inside, each block is the app's section head (a heading, a
// faint note, one quiet link) over rows.
import Link from "next/link";
import { section, type SectionId } from "@/lib/settings";

export function SectionHead({ id, children }: { id: SectionId; children?: React.ReactNode }) {
  const s = section(id);
  return (
    <div className={children ? "mb-8" : undefined}>
      <h2 id={`${s.id}-h`} className="sr-only">{s.title}</h2>
      {children && <div className="prose-sans max-w-2xl text-[0.95rem] text-muted">{children}</div>}
    </div>
  );
}

/** One block in a section: `.section-head` over its rows. */
export function Block({ id, title, note, more, className = "", children }: {
  id?: string;
  title: string;
  note?: React.ReactNode;
  more?: { href: string; label: string };
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} aria-label={title} className={`scroll-mt-24 ${className}`}>
      <div className="section-head">
        <h3>{title}</h3>
        <span className="flex flex-wrap items-baseline gap-x-4 text-[0.82rem]">
          {note && <span className="text-faint">{note}</span>}
          {more && <Link href={more.href} className="inline-flex min-h-11 items-center text-blue hover:underline sm:min-h-0">{more.label}</Link>}
        </span>
      </div>
      {children}
    </section>
  );
}

/** A notice after a form: ink when it worked, orange when it did not, or plain. */
export function Notice({ tone, children }: { tone: "good" | "bad" | "plain"; children: React.ReactNode }) {
  const cls =
    tone === "good" ? "text-ink border-line-strong bg-ink/5"
    : tone === "bad" ? "text-orange border-orange/50 bg-orange/10"
    : "text-muted border-line-strong";
  return <p role="status" className={`mb-6 border px-4 py-3 font-sans text-[0.9rem] ${cls}`}>{children}</p>;
}
