"""Design-side year replay of PR #13 decide() on the reference house. usage: PYTHONPATH=src python year_replay.py <weather.json>"""
import collections, json, sys
from scheduler import policy, types, actions as A

P, DIV, TANK, REC, HW = 0.3325, 2.5, 35.0, 0.8, 0.5
d = json.load(open(sys.argv[1]))["hourly"]; T = d["temperature_2m"]; ts = d["time"]
days = collections.defaultdict(list)
for t, x in zip(ts, T): days[t[:10]].append(x)
hd = {k for k, v in days.items() if sum(v) / len(v) < 12}
SPACE = [max(0, 10 * (20 - x) / 25.6) if t[:10] in hd else 0.0 for t, x in zip(ts, T)]
H = len(SPACE)


def run(N, pol, slack_h=24.0, arrivals_per_h=None, low=10.0, high=33.0, bid=0.5):
    prm = types.Params(policy=pol, eta_heat_used=REC, slack_enabled=slack_h > 0, migration_margin_chf=0.05, deadline_safety_h=1.0)
    lvl, mode, q, k = 0.0, True, [], 0
    used = dump = runh = backup = missed = trans = 0.0
    apr = arrivals_per_h if arrivals_per_h is not None else 4 * N * 0.6  # 60% of capacity as paid work
    acc = 0.0
    for h in range(H):
        acc += apr
        while acc >= 1:
            q.append(types.Unit(f"u{k}", f"j{k}", "ballast", "public", 0.25, bid, h + int(slack_h) + 1, slack_h, True)); k += 1; acc -= 1
        dem = SPACE[h] + HW
        s = types.SiteState("h", h, SPACE[h], lvl, TANK, N, 1.0, REC, P,
                            types.heat_value_chf_kwh(P, DIV, dem, lvl, high), frozenset({"public"}), None, False, low, high, mode, HW)
        dec = policy.decide([s], q, h, prm)
        assigned = {a.unit_id for a in dec.actions if isinstance(a, A.Assign)}
        on = [a for a in dec.actions if isinstance(a, A.SetPower)][0].servers_on
        r = [a for a in dec.actions if isinstance(a, A.Route)][0]
        if dec.next_mode["h"] != mode: trans += 1
        mode = dec.next_mode["h"]
        assert abs(r.space_kwh + r.dhw_kwh + r.tank_kwh + r.dump_kwh - on * REC) < 1e-6
        lvl += r.tank_kwh
        unmet = dem - r.space_kwh - r.dhw_kwh
        take = min(lvl, unmet); lvl -= take; unmet -= take
        assert -1e-9 <= lvl <= TANK + 1e-6
        backup += unmet; used += r.space_kwh + r.dhw_kwh + r.tank_kwh; dump += r.dump_kwh; runh += on
        q = [u for u in q if u.unit_id not in assigned]
        late = [u for u in q if u.deadline_hour <= h]; missed += len(late); q = [u for u in q if u.deadline_hour > h]
    tot = sum(SPACE) + HW * H
    elec = runh * P; hv = (used - 0) * P / DIV
    return dict(N=N, pol=pol, slack=slack_h, cover=round((tot - backup) / tot, 3), dump=round(dump), runh=round(runh),
                util=round(runh / (N * H), 3), be=round((elec - hv) / runh, 4) if runh else None,
                missed=int(missed), trans_per_day=round(trans / 365, 2))


if __name__ == "__main__":
    for N in (1, 4, 8):
        for pol, sl in (("thermostat", 0), ("always_on", 0), ("merit", 0), ("merit", 24), ("merit", 168)):
            print(run(N, pol, sl))
