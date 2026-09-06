# Office design decisions

Reviewed 2026-09-06. The interface combines an original voxel office with a conventional professional workspace: a stable sidebar, restrained graphite surfaces, readable forms, and a distinct knowledge library. All world geometry is generated in code; no Minecraft assets or external image service are used.

## Research applied

| Reference | Application |
| --- | --- |
| [Carbon: filtering](https://carbondesignsystem.com/patterns/filtering/) | Visible search/type/project filters, matching-result counts, and a clear-all action in the library. Search and team filters narrow the office roster. |
| [Carbon: disclosure patterns](https://carbondesignsystem.com/patterns/disclosures-pattern/) | Keep knowledge reading primary. Expand authoring, provenance, full notebook content, and note-management controls when needed. |
| [W3C: target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) | Camera and scene-label controls have minimum target dimensions, with larger directory and sidebar alternatives to dense spatial navigation. |
| [W3C: text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum) | Bright primary text and stronger secondary text on dark surfaces; text labels accompany colored activity indicators. |

These references informed implementation choices. They are not a claim that the entire application has passed a WCAG conformance audit.

## World and navigation

- Render up to four desk rows (at most 12 humans/agents) per virtual floor. Search, team/project arrangement, and previous/next controls keep large offices accessible.
- Keep keyboard-operable DOM labels over the 3D scene. Space overlapping labels apart, retain focus when data refreshes, and offer camera buttons as an alternative to dragging.
- Preserve camera position while activity updates. Reuse geometry/materials, cache shadows, and cap active typing animation updates. Pause rendering when hidden and respect reduced motion.
- Keep all feature screens in the sidebar and use room labels as additional entry points. If WebGL fails, retain the HTML/SVG floor and normal navigation.

## Humans and agents

Human directory entries have explicit **Human** labels. Agent states come from run presence. Human directory membership does not imply online status, account provisioning, invitations, or permission grants. The current operator comes from the request identity. Shared seating expresses organization and project assignment, not observed agent-to-agent delegation.

## Memory

Personal notebooks and shared team facts have separate reading areas. Notebook entries show dates and source runs, while the fixed system primer stays in the full-notebook disclosure and is excluded from note counts. Shared facts show type, project, tags, sensitivity, author, pin state, and provenance. Search and filters operate on the loaded team, with incremental rendering for long lists.

Memory settings remain available through the existing office configuration. The redesign does not silently raise model context budgets, change memory scopes, or invent cost/token statistics.

## Verification scope

The layout planner is tested with 0, 1, 12, 100, and 1,000 agents, including mixed human/agent identities, filtering, and page clamping. This checks reachability and bounded scene size; it is not a 1,000-user concurrency or GPU performance benchmark. Backend tests cover directory persistence and validation, user-scoped activity, heartbeat expiry, and stream cleanup. Desktop/mobile browser checks cover navigation, controls, filtering, and layout.
