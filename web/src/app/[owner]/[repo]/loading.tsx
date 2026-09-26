import { LoadingTransition } from "@/components/motion/page-transition";
import { ReportSkeleton } from "@/components/report/report-skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <ReportSkeleton />
    </LoadingTransition>
  );
}
