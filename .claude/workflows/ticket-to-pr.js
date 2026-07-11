export const meta = {
  name: 'ticket-to-pr',
  description: 'Take one open GitHub issue through analysis, planning, implementation, code review, PR, and PR-review loop. Stops before merge for human approval.',
  whenToUse: 'Run when asked to implement a specific GitHub issue end-to-end, or to pick up the oldest open issue and drive it to a reviewed, mergeable PR.',
  phases: [
    { title: 'Find Ticket', detail: 'locate the target open issue via gh, refuse closed ones' },
    { title: 'Analyze & Plan', detail: 'read the issue, produce an implementation plan' },
    { title: 'Setup Branch', detail: 'create an isolated worktree + branch named after the issue' },
    { title: 'Implement', detail: 'make the change in the worktree' },
    { title: 'Code Review', detail: 'review diff vs plan, loop fixes until approved' },
    { title: 'Commit & PR', detail: 'commit, push, open PR against main' },
    { title: 'PR Review Loop', detail: 'review the PR, comment, loop fixes until approved' },
    { title: 'Cleanup', detail: 'remove the local worktree once pushed' },
  ],
}

// This workflow never runs `gh pr merge` — merging to main is left to a human
// even after the PR review step reports approved, by design (see CLAUDE.md
// "Executing actions with care": merging is hard to reverse and affects shared state).
const MAX_ROUNDS = 3

const TICKET_SCHEMA = {
  type: 'object',
  properties: {
    found: { type: 'boolean' },
    reason: { type: 'string' },
    number: { type: 'number' },
    title: { type: 'string' },
    body: { type: 'string' },
    url: { type: 'string' },
  },
  required: ['found'],
}

const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    plan: { type: 'string' },
    slug: { type: 'string' },
    filesToTouch: { type: 'array', items: { type: 'string' } },
  },
  required: ['plan', 'slug'],
}

const WORKTREE_SCHEMA = {
  type: 'object',
  properties: {
    worktreePath: { type: 'string' },
    branch: { type: 'string' },
  },
  required: ['worktreePath', 'branch'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    approved: { type: 'boolean' },
    findings: { type: 'array', items: { type: 'string' } },
  },
  required: ['approved'],
}

phase('Find Ticket')
const ticket = await agent(
  `Using the gh CLI, find the target GitHub issue in this repo.
${
  args && args.issueNumber
    ? `Fetch issue #${args.issueNumber} specifically: gh issue view ${args.issueNumber} --json number,title,body,state,url`
    : `List open issues: gh issue list --state open --json number,title,createdAt,url and pick the OLDEST one by createdAt.`
}
Do NOT select or act on any closed issue under any circumstances.
Return found=true with number/title/body/url only if the issue exists and its state is OPEN.
If it's closed or doesn't exist, return found=false with a reason and do nothing else.`,
  { schema: TICKET_SCHEMA, phase: 'Find Ticket' }
)

if (!ticket || !ticket.found) {
  log(`No open ticket to process: ${ticket ? ticket.reason : 'agent failed'}`)
  return { status: 'no-ticket', ticket }
}

log(`Working on issue #${ticket.number}: ${ticket.title}`)

phase('Analyze & Plan')
const plan = await agent(
  `Read and analyze GitHub issue #${ticket.number} in this repo.
Title: ${ticket.title}
Body: ${ticket.body}

Explore the current codebase to understand the relevant code paths, then produce an implementation plan for a feature/fix that satisfies this issue WITHOUT breaking existing functionality or behavior. Follow this repo's CLAUDE.md conventions and layering rules.

Do NOT make any edits yet — analysis and planning only.

Return the plan (files to touch, specific changes, how existing behavior is preserved) and a short kebab-case slug for the branch name (e.g. "fix-login-timeout").`,
  { schema: PLAN_SCHEMA, phase: 'Analyze & Plan' }
)

const branchName = `issue-${ticket.number}-${plan.slug}`
log(`Plan ready. Branch: ${branchName}`)

phase('Setup Branch')
const worktree = await agent(
  `Set up an isolated git worktree for implementing GitHub issue #${ticket.number}.
1. git fetch origin main
2. git worktree add ../wt-${branchName} -b ${branchName} origin/main
   (pick a different sibling path if that one is already taken)
3. Report back the ABSOLUTE path to the new worktree and the branch name. Do not implement anything yet.`,
  { schema: WORKTREE_SCHEMA, phase: 'Setup Branch' }
)

log(`Worktree ready at ${worktree.worktreePath} (branch ${worktree.branch})`)

phase('Implement')
await agent(
  `Working ONLY inside the git worktree at absolute path ${worktree.worktreePath} (branch ${worktree.branch}) — never touch any other directory.

Implement this plan to resolve GitHub issue #${ticket.number} ("${ticket.title}"):
${plan.plan}

Likely files to touch: ${(plan.filesToTouch || []).join(', ') || 'determine as needed'}

Follow the repo's CLAUDE.md conventions. Do not break existing functionality or behavior. Do not commit — just make the edits and report what changed.`,
  { phase: 'Implement' }
)

phase('Code Review')
let approved = false
let lastFindings = []
for (let round = 1; round <= MAX_ROUNDS && !approved; round++) {
  const review = await agent(
    `Review the uncommitted changes in the git worktree at ${worktree.worktreePath} (branch ${worktree.branch}).
Run: git -C ${worktree.worktreePath} diff

Cross-check the diff against this specific plan for issue #${ticket.number} in addition to your normal review criteria:
${plan.plan}

Return approved=true only if there are no real problems, otherwise return concrete findings (file:line + description) the implementer must fix.`,
    { schema: REVIEW_SCHEMA, phase: 'Code Review', label: `code-review round ${round}`, agentType: 'python-code-reviewer' }
  )

  if (review.approved) {
    approved = true
    break
  }

  lastFindings = review.findings || []
  log(`Code review round ${round}: changes requested (${lastFindings.length} findings)`)

  await agent(
    `Working ONLY inside the git worktree at ${worktree.worktreePath} (branch ${worktree.branch}).
Address these code review findings for issue #${ticket.number} without breaking existing functionality:
${lastFindings.map((f) => `- ${f}`).join('\n')}

Do not commit — just make the fixes and report what changed.`,
    { phase: 'Code Review', label: `fix round ${round}` }
  )
}

if (!approved) {
  log(`Code review did not approve after ${MAX_ROUNDS} rounds — stopping before commit/PR. Worktree left at ${worktree.worktreePath} for inspection.`)
  return { status: 'review-failed', ticket, worktree, findings: lastFindings }
}

phase('Commit & PR')
const pr = await agent(
  `Working in the git worktree at ${worktree.worktreePath} (branch ${worktree.branch}):
1. git -C ${worktree.worktreePath} add -A
2. Commit with a concise message describing the fix for issue #${ticket.number} (${ticket.title}); include "Closes #${ticket.number}" in the commit body.
3. git -C ${worktree.worktreePath} push -u origin ${worktree.branch}
4. From ${worktree.worktreePath}, open a PR to main: gh pr create --base main --head ${worktree.branch} --title "..." --body "Closes #${ticket.number}\\n\\n<summary of the change>"
5. Report the PR number and URL.`,
  { schema: { type: 'object', properties: { prNumber: { type: 'number' }, prUrl: { type: 'string' } }, required: ['prNumber', 'prUrl'] }, phase: 'Commit & PR' }
)

log(`PR opened: ${pr.prUrl}`)

phase('PR Review Loop')
let prApproved = false
for (let round = 1; round <= MAX_ROUNDS && !prApproved; round++) {
  const prReview = await agent(
    `Review GitHub PR #${pr.prNumber} (gh pr diff ${pr.prNumber}) against the original issue #${ticket.number} and this repo's CLAUDE.md conventions. Check correctness, regressions, and whether it fully resolves the issue.

If it looks good: post gh pr comment ${pr.prNumber} --body "Approved: <short reason>" and return approved=true.
If there are problems: post gh pr comment ${pr.prNumber} --body "<findings>" and return approved=false with findings.

Use a plain comment, not "gh pr review --approve" — GitHub rejects self-approval when the PR author and the authenticated gh user are the same account, which is the case here.

Do NOT merge the PR under any circumstances — a human does the final merge.`,
    { schema: REVIEW_SCHEMA, phase: 'PR Review Loop', label: `pr-review round ${round}` }
  )

  if (prReview.approved) {
    prApproved = true
    break
  }

  log(`PR review round ${round}: changes requested on PR #${pr.prNumber}`)

  await agent(
    `Working ONLY inside the git worktree at ${worktree.worktreePath} (branch ${worktree.branch}):
Address this PR review feedback for issue #${ticket.number} / PR #${pr.prNumber}:
${(prReview.findings || []).map((f) => `- ${f}`).join('\n')}

Then: git -C ${worktree.worktreePath} add -A && git -C ${worktree.worktreePath} commit -m "Address PR review feedback" && git -C ${worktree.worktreePath} push
This updates PR #${pr.prNumber} automatically since it's the same branch.`,
    { phase: 'PR Review Loop', label: `pr-fix round ${round}` }
  )
}

phase('Cleanup')
await agent(
  `The work for PR ${pr.prUrl} is pushed. Remove the local worktree (the remote branch and PR are unaffected):
git worktree remove ${worktree.worktreePath} --force
If that fails, just report why instead of forcing anything destructive.`,
  { phase: 'Cleanup' }
)

if (prApproved) {
  log(`PR #${pr.prNumber} approved and ready for merge: ${pr.prUrl}. This workflow does not auto-merge — merge it yourself when ready.`)
  return { status: 'pr-approved-awaiting-merge', ticket, pr }
}

log(`PR #${pr.prNumber} still has open review feedback after ${MAX_ROUNDS} rounds: ${pr.prUrl}`)
return { status: 'pr-needs-more-work', ticket, pr }
