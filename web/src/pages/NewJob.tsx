import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { NOVNC_URL, TargetType, createJob } from "../api";
import JobList from "./JobList";

export default function NewJob() {
  const [targetUrl, setTargetUrl] = useState("");
  const [targetType, setTargetType] = useState<TargetType>("web_app");
  const [maxScenarios, setMaxScenarios] = useState<string>("");
  const [maxPages, setMaxPages] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    if (targetType === "chatbot") {
      // Opened synchronously (before the createJob await) and reused via a
      // fixed window name so popup blockers don't intercept it and relaunching
      // a job doesn't pile up tabs.
      window.open(NOVNC_URL, "testpilot-novnc");
    }
    try {
      const { job_id } = await createJob(
        targetUrl,
        maxScenarios.trim() === "" ? null : Number(maxScenarios),
        targetType === "chatbot" ? null : maxPages.trim() === "" ? null : Number(maxPages),
        targetType
      );
      navigate(`/jobs/${job_id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <section className="panel">
        <h2>Nouveau job</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="target_url">URL cible</label>
              <input
                id="target_url"
                type="text"
                placeholder="https://example.com"
                required
                value={targetUrl}
                onChange={(event) => setTargetUrl(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="target_type">Type de cible</label>
              <select
                id="target_type"
                value={targetType}
                onChange={(event) => setTargetType(event.target.value as TargetType)}
              >
                <option value="web_app">Application web</option>
                <option value="chatbot">Chatbot conversationnel</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="max_scenarios">
                {targetType === "chatbot" ? "Scénarios de conversation" : "Scénarios par page"}
              </label>
              <input
                id="max_scenarios"
                type="number"
                min={1}
                max={10}
                placeholder="défaut"
                value={maxScenarios}
                onChange={(event) => setMaxScenarios(event.target.value)}
              />
            </div>
            {targetType === "web_app" && (
              <div className="field">
                <label htmlFor="max_pages">Nombre de pages max</label>
                <input
                  id="max_pages"
                  type="number"
                  min={1}
                  max={20}
                  placeholder="défaut"
                  value={maxPages}
                  onChange={(event) => setMaxPages(event.target.value)}
                />
              </div>
            )}
            <button type="submit" disabled={submitting}>
              {submitting ? "Lancement…" : "Lancer le job"}
            </button>
          </div>
          {targetType === "chatbot" && (
            <p className="muted" style={{ marginTop: 10 }}>
              Les chatbots sont souvent protégés par un anti-bot (Cloudflare) ou nécessitent une
              connexion. Une fenêtre noVNC va s'ouvrir automatiquement (autorise les pop-ups si
              le navigateur la bloque) — utilise-la pour passer le captcha / te connecter
              manuellement dès que le job démarre. Une seule connexion suffit normalement pour
              tout le job (la session est réutilisée pour chaque scénario).
            </p>
          )}
          {error && <p className="error-banner">{error}</p>}
        </form>
      </section>

      <section className="panel">
        <h2>Historique</h2>
        <JobList />
      </section>
    </>
  );
}
