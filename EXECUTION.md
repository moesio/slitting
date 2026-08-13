# Computational experiments

Run the complete experiment from the project directory with:

```bash
python run_experiments.py
```

This executes `new_coils_value` once and `weighted_loss` for all eight
combinations in `{2, 4}^3` for `retail_y`, `retail_v`, and
`rolled_leftover`. By default, every instance folder under `data` is used.

To run only selected instances:

```bash
python run_experiments.py --instances bf_sae1006_050 bz_nbr7008_095
```

To run one weighted-loss configuration directly:

```bash
python slitting.py \
  --objective weighted_loss \
  --retail-y-weight 2 \
  --retail-v-weight 4 \
  --rolled-leftover-weight 2
```

Outputs are isolated by instance, objective, and weight vector:

```text
output/<instance>/<objective>/<configuration>/period_<t>/
```

The existing output filenames are retained: `cutting_plan.json`,
`gurobi.log`, and `slitting.log`. A scenario-specific `Retails.csv` is stored
in `period_<t>` when it contains reusable leftovers produced in period
`<t-1>` and available in period `<t>`. Thus, no generated leftovers are
written back into `data`, and different scenarios cannot contaminate one
another.
