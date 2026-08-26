import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createJob } from "../api";
import JobList from "./JobList";

export default function NewJob() {
  const [targetUrl, setTargetUrl] = useState("");
  const [maxScenarios, setMaxScenarios] = useState<string>("");
  const [maxPages, setMaxPages] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { job_id } = await createJob(
        targetUrl,
        maxScenarios.trim() === "" ? null : Number(maxScenarios),
        maxPages.trim() === "" ? null : Number(maxPages)
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
              <label htmlFor="max_scenarios">Scénarios par page</label>
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
            <button type="submit" disabled={submitting}>
              {submitting ? "Lancement…" : "Lancer le job"}
            </button>
          </div>
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
