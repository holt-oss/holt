import { CatFace } from "@/components/cat-face";
import { PasteBox } from "@/components/paste-box";
import { PageTransition } from "@/components/motion/page-transition";

export default function NotFound() {
  return (
    <PageTransition>
      <div className="wrap max-w-2xl py-20">
        <CatFace mood="startled" className="text-[2rem]" />
        <h1 className="display mt-6 text-[2.4rem]">Nothing here.</h1>
        <p className="prose-sans mt-3">That page doesn&apos;t exist. Looking for a repository? Paste it below.</p>
        <div className="mt-8">
          <PasteBox size="md" />
        </div>
      </div>
    </PageTransition>
  );
}
