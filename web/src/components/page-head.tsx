// The top band every inner page shares with the landing hero: the same dot
// grid and glow (static gradients), and a rule underneath.
export function PageHead({ children, narrow = false, className = "" }: { children: React.ReactNode; narrow?: boolean; className?: string }) {
  return (
    <section className={`relative overflow-hidden border-b border-line ${className}`}>
      <div aria-hidden="true" className="hero-backdrop" />
      <div className={`wrap relative py-10 sm:py-14 ${narrow ? "max-w-3xl" : ""}`}>{children}</div>
    </section>
  );
}
