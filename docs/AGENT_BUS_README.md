# agent-bus-template

GitHub as the bus: one design agent (Devin), N worker agents (Claude Code) on any number of devices and accounts, coordinated only through issues, refs and PRs. No server, no queue, no chat.

```
gh repo create my-hackathon --template <owner>/agent-bus-template --private --clone
cd my-hackathon
./bootstrap.sh --mode solo api model ui        # labels, lanes, canary issue, protection if possible
```

Then:
- **Design (Devin):** point a session (or an Automation) at this repo with `.devin/playbooks/design.md`. It fills `docs/STATE.md`, writes `contracts/<lane>.md`, cuts `status:queued` issues, reviews every PR.
- **Workers (Claude Code, any device/teammate):** install the `bus` plugin (https://github.com/Mulaydm10/agent-bus-plugin, see `docs/SETUP.md` §3), `git config device.id <name>`, then `/bus:claim` in the repo: it reads `AGENTS.md`, claims the next queued issue via the `claim/<n>` ref, works in a worktree; `/bus:pr` opens the PR.
- **You:** merge green PRs. That is the only irreversible step and it stays human.

Adding a teammate or a device is the same operation: give the account write access, run the two lines above on the machine.

| file | role |
|---|---|
| `AGENTS.md` | the whole protocol, <100 lines; every agent reads it first |
| `docs/STATE.md` | mode (`solo`/`team`), lanes, decisions, gaps — design-owned |
| `docs/verify.txt` | one test command per lane; CI runs it, issue text never executes |
| `contracts/<lane>.md` | what each lane exposes to the others |
| `.github/workflows/checks.yml` | `lane` → `resolve` → `run`: diff stays in lane, config read from `main`, tests run token-light |
| `canary/` | standing lane that proves the checks actually execute |
| `docs/ARCHITECTURE.md` | why each piece exists and what is mechanical vs. convention |
| `docs/WORKER.md` | worker-side behaviour spec (Claude Code) |
| `docs/SETUP.md` | checklist: plan, protection, provisioning, solo vs. team |
| `bootstrap.sh` | idempotent one-shot setup |

Proven on a scratch repo: lock is atomic (201/422), lane isolation holds, a task went claim → PR → CI → merge with zero direct agent-to-agent communication.
