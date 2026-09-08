import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { JobSummary, listJobs, statusBadgeClass } from "../api";

export default function JobList() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await listJobs();
        if (!cancelled) setJobs(data);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    }

    load();
    const interval = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (error) return <p className="error-banner">{error}</p>;
  if (!jobs) return <p className="muted">Chargement…</p>;
  if (jobs.length === 0) return <p className="muted">Aucun job pour l'instant.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>URL cible</th>
          <th>Type</th>
          <th>Pages</th>
          <th>Scénarios/page</th>
          <th>Statut</th>
          <th>Créé</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.job_id}>
            <td>
              <Link to={`/jobs/${job.job_id}`}>{job.target_url}</Link>
            </td>
            <td>
              <span className="chip info">
                {job.target_type === "chatbot" ? "Chatbot" : "Application web"}
              </span>
            </td>
            <td>{job.target_type === "chatbot" ? "1" : job.max_pages ?? "défaut"}</td>
            <td>{job.max_scenarios ?? "défaut"}</td>
            <td>
              <span className={`badge ${statusBadgeClass(job.status)}`}>{job.status}</span>
            </td>
            <td className="muted">{new Date(job.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
