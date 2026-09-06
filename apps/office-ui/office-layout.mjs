// Bound geometry per floor independently of total roster size.
export function planOffice(
  agents,
  people = [],
  { team = "", arrangement = "team", query = "", page = 0 } = {},
) {
  const term = query.trim().toLowerCase();
  const members = [
    ...agents.map((a) => ({ ...a, kind: "agent" })),
    ...people.map((p) => ({ ...p, kind: "human" })),
  ].filter(
    (p) =>
      (!team || p.team === team) &&
      (!term ||
        [p.name, p.id, p.team, p.project_id, p.title, p.kind]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(term)),
  );
  const groupFor = (p) =>
    arrangement === "project"
      ? p.project_id || (p.kind === "human" ? "Human workspace" : "Unassigned")
      : p.team;
  const grouped = new Map();
  for (const member of members) {
    const key = groupFor(member);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(member);
  }
  const allRows = [];
  for (const [group, entries] of [...grouped].sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    entries.sort(
      (a, b) =>
        a.name.localeCompare(b.name) ||
        a.kind.localeCompare(b.kind) ||
        a.id.localeCompare(b.id),
    );
    for (let i = 0; i < entries.length; i += 3)
      allRows.push({ group, members: entries.slice(i, i + 3), first: i === 0 });
  }
  const pageCount = Math.max(1, Math.ceil(allRows.length / 4));
  const currentPage = Math.max(
    0,
    Math.min(pageCount - 1, Number.isFinite(page) ? Math.floor(page) : 0),
  );
  const rows = allRows.slice(currentPage * 4, currentPage * 4 + 4);
  if (rows.length) rows[0] = { ...rows[0], first: true };
  return {
    rows,
    page: currentPage,
    pageCount,
    total: members.length,
    visible: rows.reduce((sum, row) => sum + row.members.length, 0),
  };
}
