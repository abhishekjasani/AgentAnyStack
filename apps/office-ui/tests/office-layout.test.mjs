import { test } from "node:test";
import assert from "node:assert/strict";
import { planOffice } from "../office-layout.mjs";
const agents = (n) =>
  Array.from({ length: n }, (_, i) => ({
    id: `agent-${i}`,
    name: `Agent ${i}`,
    team: `team-${i % 7}`,
    project_id: `project-${i}`,
  }));
for (const size of [0, 1, 12, 100, 1000])
  test(`all ${size} agents remain reachable with bounded floors`, () => {
    const roster = agents(size);
    const first = planOffice(roster);
    const ids = [];
    for (let page = 0; page < first.pageCount; page++) {
      const plan = planOffice(roster, [], { page });
      assert.ok(plan.rows.length <= 4);
      assert.ok(plan.visible <= 12);
      ids.push(...plan.rows.flatMap((r) => r.members.map((a) => a.id)));
    }
    assert.equal(new Set(ids).size, size);
    assert.equal(ids.length, size);
  });
test("humans and agents with same id stay distinct; filters and page clamping work", () => {
  const roster = agents(100);
  const people = [{ id: "agent-0", name: "Human coworker", team: "team-0" }];
  const result = planOffice(roster, people, {
    query: "Human coworker",
    page: 900,
  });
  assert.equal(result.total, 1);
  assert.equal(result.page, 0);
  assert.equal(result.rows[0].members[0].kind, "human");
  const team = planOffice(roster, people, { team: "team-0" });
  assert.ok(
    team.rows.flatMap((r) => r.members).every((p) => p.team === "team-0"),
  );
  assert.equal(
    planOffice(roster, [], { arrangement: "project" }).pageCount,
    25,
  );
  assert.equal(planOffice(roster, [], { query: "no match" }).visible, 0);
});
