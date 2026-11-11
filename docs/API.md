# API the CLI expects

The CLI is a thin client. These routes live in the private `station-house-platform` repo
(`src/app/api/v1/`, documented in its `docs/contributor-api.md`) and are deployed at
`https://app.station-house.net`. Against an older server the CLI answers "doesn't support that yet"
on a 404.

## Auth

`stationhouse login` signs in by device authorization (RFC 8628) against the platform's Better Auth,
under `/api/auth`:

| Call | Body | Answer |
|---|---|---|
| `POST /device/code` | `{ client_id: "stationhouse-cli" }` | `{ device_code, user_code, verification_uri, verification_uri_complete, expires_in, interval }`; 404 where the server has no device sign-in; 429 past 20 per 10 minutes from one IP. The CLI shows `verification_uri` and `user_code` for the member to type (the page ignores a code in the link), and its `User-Agent` (`stationhouse-cli/<version> (<platform>; Python <version>)`) is shown on the page next to the code. |
| `POST /device/token` (every `interval` s) | `{ grant_type: "urn:ietf:params:oauth:grant-type:device_code", device_code, client_id }` | `{ access_token }` (a session token) once approved at `/device`; else 400 `{ error }`: `authorization_pending`, `slow_down` (+5 s), `access_denied`, `expired_token` |
| `GET /token` | `Authorization: Bearer <session token>` | `{ token }`: the 15-minute JWT, fetched again when it runs out; 401 once the session has ended; 403 `{ code: "ACCOUNT_DISABLED" }` for a disabled account |
| `POST /sign-out` | `Authorization: Bearer <session token>` | ends the session (`stationhouse logout`) |

Where `/device/code` is a 404 (a server still signing in with Cognito), or with `login --email` or
`login --password`, sign-in is against the Station House Cognito user pool instead: an emailed code
(`USER_AUTH` with `EMAIL_OTP`), or SRP with `--password`.

Every call sends the JWT, or for a Cognito sign-in the access token plus the ID token:

```
Authorization: Bearer <JWT, or Cognito access token>
x-station-house-id-token: <Cognito ID token>          (Cognito only)
```

The platform verifies them (`MemberTokens`) and derives the member's Hugging Face handle from their
verified `HfBinding`. Identity is never read from a body. Admin routes need the `admins` group.

## The CLI's version (0.2.0 on)

Every call, `/api/auth` included, also sends `X-Stationhouse-CLI-Version: <version>`. When the CLI
is below the minimum admins set, the platform answers any call with 426
`{ error, minimum, latest, upgrade }`, and the CLI prints `This version (<version>) is no longer
supported. Update: <upgrade command>` and exits 1.

| Call | Answer |
|---|---|
| `GET /api/cli/version` (no sign-in) | `{ minimum: "X.Y.Z" \| null, latest: "X.Y.Z" }`, asked before a command at most once an hour (`~/.config/stationhouse/version-check.json`); offline or any other failure lets the command run, and it isn't asked again for ten minutes |
| `GET /api/admin/config?key=CLI_MIN_VERSION` | `{ key, value }`, `value` `""` when unset (`admin cli-min-version`) |
| `PUT /api/admin/config` | `{ key: "CLI_MIN_VERSION", value: "X.Y.Z" }`; 400 for a non-version or one newer than `latest` |
| `DELETE /api/admin/config?key=CLI_MIN_VERSION` | removes it (`admin cli-min-version --clear`) |

## Routes (all under `/api/v1`, JSON)

Projects come first and tasks live under their project. A task asked for under the wrong project is a
404 whose body names its project (`{ error, projectId, taskId }`); the CLI follows it unless you passed
`--project` yourself.

| Method + path | Body / query | Response |
|---|---|---|
| `GET /me` | | `{ memberId, hfUsername \| null, isAdmin }` |
| `GET /me/claims` | | `{ claims: [{ taskId, projectId, title, status, stale }] }` |
| `GET /projects` | | `{ projects: [{ id, title, summary }] }` |
| `GET /projects/{p}` | | `{ project, overview }` |
| `GET /projects/{p}/tasks` | | `{ project, you, tasks: [{ taskId, title, parentTaskId, childTaskIds, summary, scope, completionCriteria, available, closed, workable, full, people, mine, pendingSubtasks }] }` (the whole tree; `explore` and `find-work` read this) |
| `GET /projects/{p}/unclaimed` | | `{ tasks: [{ taskId, title, summary }] }` |
| `GET /projects/{p}/prs` | `?limit=` | `{ project, prs: [{ repo, num, title, url, author, taskId, reviewers, ... }] }` |
| `POST /projects/{p}/requests` | `{ title, description, atomicUnit? }` | `{ requestId, created, notified, status }` (`task request`) |
| `GET /projects/{p}/tasks/{t}` | | the task in full |
| `GET /projects/{p}/tasks/{t}/people` | | `{ projectId, taskId, title, people: [{ hfUsername, prNums?, stale, you? }] }` |
| `GET /projects/{p}/tasks/{t}/context` | | the task's work-graph neighbourhood (`context`) |
| `POST /projects/{p}/tasks/{t}/claim` | (no body) | `{ projectId, taskId, people, dashboard }` |
| `POST /projects/{p}/tasks/{t}/release` | (no body) | `{ ok: true, dashboard }` |
| `POST /projects/{p}/tasks/{t}/assign` | `{ hfUsername }` (admin only) | `{ ok: true }` |
| `POST /projects/{p}/tasks/{t}/subtasks` | `{ title, summary }` | `{ proposalId, created, status }` (`task create`) |
| `GET /proposals`, `POST /proposals/approve`, `POST /proposals/reject` | (admin only) | the subtask-proposal queue |
| `PUT`/`DELETE /projects/{p}/membership` | (no body) | `{ projectId, title, member, lead, following, reason, changed }` (`join`, `leave`; a lead's leave is a 409) |
| `GET`/`PUT`/`DELETE /projects/{p}/following` | (no body) | the same (`follow`, `unfollow`; GET reads it, without `changed`) |
| `GET`/`PUT`/`DELETE /pages/{id}/following` | (no body) | `{ following, reason, unfollowed, projectFollowing, others }` (`follow --page`, `unfollow --page`) |
| `GET /me/following` | | `{ projects: [{ projectId, title, member, lead, following, reason }], pages: [{ pageId, projectId, projectTitle, kind, title, reason, lastActivityAt }] }` (`following`) |
| `POST /agent/chat` | `{ messages: [{ role, text }], project? }` | `{ reply, suggestedActions, taskIds }` (the assistant, for people) |

Errors are `{ "error": "message" }` with a normal status. `claim` for a member with no verified HF
handle is a 409 with a message telling them to verify it on the website. `dashboard` is `added` /
`removed` / `unchanged` / `failed` for the task's card on the website dashboard. The Join & Follow
routes answer 403 for a project the member can't see; the CLI then names the nearest one they can.

## Project-management tasks

`GET /projects` and `GET /projects/{p}` give each project's `taskModel`: `"project_management"` or
`"catalog"`.

- **Catalog projects** answer the routes above as they always have.
- **Project-management projects** answer `tasks`, `unclaimed`, `tasks/{t}`, `claim` and `release`
  in the new shapes (`model: "project_management"`).
- **New routes** (`state`, `comments`, `propose`, `approve`, …) are project management's alone. On a
  catalog project they're a 409 "`<project>` hasn't moved to project management yet."

A task is named by its number: `{t}` is `12`, `<project>#12` (URL-encoded) or its id. The platform's
`docs/contributor-api.md` has the full table. The responses the CLI prints are fixtures in
`tests/fixtures/v1/`, written by the platform's route tests, so the two can't drift.

| Command | Call |
|---|---|
| `tasks [--state S] [--milestone M] [--mine] [--all]` | `GET /projects/{p}/tasks` |
| `task <n> [--feed]` | `GET /projects/{p}/tasks/{n}` |
| `unclaimed` (= `tasks --state unclaimed`) | `GET /projects/{p}/unclaimed` |
| `claim <n>`, `release <n>` (`unclaim`) | `POST …/tasks/{n}/claim`, `…/release` |
| `move <n> <state>` | `PUT …/tasks/{n}/state { state }` |
| `comment <n> <text>` | `POST …/tasks/{n}/comments { body, replyTo? }` |
| `propose "<title>" [--take]`, `propose --draft <n>` | `POST /projects/{p}/tasks { start: "proposed" }`, `POST …/tasks/{n}/propose` |
| `task new "<title>" [--open] [--milestone M]` | `POST /projects/{p}/tasks`, then `PUT …/milestone` |
| `task new "<title>" --offer <who>` (leads) | the board's `POST /board/projects/{p}/tasks { start: "open", offerTo }` (below) |
| `task proposals`, `task approve/send-back/decline/reopen/open <n>` | the list's `proposals`; `POST …/tasks/{n}/<action>` |
| `task edit <n>`, `task milestone <n> <M\|none>`, `task subtask <n> "<title>"` | `PATCH …/tasks/{n}`, `PUT …/milestone`, `POST …/subtasks` |
| `assign <n> <who>`, `unassign <n> <who>` | `POST …/tasks/{n}/owners { who }`, `DELETE …/owners/{who}` |
| `mine [--all]` | `GET /me/tasks`, then `GET /me/claims` |

A refusal prints the platform's message, then a hint of the CLI's own, indented and dim on a
terminal (where to join, its owners, or the states you can pick). A CLI older than 0.3.0 gets 409
`code: "cliUpdateRequired"` from these routes, and prints its message, which says how to update.

## Project management (`/board/…`, Leads run projects)

A project's leads run its page (STA-304 to STA-311): its About, milestones, offers and moderation.
These are the site's own board routes re-exported under `/api/v1/board/`, with the site's contract
and errors. Writes are leads' (and admins') only: anyone else gets a 403 whose message the CLI shows
as it is ("Only the project's leads can lock a post's comments."). A stale save is a 409.

| Method + path | Body / query | Response | Command |
|---|---|---|---|
| `GET /board/projects/{p}/about` | | `{ about: { page, body, canEdit, summary, saved: { by, at } } }` | `about` |
| `PUT /board/projects/{p}/about` | `{ body, baseVersion }` | `{ page }`; 409 when `baseVersion` isn't the latest | `about edit` (`--force`: the latest as base) |
| `GET /board/pages/{page}/versions` | | `{ versions: [{ version, authorId, authorName, createdAt }] }` newest first | `about history` |
| `GET /board/pages/{page}/diff` | `?from=&to=` | `{ diff: { from, to, lines: [{ type, text }] } }` | `about diff` |
| `GET /board/projects/{p}/milestones` | | `{ rail: { milestones, currentId, canEdit } }` | `milestones`; every `milestone` command reads it first |
| `POST /board/projects/{p}/milestones` | `{ title, summary, notes, dueOn }` | `{ rail }` (it goes last) | `milestone add` |
| `PUT /board/projects/{p}/milestones/order` | `{ order: [milestoneId…] }` | `{ rail }` | `milestone add --before`, `milestone move` |
| `PATCH /board/milestones/{m}` | `{ title, summary, notes, dueOn, baseVersion }` | `{ rail }` | `milestone edit` (sends the fields it isn't changing as they are) |
| `PUT /board/milestones/{m}/completed` | `{ completed, openTasks?: "move" \| "leave" }` | `{ rail, completion: { to, movedTaskIds } }` | `milestone done`, `milestone reopen` |
| `DELETE /board/milestones/{m}` | | `{ rail }` | `milestone delete` |
| `GET /board/projects/{p}/tasks` | | `{ tasks: { groups: [{ milestone, tasks }], proposals } }` | `milestone done` (its open tasks); short task ids and people's names |
| `POST /board/projects/{p}/tasks` | `{ title, body, start: "open", offerTo? }` | `{ task }` (the task's view) | `task new` |
| `GET /board/tasks/{t}` | | `{ task }` with `offer`, `canOffer`, `people` | `offer <task> <person>` (names) |
| `PUT /board/tasks/{t}/milestone` | `{ milestoneId }` | `{ task }` | `task new --milestone` |
| `PUT /board/tasks/{t}/offer` | `{ memberId }` | `{ task }` | `offer <task> <person>` |
| `POST /board/tasks/{t}/offer` | `{ accept, reason? }` | `{ task }` | `offer accept`, `offer decline` |
| `DELETE /board/tasks/{t}/offer` | | `{ task }` | `offer withdraw` |
| `GET /board/me/offers` | `?projectId=` | `{ toYou, byLeads }` | `offers`; short task ids |
| `PUT /board/posts/{post}/hidden` | `{ hidden, note? }` | `{ post }` | `post hide`, `post unhide` |
| `PUT /board/posts/{post}/locked` | `{ locked, reason? }` | `{ post }` | `post lock`, `post unlock` |
| `PUT /board/comments/{c}/hidden` | `{ hidden }` | `{ comments }` | `comment hide`, `comment unhide` |

Board ids are UUIDs. The CLI shows a task's first 8 characters and takes any unique start of its id,
looked up in `me/offers` and the Tasks tab. Posts and comments take their full id: no v1 route lists
them. A person (`--offer`, `offer <task> <person>`) is a name or the start of one, matched against
the people those routes name (tasks' owners, offers, proposers, a task's `people`), or a member id;
`GET /board/projects/{p}/mentions` (the @ picker's people) is read too where the server serves it.

### Admins

| Method + path | Body | Response | Command |
|---|---|---|---|
| `POST /api/admin/projects/{p}/overview-migration` (not under `/api/v1`) | `{ apply }` | `{ report: { projectId, applied, plan: { summary, about, milestones, headerLinks } \| null, about, milestones, headerLinks, notified } }`; `about`/`milestones` are `write`, `exists` or `empty` | `admin migrate-overview <p> [--apply]` (STA-312; a dry run without `--apply`) |

## Who thinks where

- **People asking questions** (`stationhouse`, `stationhouse <question>`, `stationhouse ask`) get the
  platform's assistant (`POST /agent/chat`), which reads the same data and never changes anything:
  claims it suggests are put to you as y/N and made by the CLI.
- **Coding agents and scripts** use the other commands. They return facts and do no thinking of
  their own: `find-work` is a fixed ranking (nobody on it beats only stale claims beats shared; a
  subtask beats a parent with open subtasks; words you give it narrow the list), so its reasons are
  the real reasons, and `explore` is a keyword lookup over the task tree. No model runs on your
  machine.
