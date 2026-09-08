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

## Mode chatbot (`target_type: "chatbot"`)

En plus du mode générique (`web_app`, valeur par défaut) qui teste des sites via DOM et
formulaires, le pipeline peut tester une interface de chatbot conversationnel (type ChatGPT) :
un seul champ de saisie, des réponses qui apparaissent dans la page. Activé via
`"target_type": "chatbot"` à la création du job (`POST /jobs`), ou via le sélecteur "Type de
cible" du web UI.

### Différences avec le mode `web_app`
- `max_pages` est forcé à 1 — un chatbot est une seule surface conversationnelle, pas un site
  à crawler.
- Le `Scenario` utilise un jeu d'actions dédié : `send_message`, `wait_for_response`,
  `assert_response`, `stop_generation`, `regenerate` (voir `libs/qa_swarm_common/schemas.py`).
- Le navigateur (discovery-agent **et** selenium-executor-agent) tourne en **mode visible**
  (pas `--headless`), car la plupart des chatbots sont protégés par un anti-bot (Cloudflare,
  reCAPTCHA) ou nécessitent une connexion.

### Vérification manuelle (captcha / connexion)
Le projet ne tente jamais de contourner un anti-bot ou un captcha — la vérification est
volontairement manuelle :
- Une pause de grâce (`CHATBOT_CAPTCHA_GRACE_SECONDS`, 60s par défaut, voir
  `docker-compose.yml`) démarre juste après le chargement de la page, avant toute action.
- Pendant cette pause, connecte-toi via le viewer noVNC du conteneur Selenium Grid :
  **http://localhost:7900** (aucun mot de passe). Le web UI l'ouvre automatiquement dans un
  nouvel onglet au lancement d'un job chatbot (`web/src/pages/NewJob.tsx`).
- **Une seule connexion suffit généralement pour tout le job** : discovery-agent capture les
  cookies de session juste après avoir passé le captcha (`session_cookies` sur
  `DiscoveryResult`), et l'orchestrateur les réinjecte automatiquement dans chaque session
  Selenium d'exécution de scénario suivante. Quand des cookies sont disponibles, la pause de
  grâce est plus courte (`chatbot_reauth_grace_seconds`, 45s) puisqu'il ne reste normalement
  qu'un éventuel défi résiduel à passer, pas une connexion complète.
- Chaque scénario ouvre malgré tout une session Selenium neuve (pas de profil partagé) — si
  les cookies ne suffisent pas à repasser un challenge résiduel, il faut ré-intervenir
  manuellement via noVNC.

### DSL des scénarios chatbot

| Action | `target_selector` | `value` | Effet |
|---|---|---|---|
| `send_message` | sélecteur du champ de saisie | texte du message | Tape le message et appuie sur Entrée |
| `wait_for_response` | toujours `null` | timeout en ms (optionnel) | Attend que le texte de la page se stabilise (fin du streaming) |
| `assert_response` | toujours `null` | sous-chaîne attendue, ou `null` | Vérifie qu'une réponse non vide est apparue (et la contient, si précisé) |
| `stop_generation` | sélecteur du bouton stop | — | Clique sur le bouton d'arrêt de génération |
| `regenerate` | sélecteur du bouton regénérer | — | Clique sur le bouton de régénération |

`wait_for_response` et `assert_response` n'utilisent jamais de sélecteur précis : ils
comparent le texte visible de toute la page avant/après (même mécanisme que `dom_diffs`),
car discovery/vision ne détectent pas encore de rôle "conteneur de messages", seulement les
éléments interactifs (champ de saisie, boutons).

### Génération de scénarios
En plus des scénarios de conversation classiques (question factuelle, échange multi-tours,
cas limites comme un message très long ou quasi-vide), le générateur peut produire deux types
de vérification supplémentaires :
- **Fact-check** — une question à réponse vérifiable (le fait correct est indiqué dans la
  `description` du scénario) ou une question sur un sujet fictif, pour détecter une
  hallucination confiante plutôt qu'une réponse honnête ("je ne sais pas").
- **Sécurité/refus** — une demande à laquelle l'assistant devrait normalement refuser de
  répondre (instructions dangereuses, phishing, données personnelles, contenu haineux), posée
  directement sans technique de contournement. Le judge vérifie que la réponse refuse/décline,
  pas qu'elle exécute la demande.

### Jugement sémantique
Contrairement au mode `web_app` (qui vérifie des signaux déterministes comme un changement
d'URL ou de cookies), un scénario chatbot réussi est jugé par un LLM local (`qwen2.5:3b` par
défaut) qui évalue la cohérence, la pertinence et l'exactitude factuelle de la réponse — pas
seulement sa présence (`CHATBOT_JUDGE_PROMPT` dans `agents/llm-judge-agent`). Le check
`assert_response` reste une porte déterministe en amont : s'il échoue (réponse vide, ou
sous-chaîne absente), l'exécution est en échec et le judge ne fait aucun appel LLM.

### Limites connues
- Le générateur (petit modèle 3B local) ne produit pas encore fiablement les scénarios
  fact-check/sécurité malgré l'instruction explicite — il retombe souvent sur les catégories
  de base seules.
- Le judge sémantique (même classe de modèle) peut occasionnellement se tromper sur une
  conversation multi-tours ou sous un prompt trop chargé — toujours vérifier
  `execution_results[...].evidence.conversation_transcript` avant de faire confiance à un
  verdict surprenant.
- Aucun rôle "conteneur de messages" n'est encore détecté par discovery/vision :
  `assert_response` compare tout le texte de la page, pas une zone précise.
- Le texte capturé peut inclure l'écho d'interface du chatbot lui-même (ex : `"You said: ...
  ChatGPT said: ..."` sur ChatGPT) en plus de la vraie réponse.
