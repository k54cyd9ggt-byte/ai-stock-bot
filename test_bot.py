from bot import target_weights

def test_limits():
    cfg = {'min_probability': .57, 'max_position_weight': .2, 'max_total_exposure': .6}
    weights = target_weights({'A': .9, 'B': .8, 'C': .7, 'D': .6}, cfg)
    assert sum(weights.values()) <= .6000001
    assert all(w <= .2 for w in weights.values())
    assert target_weights({'A': .1}, cfg) == {}
