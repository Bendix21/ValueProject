import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  API_BASE_URL,
  JobDetail as JobDetailType,
  JobTrace,
  TERMINAL_STATUSES,
  cancelJob,
  getJob,
  getJobTrace,
  resumeJob,
  statusBadgeClass,
} from "../api";
import StatusTimeline from "../components/StatusTimeline";
import TraceTimeline from "../components/TraceTimeline";

function screenshotSrc(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE_URL}${url}`;
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<JobDetailType | null>(null);
  const [trace, setTrace] = useState<JobTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      const data = await getJob(jobId);
      setJob(data);
      setError(null);
    } catch (err) {
      // Only surface the error if we have nothing to show yet — once a job
      // has loaded once, a transient poll failure shouldn't blank the page;
      // the next poll (2s later) retries anyway.
      if (!job) setError((err as Error).message);
    }
    try {
      const traceData = await getJobTrace(jobId);
      setTrace(traceData);
    } catch {
      // Trace fetch is best-effort — never block the job page on it.
    }
  }, [jobId, job]);

  useEffect(() => {
    load();
    const interval = setInterval(() => {
      if (job && TERMINAL_STATUSES.includes(job.status)) return;
      load();
    }, 2000);
    return () => clearInterval(interval);
  }, [load, job]);

  if (error) return <p className="error-banner">{error}</p>;
  if (!job) return <p className="muted">Chargement…</p>;

  const isTerminal = TERMINAL_STATUSES.includes(job.status);
  const hasDegradedAgents = Object.values(job.failure_states).some(
    (state) => state.degraded_mode || state.consecutive_failures > 0
  );

  async function handleCancel() {
    if (!jobId) return;
    setBusy(true);
    setActionError(null);
    try {
      await cancelJob(jobId);
      await load();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleResume() {
    if (!jobId) return;
    setBusy(true);
    setActionError(null);
    try {
      await resumeJob(jobId);
      await load();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="panel">
        <h2>Job {job.job_id}</h2>
        <p>
          <strong>{job.target_url}</strong>{" "}
          <span className={`badge ${statusBadgeClass(job.status)}`}>{job.status}</span>
        </p>
        <StatusTimeline status={job.status} />
        <p className="muted" style={{ marginTop: 10 }}>
          {job.pages_tested} page(s){job.max_pages ? ` (max ${job.max_pages})` : ""} ·{" "}
          {job.scenario_count} scénario(s)
          {job.max_scenarios ? ` (max ${job.max_scenarios}/page)` : ""} · créé le{" "}
          {new Date(job.created_at).toLocaleString()} · mis à jour le{" "}
          {new Date(job.updated_at).toLocaleString()}
        </p>
        <div className="form-row" style={{ marginTop: 12 }}>
          {!isTerminal && (
            <button className="danger" onClick={handleCancel} disabled={busy}>
              Annuler le job
            </button>
          )}
          {!isTerminal && (
            <button className="secondary" onClick={handleResume} disabled={busy}>
              Reprendre depuis le checkpoint
            </button>
          )}
        </div>
        {actionError && <p className="error-banner">{actionError}</p>}
        {job.final_report && (
          <p className="muted" style={{ marginTop: 10 }}>
            Résultat final : {job.final_report.passed} passé(s) / {job.final_report.failed} échoué(s)
            sur {job.final_report.pages_tested} page(s)
          </p>
        )}
      </section>

      {(job.circuit_breaker_tripped || hasDegradedAgents) && (
        <div className="failure-alert">
          {job.circuit_breaker_tripped && <p>⚠ Circuit breaker déclenché sur ce job.</p>}
          {Object.values(job.failure_states).map((state) => (
            <p key={state.agent_name}>
              <strong>{state.agent_name}</strong> — {state.consecutive_failures} échec(s)
              consécutif(s){state.degraded_mode ? " (mode dégradé)" : ""}
              {state.last_error ? ` — ${state.last_error}` : ""}
            </p>
          ))}
        </div>
      )}

      {job.final_report && job.final_report.blocked_pages.length > 0 && (
        <div className="failure-alert">
          <p>⚠ {job.final_report.blocked_pages.length} page(s) bloquée(s) par un CAPTCHA/anti-bot — non testées :</p>
          {job.final_report.blocked_pages.map((page) => (
            <p key={page.url}>
              <strong>{page.url}</strong>{page.reason ? ` — ${page.reason}` : ""}
            </p>
          ))}
        </div>
      )}

      {job.discovery_screenshots.length > 0 && (
        <section className="panel">
          <h2>Captures Discovery ({job.pages_tested} page(s))</h2>
          {Object.entries(
            job.discovery_screenshots.reduce<Record<string, typeof job.discovery_screenshots>>(
              (groups, shot) => {
                (groups[shot.page_url] ??= []).push(shot);
                return groups;
              },
              {}
            )
          ).map(([pageUrl, shots]) => (
            <div key={pageUrl} style={{ marginBottom: 14 }}>
              <p className="muted">{pageUrl}</p>
              <div className="screenshot-row">
                {shots.map((shot) => (
                  <figure key={shot.viewport_name}>
                    <div className="screenshot-thumb">
                      <img src={screenshotSrc(shot.url)} alt={shot.viewport_name} />
                    </div>
                    <figcaption>{shot.viewport_name}</figcaption>
                  </figure>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      {job.scenarios.length > 0 && (
        <section className="panel">
          <h2>Scénarios</h2>
          {job.scenarios.map((scenario) => {
            const validation = job.validation_results[scenario.scenario_id];
            const execution = job.execution_results[scenario.scenario_id];
            const verdict = job.judge_verdicts[scenario.scenario_id];
            return (
              <div key={scenario.scenario_id} className="scenario-card">
                <h3>{scenario.title}</h3>
                <p className="muted" style={{ marginTop: -6, marginBottom: 6 }}>
                  {scenario.page_url}
                </p>
                <p className="desc">{scenario.description}</p>
                <div className="verdict-row">
                  {validation && (
                    <span className={`chip ${validation.approved ? "pass" : "fail"}`}>
                      Validation : {validation.approved ? "approuvée" : "rejetée"}
                    </span>
                  )}
                  {execution && (
                    <span className={`chip ${execution.status === "success" ? "pass" : "fail"}`}>
                      Exécution : {execution.status}
                    </span>
                  )}
                  {verdict && (
                    <span className={`chip ${verdict.verdict === "pass" ? "pass" : "fail"}`}>
                      Judge : {verdict.verdict} ({Math.round(verdict.confidence * 100)}%)
                    </span>
                  )}
                </div>
                {verdict && <p className="muted">{verdict.reasoning}</p>}
                {validation && !validation.approved && (
                  <p className="muted">{validation.llm_review_notes}</p>
                )}
                {execution?.error_message && <p className="error-banner">{execution.error_message}</p>}
                {execution && execution.evidence.screenshots.length > 0 && (
                  <div className="screenshot-row">
                    {execution.evidence.screenshots.map((url) => (
                      <div key={url} className="screenshot-thumb">
                        <img src={screenshotSrc(url)} alt="preuve d'exécution" />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      )}

      <section className="panel">
        <h2>Traçabilité complète (Laminar)</h2>
        {trace && !trace.enabled && (
          <p className="muted">
            Tracing non configuré (renseigne <code>LMNR_PROJECT_API_KEY</code> dans <code>.env</code>{" "}
            pour l'activer).
          </p>
        )}
        {trace && trace.enabled && <TraceTimeline spans={trace.spans} />}
        {!trace && <p className="muted">Chargement des traces…</p>}
      </section>
    </>
  );
}
