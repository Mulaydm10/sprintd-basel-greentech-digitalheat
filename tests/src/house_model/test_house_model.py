from house_model.model import heating_demand_kw


def test_no_demand_off_heating_day():
    assert heating_demand_kw(0.0, False) == 0.0


def test_demand_at_minus_5_5():
    assert abs(heating_demand_kw(-5.6, True) - 10.0) < 1e-9
