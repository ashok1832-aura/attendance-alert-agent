# Attendance Alert Agent (MAF on Azure AI Foundry)

A Microsoft Agent Framework agent for a college lecturer. It reads the attendance rule from the
college regulations, finds the students below it in Azure SQL, drafts an email for each one, and
sends each email through an email MCP server **only after the lecturer approves it**.

```
Lecturer ──► Foundry Hosted Agent (attendance-alert-agent, gpt-5.4)
               │ 1. search_regulations ─────────► Azure AI Search  (college-rag index)
               │ 2. get_students_below_attendance ► Azure SQL      (dbo.students, SELECT only)
               │ 3. classify: condonation (65–75%) vs detained (<65%)
               │ 4. send_email  ── PAUSE: Approve / Reject ──
               └──────────────────────────────────► Email MCP server (Container App, Easy Auth)
                                                      └──► Azure Communication Services Email
```

There are no API keys or connection strings anywhere. Every hop authenticates as an Entra identity:
`az login` when running locally, the Foundry agent identity when hosted, and the Container App's
managed identity for ACS.

## Layout

```
agent/                      the MAF agent (Foundry Hosted Agent, port 8088)
  .env                      every setting (endpoints, model, deploy target); see .env.example
  src/main.py               container entry: build agent -> ResponsesHostServer
  src/agent_deploy.py       register the pushed image as a new Foundry agent version
  src/config/config.py      reads settings from the environment (.env) with defaults; fails fast
  src/agent/builder.py      INSTRUCTIONS + FoundryChatClient + 3 tools -> Agent
  src/agent/credential.py   one credential per process (cli | managed_identity | default)
  src/agent/tools/
    regulations.py          @tool search_regulations       (approval: never)
    students.py             @tool get_students_below_attendance (approval: never, parameterised SQL)
    email.py                MCPStreamableHTTPTool -> send_email (approval: ALWAYS)
  scripts/invoke_hosted.py  talk to the hosted agent, approve/reject each email
  scripts/local_chat.py     run the agent in-process
  tests/                    unit tests (no Azure needed)
email-mcp/                  MCP server: one send_email tool over ACS Email
```

The `students` table is created and managed directly in Azure SQL; see [Database](#database).

## Azure resources (resource group `rag-api-RG`)

| Purpose | Resource |
|---|---|
| Foundry project + model | `RAG-MAF-API` / `rag-api-RG-proj`, deployment `gpt-5.4` (eastus2) |
| Regulations | AI Search `ragmanualdemo`, index `college-rag` (source container `ragstorageapi/collegedoc`) |
| Student table | Azure SQL `sql-attn2800-centralus` / db `attendance` (serverless, free offer, Entra-only auth) |
| Email | ACS `acs-attn2800` + email service `ecs-attn2800` (Azure-managed domain) |
| Email MCP server | Container App `ca-email-mcp` (in environment `cae-aura-test` — the subscription allows only one) |
| Images | ACR `acrattn2800` (`attendance-alert-agent:v5`, `email-mcp:v2`) |
| MCP API identity | Entra app `attendance-email-mcp` (`3788e220-b1f5-4bf3-86df-27b680f27822`) |

## Access granted (least privilege)

| Identity | Access |
|---|---|
| Agent (`c189cf2a-2e1d-4039-8132-3e1d845aa166`) | Search Index Data Reader on `ragmanualdemo`; `SELECT` on `dbo.students`; on the MCP allow-list |
| Container App `ca-email-mcp` | Communication and Email Service Owner on `acs-attn2800`; AcrPull |
| Foundry project | AcrPull on `acrattn2800` |
| Lecturer (`Ashok@…onmicrosoft.com`) | SQL Entra admin; on the MCP allow-list (local testing) |

The email MCP server is protected twice. **Easy Auth** rejects any request without a valid token for
`api://3788e220-…` (401). The app then checks the caller's object id against `ALLOWED_PRINCIPAL_IDS`
and rejects anyone else (403).

## Use it

```powershell
cd agent
# Read-only: who is below the requirement (sends nothing)
uv run python -m scripts.invoke_hosted "Which students are below the attendance requirement?"

# Email them: you are asked to approve or reject EACH email before it is sent
uv run python -m scripts.invoke_hosted "Email all students who are below the attendance requirement."
```

The same agent is also in the Foundry portal (Agents -> attendance-alert-agent -> Playground). There,
each `send_email` call shows **Approve / Reject**.

Mail comes from `DoNotReply@2e2991c4-9e77-4f1c-ac3d-d0242bbf06d5.azurecomm.net`. Azure-managed
domains often land in **spam**. Use a custom verified domain for production.

## Develop

```powershell
cd agent;     uv sync; uv run pytest; uv run ruff check .
cd email-mcp; uv sync; uv run pytest; uv run ruff check .
```

To run the agent in-process (`scripts/local_chat.py`), your own account also needs **Search Index Data
Reader** on `ragmanualdemo`.

## Deploy a new agent version

Set `IMAGE_TAG` in `agent/.env` to the new tag (for example `v6`), then:

```powershell
cd agent
az acr login -n acrattn2800
docker build --platform linux/amd64 -t acrattn2800.azurecr.io/attendance-alert-agent:v6 .
docker push acrattn2800.azurecr.io/attendance-alert-agent:v6
uv run python -m src.agent_deploy      # reads AZURE_CREDENTIAL_TYPE, ACR_NAME, IMAGE_TAG from .env
```

The agent identity stays the same across versions, so the grants above carry over.

## Database

Open the Azure portal, go to `sql-attn2800-centralus`, then database `attendance` → **Query editor**, and sign in with
**Microsoft Entra authentication** as the SQL admin.

**View the students**

```sql
SELECT * FROM dbo.students ORDER BY attendance_pct;
```

**Rebuild the table (only if it is ever deleted)**

```sql
CREATE TABLE dbo.students (
    student_id        VARCHAR(20)    NOT NULL PRIMARY KEY,
    full_name         NVARCHAR(100)  NOT NULL,
    email             NVARCHAR(254)  NOT NULL UNIQUE,
    department        NVARCHAR(50)   NOT NULL,
    semester          TINYINT        NOT NULL CHECK (semester BETWEEN 1 AND 8),
    regulation        VARCHAR(10)    NOT NULL,
    classes_held      SMALLINT       NOT NULL CHECK (classes_held > 0),
    classes_attended  SMALLINT       NOT NULL,
    attendance_pct    AS CAST(classes_attended * 100.0 / classes_held AS DECIMAL(5, 2)) PERSISTED,
    CHECK (classes_attended BETWEEN 0 AND classes_held)
);

INSERT INTO dbo.students (student_id, full_name, email, department, semester, regulation, classes_held, classes_attended)
VALUES ('22CS001', N'Manoj',        N'manoj@example.com',               N'CSE', 5, 'R22', 120,  84),  -- 70%
       ('22CS002', N'Ashok',        N'ashok@example.com',               N'CSE', 5, 'R22', 120,  72),  -- 60%
       ('22CS003', N'Priya Sharma', N'priya.sharma@example.com',        N'CSE', 5, 'R22', 120, 102),  -- 85%
       ('22CS004', N'Rahul Verma',  N'rahul.verma@example.com',         N'CSE', 5, 'R22', 120,  90),  -- 75%
       ('22CS005', N'Sneha Reddy',  N'sneha.reddy@example.com',         N'CSE', 5, 'R22', 120, 114);  -- 95%
```

**Give an agent identity read access** (only needed for a new agent name; the current one already has it)

```sql
CREATE USER [RAG-MAF-API-rag-api-RG-proj-attendance-alert-agent-AgentIdentity] FROM EXTERNAL PROVIDER;
GRANT SELECT ON dbo.students TO [RAG-MAF-API-rag-api-RG-proj-attendance-alert-agent-AgentIdentity];
```

## Change the data

- **Students:** edit the rows in the portal's Query editor (`INSERT` / `UPDATE dbo.students ...`). Changes apply immediately, with no redeploy.
- **Rules:** update the PDF in the `collegedoc` container and re-run the `college-rag-indexer`. No code change is needed, because the threshold always comes from the document.
- **Behaviour:** edit `INSTRUCTIONS` in `agent/src/agent/builder.py`, then deploy a new version.
- **Settings:** edit `agent/.env`, then deploy a new version. `agent_deploy.py` passes the settings to the
  hosted container as environment variables.

## Notes

- **Duplicate guard:** the email MCP server sends an identical email (same recipient, subject and body)
  at most once per 10 minutes and answers a repeat with `NOT_SENT: duplicate`. It was added because the
  preview hosting layer replayed approved `send_email` calls, so each student received the same email
  twice. The guard is kept in memory, so the Container App runs with `--max-replicas 1`, which lets one
  instance see every send.

- `ResponsesHostServer` in `agent-framework-foundry-hosting 1.0.0b260918` stores approval requests in
  Foundry's state store. A plain `Agent` therefore pauses and resumes on approval, without the
  `WorkflowAgent` wrapper older versions needed.
- Foundry sets `HOME` to a directory the container user can't write to. That's why the image runs
  `.venv/bin/python` directly instead of `uv run`.
- The serverless SQL database auto-pauses. The first query after a pause takes up to about 1 minute,
  and the tool retries the transient error 40613 while it resumes.
