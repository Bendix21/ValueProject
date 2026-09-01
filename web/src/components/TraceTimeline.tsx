import { TraceSpan } from "../api";

function statusClass(status: string): string {
  if (status === "error") return "fail";
  if (status === "success") return "pass";
  return "";
}

export default function TraceTimeline({ spans }: { spans: TraceSpan[] }) {
  if (spans.length === 0) {
    return <p className="muted">Aucune trace pour le moment.</p>;
  }

  const starts = spans.map((s) => new Date(s.start_time).getTime());
  const ends = spans.map((s) => new Date(s.end_time).getTime());
  const rangeStart = Math.min(...starts);
  const rangeEnd = Math.max(...ends);
  const rangeMs = Math.max(rangeEnd - rangeStart, 1);

  return (
    <div className="trace-timeline">
      {spans.map((span) => {
        const start = new Date(span.start_time).getTime();
        const end = new Date(span.end_time).getTime();
        const leftPct = ((start - rangeStart) / rangeMs) * 100;
        const widthPct = Math.max(((end - start) / rangeMs) * 100, 0.4);
        const durationMs = span.duration * 1000;
        return (
          <div key={span.span_id} className="trace-row">
            <span className="trace-name" title={span.name}>
              {span.name}
            </span>
            <div className="trace-track">
              <div
                className={`trace-bar ${statusClass(span.status)}`}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                title={`${span.name} — ${durationMs.toFixed(1)} ms — ${span.status}`}
              />
            </div>
            <span className="trace-duration">{durationMs.toFixed(0)} ms</span>
          </div>
        );
      })}
    </div>
  );
}
