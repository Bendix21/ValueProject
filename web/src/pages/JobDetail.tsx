import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  API_BASE_URL,
  JobDetail as JobDetailType,
  JobTrace,
  NOVNC_URL,
  TERMINAL_STATUSES,
  cancelJob,
  getJob,
  getJobTrace,
  resumeJob,
  statusBadgeClass,
} from "../api";
import Lightbox from "../components/Lightbox";
import StatusTimeline from "../components/StatusTimeline";
import TraceTimeline from "../components/TraceTimeline";

function screenshotSrc(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE_URL}${url}`;
}

function screenshotLabel(url: string): string {
  const name = url.split("/").pop() ?? "";
  if (name.startsWith("before")) return "Avant";
  if (name.startsWith("after")) return "Après";
  const match = name.match(/failure-step-(\d+)/);
  if (match) return `Échec à l'étape ${match[1]}`;
  return "Capture";
}

interface DeterministicSignals {
  url_changed?: boolean;
  new_cookie_names?: string[];
  changed_cookie_names?: string[];
  failed_step_index?: number | null;
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<JobDetailType | null>(null);
  const [trace, setTrace] = useState<JobTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null);

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
          <span className={`badge ${statusBadgeClass(job.status)}`}>{job.status}</span>{" "}
          <span className="chip info">
            {job.target_type === "chatbot" ? "Chatbot" : "Application web"}
          </span>
        </p>
        {job.target_type === "chatbot" && !isTerminal && (
          <p className="muted" style={{ marginTop: -4, marginBottom: 10 }}>
            🖥 Le navigateur tourne en mode visible pour passer un éventuel captcha ou te
            connecter —{" "}
            <a
              href={NOVNC_URL}
              onClick={(event) => {
                event.preventDefault();
                window.open(NOVNC_URL, "qa-swarm-novnc");
              }}
            >
              ouvrir la fenêtre noVNC
            </a>
            .
          </p>
        )}
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
                      <img
                        src={screenshotSrc(shot.url)}
                        alt={shot.viewport_name}
                        onClick={() =>
                          setLightbox({ src: screenshotSrc(shot.url), alt: shot.viewport_name })
                        }
                      />
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
            const signals = execution?.evidence.deterministic_signals as
              | DeterministicSignals
              | undefined;
            return (
              <div key={scenario.scenario_id} className="scenario-card">
                <h3>{scenario.title}</h3>
                <p className="muted" style={{ marginTop: -6, marginBottom: 6 }}>
                  {scenario.page_url} · priorité {scenario.priority}
                </p>
                <p className="desc">{scenario.description}</p>
                {scenario.steps.length > 0 && (
                  <ol className="step-list">
                    {scenario.steps.map((step, i) => (
                      <li key={i}>
                        <code>{step.action}</code>
                        {step.target_selector && (
                          <>
                            {" "}
                            sur <code>{step.target_selector}</code>
                          </>
                        )}
                        {step.value && (
                          <>
                            {" "}
                            = <code>{JSON.stringify(step.value)}</code>
                          </>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
                <div className="verdict-row">
                  {scenario.expect_failure && <span className="chip info">échec attendu</span>}
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
                {execution && (
                  <div className="verdict-row">
                    <span className="muted">
                      {execution.evidence.url_before}
                      {" → "}
                      {execution.evidence.url_after}
                      {signals?.url_changed ? " (changée)" : ""}
                    </span>
                    {signals?.new_cookie_names && signals.new_cookie_names.length > 0 && (
                      <span className="chip info">
                        +cookie : {signals.new_cookie_names.join(", ")}
                      </span>
                    )}
                    {signals?.changed_cookie_names && signals.changed_cookie_names.length > 0 && (
                      <span className="chip info">
                        cookie modifiée : {signals.changed_cookie_names.join(", ")}
                      </span>
                    )}
                    {signals?.failed_step_index != null && (
                      <span className="chip fail">
                        échec à l'étape {signals.failed_step_index + 1}
                      </span>
                    )}
                  </div>
                )}
                {execution && execution.evidence.conversation_transcript.length > 0 && (
                  <div className="transcript">
                    {execution.evidence.conversation_transcript.map((turn, i) => (
                      <div
                        key={i}
                        className={`transcript-turn ${turn.role === "user" ? "user" : "assistant"}`}
                      >
                        <span className="transcript-role">
                          {turn.role === "user" ? "Utilisateur" : "Chatbot"}
                        </span>
                        <p>{turn.text || "(réponse vide)"}</p>
                      </div>
                    ))}
                  </div>
                )}
                {execution && execution.evidence.screenshots.length > 0 && (
                  <div className="screenshot-row">
                    {execution.evidence.screenshots.map((url) => (
                      <figure key={url}>
                        <div className="screenshot-thumb">
                          <img
                            src={screenshotSrc(url)}
                            alt={screenshotLabel(url)}
                            onClick={() =>
                              setLightbox({ src: screenshotSrc(url), alt: screenshotLabel(url) })
                            }
                          />
                        </div>
                        <figcaption>{screenshotLabel(url)}</figcaption>
                      </figure>
                    ))}
                  </div>
                )}
                {execution && execution.evidence.console_logs.length > 0 && (
                  <details className="console-logs">
                    <summary>Logs console ({execution.evidence.console_logs.length})</summary>
                    <pre>{execution.evidence.console_logs.join("\n")}</pre>
                  </details>
                )}
                {execution && execution.evidence.network_errors.length > 0 && (
                  <details className="console-logs">
                    <summary>Requêtes réseau en échec ({execution.evidence.network_errors.length})</summary>
                    <pre>{execution.evidence.network_errors.join("\n")}</pre>
                  </details>
                )}
                {execution && execution.evidence.dom_diffs.length > 0 && (
                  <details className="console-logs">
                    <summary>Changements DOM ({execution.evidence.dom_diffs.length})</summary>
                    <pre>
                      {execution.evidence.dom_diffs.map((diff, i) => (
                        <div key={i} className={diff.op === "added" ? "dom-diff-added" : "dom-diff-removed"}>
                          {diff.op === "added" ? "+ " : "- "}
                          {diff.text}
                        </div>
                      ))}
                    </pre>
                  </details>
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

      {lightbox && (
        <Lightbox src={lightbox.src} alt={lightbox.alt} onClose={() => setLightbox(null)} />
      )}
    </>
  );
}
