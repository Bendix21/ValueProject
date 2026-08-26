# QA Swarm Autonomous

Système multi-agents autonome qui teste des applications web via un vrai
navigateur (Selenium), piloté par un orchestrateur FastAPI + LangGraph
(`QAState`, checkpointing Postgres, résilience, fan-out parallèle) et 6 agents
spécialisés (Discovery, Vision, Generator, Validator, Selenium Executor, LLM
Judge), chacun dans son propre conteneur.

## Démarrage (stack complète en un conteneur, y compris l'orchestrateur)

```powershell
copy .env.example .env
# éditer .env : renseigner LMNR_PROJECT_API_KEY si tu veux le tracing (facultatif)

docker compose up -d --build
```

Ça lance les 10 services : `postgres`, `selenium-grid`, les 6 agents,
`orchestrator` (exposé sur le port 8000) et `web`, l'interface (exposée sur
[http://localhost:3000](http://localhost:3000)) pour lancer des jobs, régler le
nombre de scénarios et suivre leur traçabilité (statut en direct, scénarios
générés, preuves d'exécution avec captures d'écran, verdicts du Judge, état de
résilience). Ollama n'est **pas** dans le compose —
le projet réutilise volontairement une instance Ollama déjà présente sur la
machine hôte (`OLLAMA_HOST=http://host.docker.internal:11434` dans les agents
qui en ont besoin), pour éviter de re-télécharger `llava:7b` et `qwen2.5:3b` à
chaque environnement. Si tu n'as pas d'Ollama local avec ces modèles, Vision
bascule automatiquement en `vision_mode: "ocr_only"` et les autres agents LLM
ont un mode dégradé équivalent — le pipeline reste fonctionnel, juste moins
précis.

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/jobs -Method Post -ContentType "application/json" -Body '{"target_url": "https://the-internet.herokuapp.com/login"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/jobs/<job_id>
```

## Développement local sans Docker pour l'orchestrateur

Pour itérer sur l'orchestrateur sans le reconstruire à chaque changement :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install -e libs/qa_swarm_common

docker compose up -d --build postgres selenium-grid discovery-agent vision-agent generator-agent validator-agent selenium-executor-agent llm-judge-agent

python scripts/dev_server.py
```

`scripts/dev_server.py` lance l'orchestrateur avec une boucle asyncio compatible
Windows (`SelectorEventLoop`), nécessaire car `psycopg` async est incompatible
avec le `ProactorEventLoop` que force uvicorn sur Windows. À l'intérieur du
conteneur Docker (Linux), ce problème n'existe pas — `uvicorn app.main:app`
tourne directement, c'est ce que fait le `Dockerfile` de l'orchestrateur.

Les agents exposent chacun `/health` et `/run` sur les ports 8001 à 8006 (mappés
depuis le port interne 8000 de chaque conteneur) :

| Service | Port host |
|---|---|
| orchestrator | 8000 |
| discovery-agent | 8001 |
| vision-agent | 8002 |
| generator-agent | 8003 |
| validator-agent | 8004 |
| selenium-executor-agent | 8005 |
| llm-judge-agent | 8006 |
| postgres | 5433 |
| selenium-grid | 4445 |

## Résilience

Retry automatique sur les pannes transitoires, isolation des échecs par
scénario, circuit breaker après échecs consécutifs, reprise de job interrompu
via `POST /jobs/{job_id}/resume` (checkpoint Postgres). Voir `app/graph/resilience.py`.

## Observabilité

Tracing OpenTelemetry vers [Laminar](https://lmnr.ai) si `LMNR_PROJECT_API_KEY`
est renseignée dans `.env` — sinon désactivé silencieusement, aucun impact sur
le fonctionnement. Un span par nœud du graphe, groupés par `job_id` (session
Laminar), plus des spans détaillés par agent.

## Tests

```powershell
pytest
```

Les tests unitaires patchent `call_agent` (pas de dépendance à Docker/Postgres)
pour valider le graphe (chemin heureux, échec d'agent single-shot, circuit
breaker) et la reprise via checkpoint. La validation end-to-end réelle (stack
Docker complète) se fait manuellement en frappant `POST /jobs`.

## API

- `POST /jobs` `{"target_url": "https://example.com", "max_scenarios": 3}` → démarre un job, retourne `job_id` (`max_scenarios` optionnel, 1 à 10, défaut celui du generator-agent)
- `GET /jobs` → liste des jobs (historique) avec leur statut courant
- `GET /jobs/{job_id}` → détail complet du job (statut, scénarios, résultats de validation/exécution/judge, captures d'écran, état de résilience, rapport final)
- `POST /jobs/{job_id}/cancel` → annule un job en cours (statut `cancelled`, terminal)
- `POST /jobs/{job_id}/resume` → reprend un job interrompu depuis son dernier checkpoint
- `GET /screenshots/{job_id}/...` → sert les captures d'écran (Discovery et preuves d'exécution)
- `GET /health` → healthcheck
