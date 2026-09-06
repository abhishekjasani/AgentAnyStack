# Office UI guide

The office floor is a Minecraft-inspired voxel scene and the home screen for AgentAnyStack. Its block-built rooms, furniture, lighting, and agent characters use locally served Three.js. It shows the agents configured in your office repository and activity reported by the orchestrator. Open `/` on your running server; the default local URL is <http://127.0.0.1:8787/>.

## Find your way around

| Space | What you can do |
| --- | --- |
| Agent desks | Inspect an agent's model, connection, project, active runs, and approvals; open a conversation or configuration |
| Team studios | See agents grouped by team; filter the floor to one team |
| Project seating | Group agents by their configured project; unassigned agents appear together |
| Project hub | Open run history from the shared planning table |
| Reception | Ask Office about team knowledge or project status |
| Library | Read personal working notes, replace or clear notes, manage shared facts, and export OKF |
| Review room | Open the approval board to review pending requests |
| Server room | Manage inference connections and coding runtimes |
| Office pulse | Follow active runs, pending approvals, and recent outcomes |

The sidebar also provides agent creation, conversations, run history, local model management, integrations, and office settings. Room buttons and the directory below the floor open the same feature screens.

## Explore the 3D world

- Drag horizontally on the scene to rotate the camera within the cutaway office view.
- Use **Rotate left/right**, **Zoom in/out**, or **Reset camera** for keyboard-accessible camera control.
- Select **Expand office** to fill the workspace; press **Escape** or select it again to return.
- Click an agent's floating label to inspect its desk. Room labels open their corresponding features.
- Switch **Teams** / **Projects** to rearrange the agent desk islands.

The office splits large rosters into virtual floors with up to four desk rows (at most 12 people/agents) per floor. Use the search field and previous/next floor buttons to find anyone without shrinking the whole roster into one scene. Furniture, plants, illuminated floor markers, and server lights are environmental decoration. Agent activity indicators and typing motion depend on actual active runs. This is an office visualization, not a playable Minecraft world: block editing and first-person movement are not included.

If WebGL cannot initialize or its context is lost, an interactive HTML/SVG floor provides access to the desks and rooms. The sidebar and feature directory remain available.

## Human teammates

**People & agents** lists human directory entries and configured agents. Filter by member type or search names, roles, and teams. **Add a human teammate** saves their ID, name, team, and job title and gives them a place in the scene. **Remove entry** removes that directory record.

The current operator is shown even without a saved directory entry. Human seats are directory entries, not live presence; they do not create logins, send invitations, or grant permissions. Agents retain their existing desk configuration and live run states.

## Memory workspace

The library separates **Agent notebook** from **Team knowledge**. Select an agent for per-user notes, then expand the full notebook to see its fixed system primer. Note counts exclude that primer. Individual notes show their date and source run when recorded.

Shared knowledge cards show type, projects, tags, sensitivity, author, date, pin state, and provenance. Search or filter by type/project; **Clear filters** resets these controls. The loaded team is named next to the result count. **Show more knowledge** renders further results incrementally.

Expand **Add shared knowledge** to capture a fact, decision, procedure, or other supported type with projects, tags, sensitivity, and pinning. Use **Memory settings** for the existing context and notebook limits. Export writes the existing portable knowledge files; it is not a browser download.

## Give an agent work

Configure a connection, seat an agent, and select its project and model. Click the desk, choose **Start conversation**, and send a task. Return to the floor to observe the run. Clicking a desk opens details without starting a new run.

**Teams** and **Projects** change the visual arrangement only. A shared project table means agents are assigned to the same project. It does not initiate a meeting, delegate work, or represent observed messages between agents. Shared knowledge remains governed by the existing memory scopes.

## Understand activity

| State | Meaning |
| --- | --- |
| Available | No active run or pending approval is currently reported for that agent |
| Working | A run has started |
| Thinking | The adapter is streaming a thinking event |
| Using a tool | A tool event was reported; the HTML fallback desk bubble can show its name |
| Responding | Response tokens are streaming |
| Finishing | The stream reported completion and is being cleaned up |
| Needs approval | A pending approval exists and the agent has no active run |
| Failed | A run failed; inspect run history for details |

An agent can have an active run and pending approvals at the same time. The desk prioritizes the active run; the review room and desk details retain the approval information. Idle desks are not evidence that a provider is healthy or connected.

The UI refreshes approximately every three seconds while the browser tab is visible. It refreshes again when you return. If updates fail, the connection indicator and error message identify the displayed snapshot as potentially stale. Live presence expires after 35 seconds without a server heartbeat; normal completion, disconnect, and exceptions remove it immediately.

## Inspect completed work

**Run history** combines active runs with up to 100 recent journal entries for the current user, newest recent entries first. Each row includes the agent, team, project, model, status, and start time. **Inspect** opens the run metadata and retrieves recorded thinking when available. Approval decision audit records are excluded from this run list.

Token totals, costs, agent message graphs, and native Slack/Teams/GitHub integrations are not implemented in this view. The Integrations screen links to the orchestrator API and labels external connectors as planned.

## Troubleshooting

- **Empty office:** create an agent, or verify `OFFICE_REPO_PATH` points to your office repository.
- **UI missing:** launch from the repository root or set `OFFICE_UI_PATH` explicitly.
- **Updates disconnected:** check the orchestrator and its `/agents`, `/office/activity`, and `/approvals` responses. The UI retries automatically.
- **No activity during a task:** verify the task uses this orchestrator's agent chat stream and the same user identity as the UI.
- **No run history:** only journal entries available to the current user appear. Agent creation alone does not create a run.

## Accessibility and smaller screens

Floating desk and room labels and camera controls are keyboard-operable buttons, selected navigation and seating controls expose their state, and inspectors use native dialogs. Status is shown in text as well as color. Reduced-motion preferences disable animations. On smaller screens the floor, rooms, activity panel, and directory reflow, while navigation can scroll horizontally.
