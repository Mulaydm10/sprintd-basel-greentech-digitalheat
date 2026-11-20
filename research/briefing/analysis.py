"""Reference-house analysis for the DigitalHeat case. Produces charts + numbers.json."""
import json, collections
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

P = 0.3325          # CHF/kWh, ElCom 2026 IWB H4 total
COP = 2.5
REC = 0.8           # recoverable heat fraction
TANK = 35.0
HW = 12.0 / 24      # kW hot water, flat
CAPEX = 8000.0      # CHF per 1 kW server incl. install (assumption, range 5-15k)
LIFE_Y = 5

d = json.load(open("weather.json"))["hourly"]
T = np.array(d["temperature_2m"], float); G = np.array(d["shortwave_radiation"], float); ts = d["time"]
days = collections.defaultdict(list)
for t, x in zip(ts, T): days[t[:10]].append(x)
hd = {k for k, v in days.items() if np.mean(v) < 12}
heating = np.array([t[:10] in hd for t in ts])
space = np.where(heating, np.maximum(0, 10 * (20 - T) / 25.6), 0.0)
D = space + HW
month = np.array([int(t[5:7]) for t in ts])
H = len(D)

def sim(N, mode):
    """mode 'follow': run only to meet demand + fill tank. 'always': run all servers 24/7."""
    cap = REC * N; lvl = 0.0; used = dump = runh = 0.0
    used_h = np.zeros(H); run_h = np.zeros(H)
    for i, x in enumerate(D):
        if mode == "always":
            h = cap
        else:
            take_from_tank = min(lvl, x)
            h = min(cap, (x - take_from_tank) + (TANK - (lvl - take_from_tank)))
        take = min(lvl, x); lvl -= take; r = x - take
        u = min(h, r); ex = h - u; ch = min(ex, TANK - lvl); lvl += ch
        dump += ex - ch; used += take + u
        rh = h / REC; runh += rh; used_h[i] = take + u; run_h[i] = rh
    elec = runh * 1.0 * P
    heat_val = used * P / COP
    be = (elec - heat_val) / runh if runh else float("nan")
    capex_h = CAPEX * N / LIFE_Y / runh if runh else float("nan")
    return dict(N=N, mode=mode, covered=used / D.sum(), used=used, dump=dump, util=runh / (N * H),
                runh=runh, elec=elec, heat_val=heat_val, be=be, be_capex=be + capex_h, used_h=used_h, run_h=run_h)

res = {m: [sim(N, m) for N in range(1, 14)] for m in ("follow", "always")}

# portfolio: houses + year-round sites absorb off-season compute
def portfolio(N):
    f = res["follow"][N - 1]
    idle_h = N * H - f["runh"]
    return idle_h

out = dict(price=P, total=D.sum(), space=space.sum(), hw=HW * H, heating_days=len(hd), tmin=T.min(),
           peak=D.max(), hours_above={k: int((D > k * REC).sum()) for k in (1, 2, 4, 6, 8, 10, 12.5)},
           monthly={int(m): float(D[month == m].sum()) for m in range(1, 13)},
           sweep={m: [{k: (float(v) if not isinstance(v, np.ndarray) else None) for k, v in r.items() if k not in ("used_h", "run_h", "mode")} for r in res[m]] for m in res})
json.dump(out, open("numbers.json", "w"), indent=1)

plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 160})
C1, C2, C3, C4 = "#d9480f", "#1971c2", "#2b8a3e", "#868e96"

# 1 year profile
fig, ax = plt.subplots(figsize=(7.2, 2.6))
ax.plot(D, lw=0.4, color=C1, label="Heat demand (space + hot water), kW")
ax2 = ax.twinx(); ax2.plot(T, lw=0.3, color=C2, alpha=0.6); ax2.set_ylabel("Outdoor T (°C)", color=C2)
ax.set_xlabel("Hour of 2025"); ax.set_ylabel("kW"); ax.set_title("Reference house, Basel 2025: hourly heat demand")
for s in ax2.spines.values(): s.set_visible(False)
fig.tight_layout(); fig.savefig("f_year.png"); plt.close()

# 2 load duration
fig, ax = plt.subplots(figsize=(7.2, 2.6))
s = np.sort(D)[::-1]; ax.plot(s, color=C1)
for N in (2, 4, 6, 8, 12.5):
    ax.axhline(N * REC, ls="--", lw=0.6, color=C4); ax.text(8400, N * REC + 0.1, f"{N} servers", fontsize=7, color=C4, ha="right")
ax.set_xlabel("Hours per year (sorted)"); ax.set_ylabel("kW"); ax.set_title("Load-duration curve: the peak (12.5 servers) lasts only ~29 h/yr")
fig.tight_layout(); fig.savefig("f_ldc.png"); plt.close()

# 3 monthly
fig, ax = plt.subplots(figsize=(7.2, 2.4))
m = list(range(1, 13)); sp = [space[month == i].sum() for i in m]; hw = [HW * (month == i).sum() for i in m]
ax.bar(m, sp, color=C1, label="Space heating"); ax.bar(m, hw, bottom=sp, color=C2, label="Hot water")
ax.set_xticks(m, ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]); ax.set_ylabel("kWh"); ax.legend(frameon=False)
ax.set_title("Monthly heat demand: summer is hot water only (~370 kWh/month)")
fig.tight_layout(); fig.savefig("f_month.png"); plt.close()

# 4 coverage + utilisation vs N
fig, ax = plt.subplots(figsize=(7.2, 2.8))
Ns = range(1, 14)
ax.plot(Ns, [100 * r["covered"] for r in res["follow"]], "o-", color=C1, label="Heat demand covered (%)")
ax.plot(Ns, [100 * r["util"] for r in res["follow"]], "s-", color=C2, label="Server utilisation, heat-following (%)")
ax.set_xlabel("Servers per house"); ax.set_ylabel("%"); ax.legend(frameon=False); ax.grid(alpha=0.2)
ax.axvspan(3, 6, color=C3, alpha=0.08); ax.text(4.5, 8, "sweet spot", ha="center", color=C3)
ax.set_title("The core trade-off: coverage rises, utilisation falls")
fig.tight_layout(); fig.savefig("f_tradeoff.png"); plt.close()

# 5 break-even
fig, ax = plt.subplots(figsize=(7.2, 2.8))
ax.plot(Ns, [r["be"] for r in res["follow"]], "o-", color=C1, label="Heat-following, case formula")
ax.plot(Ns, [r["be"] for r in res["always"]], "o--", color=C4, label="Always-on (dumps heat), case formula")
ax.plot(Ns, [r["be_capex"] for r in res["follow"]], "s-", color=C2, label=f"Heat-following + hardware (CHF {CAPEX:.0f}/srv, {LIFE_Y} y)")
ax.plot(Ns, [r["be_capex"] for r in res["always"]], "s--", color=C3, label="Always-on + hardware")
ax.set_xlabel("Servers per house"); ax.set_ylabel("CHF per server-hour sold"); ax.legend(frameon=False, fontsize=7); ax.grid(alpha=0.2)
ax.set_title(f"Break-even compute price at {P*100:.2f} Rp/kWh (IWB H4 2026)")
fig.tight_layout(); fig.savefig("f_breakeven.png"); plt.close()

# 6 Jan + Jul day for N=4
f4 = res["follow"][3]
def dayplot(date, fn, title):
    idx = [i for i, t in enumerate(ts) if t.startswith(date)]
    fig, ax = plt.subplots(figsize=(3.5, 2.3))
    ax.step(range(24), D[idx], where="mid", color=C1, label="demand")
    ax.step(range(24), f4["run_h"][idx] * REC, where="mid", color=C2, ls="--", lw=1.6, label="server heat used (4 srv)")
    ax.set_ylim(0, max(D[idx].max(), 1) * 1.15)
    ax.set_xlabel("hour"); ax.set_ylabel("kW"); ax.set_title(title, fontsize=8); ax.legend(frameon=False, fontsize=6)
    fig.tight_layout(); fig.savefig(fn); plt.close()
coldest = ts[int(np.argmin(T))][:10]
dayplot(coldest, "f_jan.png", f"Coldest day {coldest}")
dayplot("2025-07-15", "f_jul.png", "Summer day 2025-07-15")
print(json.dumps({k: out[k] for k in ("total", "space", "hw", "heating_days", "tmin", "peak", "hours_above")}, indent=0))
for r in out["sweep"]["follow"]: print({k: round(v, 3) for k, v in r.items() if k in ("N","covered","util","be","be_capex")})
for r in out["sweep"]["always"][:6]: print("always", {k: round(v, 3) for k, v in r.items() if k in ("N","covered","dump","be","be_capex")})
print("coldest", coldest)
