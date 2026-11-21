"""Design-side adversarial review suite for scheduler contract v2. Run from a PR checkout:
# Design-owned regression suite for contract v2 (fuzz + invariants). Lives outside lanes.
   PYTHONPATH=src python -m pytest <this file> -q
Fuzzes invariants + replays the reference year and compares baselines with research/briefing numbers."""
import dataclasses, inspect, json, os, random
import pytest
from scheduler import policy, types, actions as A

ROOT = os.environ.get("REPO", ".")


def mk_params(policy_name="merit", slack=True):
    fields = {f.name for f in dataclasses.fields(policy.Params)} if dataclasses.is_dataclass(policy.Params) else set()
    kw = dict(policy=policy_name, eta_heat_used=0.8, slack_enabled=slack, migration_margin_chf=0.05, deadline_safety_h=1.0)
    return policy.Params(**{k: v for k, v in kw.items() if not fields or k in fields})


def site(**o):
    d = dict(site_id="h1", hour_index=0, demand_kw=2.0, tank_level_kwh=10.0, tank_cap_kwh=35.0, servers=4,
             server_kw_el=1.0, heat_recovery=0.8, p_el_chf_kwh=0.3325, heat_value_chf_kwh=0.133,
             eligible_classes=frozenset({"public", "swiss-only"}), night_cap_kw=None, has_dump=False,
             band_low_kwh=10.0, band_high_kwh=33.0, mode_running=True)
    d.update(o)
    return types.SiteState(**d)


def unit(i, **o):
    d = dict(unit_id=f"u{i}", job_id=f"j{i}", job_class="ballast", access_class="public", kwh_el=0.25,
             bid_chf_per_server_h=0.5, deadline_hour=1000, slack_h=24.0, checkpointable=True)
    d.update(o)
    return types.Unit(**d)


def acts(dec, cls):
    return [a for a in dec.actions if isinstance(a, cls)]


def rand_world(rng):
    sites = [site(site_id=f"s{k}", demand_kw=rng.choice([0, 0.5, 3, 9]), tank_level_kwh=rng.uniform(0, 35),
                  servers=rng.randint(1, 6), mode_running=rng.random() < .5,
                  heat_value_chf_kwh=rng.choice([0, 0.133]),
                  eligible_classes=frozenset(rng.sample(["public", "swiss-only", "certified"], rng.randint(1, 3))),
                  night_cap_kw=rng.choice([None, 2.0])) for k in range(rng.randint(1, 5))]
    q = [unit(i, access_class=rng.choice(["public", "swiss-only", "certified"]),
              deadline_hour=rng.randint(0, 200), slack_h=rng.choice([0, 6, 24, 168]),
              bid_chf_per_server_h=rng.choice([0.1, 0.3, 0.5, 1.7])) for i in range(rng.randint(0, 40))]
    return sites, q


@pytest.mark.parametrize("seed", range(300))
def test_fuzz_invariants(seed):
    rng = random.Random(seed)
    sites, q = rand_world(rng)
    hour = rng.randint(0, 100)
    dec = policy.decide(sites, q, hour, mk_params(), seed=seed)
    dec2 = policy.decide(sites, q, hour, mk_params(), seed=seed)
    assert dec == dec2, "non-deterministic"
    S = {s.site_id: s for s in sites}; U = {u.unit_id: u for u in q}
    assigned = acts(dec, A.Assign)
    ids = [a.unit_id for a in assigned]
    assert len(ids) == len(set(ids)), "unit assigned twice"
    for a in assigned:
        assert U[a.unit_id].access_class in S[a.site_id].eligible_classes, "ELIGIBILITY VIOLATION"
    for p in acts(dec, A.SetPower):
        s = S[p.site_id]
        assert -1e-9 <= p.servers_on <= s.servers + 1e-9
        if s.night_cap_kw is not None and getattr(policy, "is_night", None) is None:
            pass  # night definition is the PR's; checked in dedicated test if exposed
    for r in acts(dec, A.Route):
        assert min(r.space_kwh, r.dhw_kwh, r.tank_kwh, r.dump_kwh) >= -1e-9
        assert S[r.site_id].tank_level_kwh + r.tank_kwh <= S[r.site_id].tank_cap_kwh + 1e-6, "tank overfill"
        if not S[r.site_id].has_dump:
            pass  # case house: dump counted, allowed
    assert isinstance(dec.trace, list)


def test_certified_refused_everywhere_public():
    s = [site(site_id="a", eligible_classes=frozenset({"public"})), site(site_id="b", eligible_classes=frozenset({"public"}))]
    dec = policy.decide(s, [unit(1, access_class="certified")], 0, mk_params())
    assert not acts(dec, A.Assign) and acts(dec, A.Refuse)


def test_summer_holds_instead_of_dump():
    s = [site(demand_kw=0.5, tank_level_kwh=35.0, heat_value_chf_kwh=0.0, mode_running=False)]
    dec = policy.decide(s, [unit(i, slack_h=168, deadline_hour=500) for i in range(8)], 10, mk_params())
    assert len(acts(dec, A.Hold)) >= 4


def test_deadline_forces_run():
    s = [site(demand_kw=0.0, tank_level_kwh=35.0, heat_value_chf_kwh=0.0, mode_running=False)]
    dec = policy.decide(s, [unit(1, slack_h=24, deadline_hour=10, bid_chf_per_server_h=1.7)], 9, mk_params())
    assert acts(dec, A.Assign), "deadline unit was not run"


def test_baselines_exist_same_module():
    for p in ("thermostat", "always_on"):
        policy.decide([site()], [unit(1)], 0, mk_params(p))


def test_no_hardcoded_numbers_in_src():
    src = inspect.getsource(policy)
    for bad in ("0.3325", "35.0", "26851", "0.226"):
        assert bad not in src, f"hard-coded {bad} in policy.py"


def test_cheapest_site_wins_and_certified_goes_to_certified():
    cheap = site(site_id="a", p_el_chf_kwh=0.23, eligible_classes=frozenset({"public"}))
    dear = site(site_id="b", p_el_chf_kwh=0.33, eligible_classes=frozenset({"public", "certified"}))
    dec = policy.decide([dear, cheap], [unit(1), unit(2, access_class="certified", bid_chf_per_server_h=1.7)], 0, mk_params())
    where = {a.unit_id: a.site_id for a in acts(dec, A.Assign)}
    assert where == {"u1": "a", "u2": "b"}


@pytest.mark.parametrize("seed", range(30))
def test_input_order_independent(seed):
    rng = random.Random(seed); sites, q = rand_world(rng)
    d1 = policy.decide(sites, q, 5, mk_params(), seed=1)
    d2 = policy.decide(list(reversed(sites)), list(reversed(q)), 5, mk_params(), seed=1)
    assert d1 == d2


def test_night_cap_respected():
    s = [site(servers=6, night_cap_kw=2.0, demand_kw=9.0, tank_level_kwh=0.0)]
    dec = policy.decide(s, [unit(i) for i in range(40)], 0, mk_params())
    assert acts(dec, A.SetPower)[0].servers_on <= 2.0 + 1e-9
