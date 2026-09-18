import math

from scripts.aios.research.run_quant_pairs_oos import fit, simulate


def test_pairs_simulator_cost_stress():
    right=[100*(1.001**i) for i in range(1000)]
    left=[x*math.exp(.02*math.sin(i/10)) for i,x in enumerate(right)]
    model=fit(left,right,0,500)
    base=simulate(left,right,model,500,1000,1.5,.5)
    stress=simulate(left,right,model,500,1000,1.5,.5,cost_multiplier=1.5)
    assert base['trades']>0 and base['net_return_pct']>=stress['net_return_pct']
