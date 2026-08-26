import { JobStatus } from "../api";

const STEPS: JobStatus[] = [
  "pending",
  "discovering",
  "vision",
  "generating",
  "selecting",
  "validating",
  "executing",
  "judging",
  "advancing",
  "finalizing",
  "completed",
];

const FAILED_STATUSES: JobStatus[] = ["failed", "circuit_broken", "cancelled"];

export default function StatusTimeline({ status }: { status: JobStatus }) {
  if (FAILED_STATUSES.includes(status)) {
    return (
      <div className="timeline">
        {STEPS.map((step) => (
          <span key={step} className="timeline-step done">
            {step}
          </span>
        ))}
        <span className="timeline-step failed">{status}</span>
      </div>
    );
  }

  const currentIndex = STEPS.indexOf(status);

  return (
    <div className="timeline">
      {STEPS.map((step, index) => (
        <span
          key={step}
          className={
            "timeline-step " +
            (index < currentIndex ? "done" : index === currentIndex ? "current" : "")
          }
        >
          {step}
        </span>
      ))}
    </div>
  );
}
