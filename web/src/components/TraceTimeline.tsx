import { TraceSpan } from "../api";

const ZERO_SPAN_ID = "00000000-0000-0000-0000-000000000000";

interface TraceNode {
  span: TraceSpan;
  children: TraceNode[];
}

function buildTree(spans: TraceSpan[]): TraceNode[] {
  const nodeBySpanId = new Map<string, TraceNode>();
  for (const span of spans) {
    nodeBySpanId.set(span.span_id, { span, children: [] });
  }

  const roots: TraceNode[] = [];
  for (const span of spans) {
    const node = nodeBySpanId.get(span.span_id)!;
    const parent =
      span.parent_span_id !== ZERO_SPAN_ID ? nodeBySpanId.get(span.parent_span_id) : undefined;
    // Agent-side spans (e.g. "validator-agent.run") are traced from a
    // separate process with no propagated parent context, so they show up
    // as their own root here too — that's a real property of this app's
    // tracing setup, not a bug in the tree building.
    (parent ?? { children: roots }).children.push(node);
  }

  const byStartTime = (a: TraceNode, b: TraceNode) =>
    new Date(a.span.start_time).getTime() - new Date(b.span.start_time).getTime();
  const sortRecursive = (nodes: TraceNode[]) => {
    nodes.sort(byStartTime);
    nodes.forEach((n) => sortRecursive(n.children));
  };
  sortRecursive(roots);
  return roots;
}

function statusClass(status: string): string {
  if (status === "error") return "fail";
  if (status === "success") return "pass";
  return "";
}

function TraceRows({
  nodes,
  depth,
  rangeStart,
  rangeMs,
}: {
  nodes: TraceNode[];
  depth: number;
  rangeStart: number;
  rangeMs: number;
}) {
  return (
    <>
      {nodes.map((node) => {
        const span = node.span;
        const start = new Date(span.start_time).getTime();
        const end = new Date(span.end_time).getTime();
        const leftPct = ((start - rangeStart) / rangeMs) * 100;
        const widthPct = Math.max(((end - start) / rangeMs) * 100, 0.4);
        const durationMs = span.duration * 1000;
        return (
          <div key={span.span_id}>
            <div className="trace-row">
              <span
                className="trace-name"
                style={{ paddingLeft: depth * 14 }}
                title={span.name}
              >
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
            {node.children.length > 0 && (
              <TraceRows
                nodes={node.children}
                depth={depth + 1}
                rangeStart={rangeStart}
                rangeMs={rangeMs}
              />
            )}
          </div>
        );
      })}
    </>
  );
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
  const roots = buildTree(spans);

  return (
    <div className="trace-timeline">
      <TraceRows nodes={roots} depth={0} rangeStart={rangeStart} rangeMs={rangeMs} />
    </div>
  );
}
