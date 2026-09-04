import os
import re
import json
import argparse
import logging
import numpy as np
import pandas as pd
import gurobipy as gp
import datetime as dt
import networkx as nx
from pathlib import Path
from gurobipy import GRB

PROJECT_DIR = Path(__file__).resolve().parent
os.chdir(PROJECT_DIR)

logger = logging.getLogger('gurobipy')
logger.propagate = False

parser = argparse.ArgumentParser(
    description='Solve one objective/weight configuration for all instances and periods.'
)
parser.add_argument(
    '--objective',
    choices=['weighted_loss', 'new_coils_value'],
    required=True
)
parser.add_argument('--retail-y-weight', type=int, choices=[2, 4])
parser.add_argument('--retail-v-weight', type=int, choices=[2, 4])
parser.add_argument('--rolled-leftover-weight', type=int, choices=[2, 4])
parser.add_argument(
    '--instances',
    nargs='+',
    help='Instance folders to solve. By default, all folders under data are used.'
)
args = parser.parse_args()

if args.objective == 'weighted_loss':
    leftover_weights = {
        'retail_y': args.retail_y_weight,
        'retail_v': args.retail_v_weight,
        'rolled_leftover': args.rolled_leftover_weight,
    }
    if any(weight is None for weight in leftover_weights.values()):
        parser.error(
            'weighted_loss requires --retail-y-weight, --retail-v-weight, '
            'and --rolled-leftover-weight'
        )
    configuration_name = (
        f"retail_y_{leftover_weights['retail_y']}__"
        f"retail_v_{leftover_weights['retail_v']}__"
        f"rolled_leftover_{leftover_weights['rolled_leftover']}"
    )
else:
    leftover_weights = None
    configuration_name = 'default'

# instancia             types   parts   coils  wide     narrow
# 'bf_sae1006_050'      1        2        6    1200.0   105.5
# 'bz_nbr7008_095'      1        4       11    1000.0   110.0
# 'bz_nbr7008_075'      1        5       11    1000.0    38.0
# 'bf_qcv_045'          3        5      255    1200.0   433.0
# 'bf_sae1006_045'      3        9      297    1250.0   277.0
# 'bz_nbr7008_043'      3       10      108    1200.0   107.0

available_instances = sorted(path.name for path in Path('data').iterdir() if path.is_dir())
dirs = args.instances or available_instances

unknown_instances = sorted(set(dirs) - set(available_instances))
if unknown_instances:
    parser.error(f"Unknown instance folder(s): {', '.join(unknown_instances)}")

for data_folder in dirs:
    for period in ['period_1','period_2','period_3','period_4','period_5']:

        output_root = Path(
            'output', data_folder, args.objective, configuration_name
        )
        period_output_dir = output_root / period

        log_path = period_output_dir / 'slitting.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            filename=log_path,
            filemode='w',
            level=logging.INFO,
            datefmt='%d-%m-%Y %H:%M:%S',
            format='%(asctime)s-%(levelname)-8s-%(message)s',
            force=True
        )
        
        logging.info(f'{data_folder}-{period}-leitura de dados iniciada.')

        df_parameters = pd.read_csv(
            f'data/{data_folder}/{period}/Parameters.csv',
            usecols=["Name", "Value"],
            dtype={"Name": "str", "Value": "str"}
        )
        
        parameters = dict(zip(df_parameters["Name"], df_parameters["Value"]))
        del df_parameters

        parameters['NumKnives'] = int(parameters['NumKnives'])
        parameters['MinEdgeTrim'] = float(parameters['MinEdgeTrim']) / 1000.0
        parameters['MinStripLength'] = float(parameters['MinStripLength'])
        parameters['MinCoilLength'] = float(parameters['MinCoilLength'])
        parameters['MinRetailLength'] = float(parameters['MinRetailLength'])
        parameters['Density'] = float(parameters['Density'])
        parameters['Thickness'] = float(parameters['Thickness']) / 1000.0
        time_str = parameters['TimeLimit']
        match = re.fullmatch(r'[0-9]+:[0-5][0-9]', time_str)
        h, m = match.group(0).split(':')
        parameters['TimeLimit'] = dt.timedelta(hours=int(h), minutes=int(m))        
        
        # Width (mm)
        # Demand (kg)
        # BeginLoss (m)
        # EndLoss (m)
        parts = pd.read_csv(
            f'data/{data_folder}/{period}/Parts.csv',
            usecols=['Code', 'Width', 'Demand', 'BeginLoss', 'EndLoss'],
            dtype={'Code': 'str', 'Width': 'float', 'Demand': 'float', 'BeginLoss': 'float', 'EndLoss': 'float'}
        )

        # Width (mm -> m)
        parts['Width'] = parts['Width'] / 1000
        # Length (m)
        parts['Length'] = ((parts['Demand'] / parameters['Density']) / (parameters['Thickness'] * parts['Width']))
        min_strip_width = parts['Width'].min()
        parts_codes = parts['Code'].unique()

        # Width (mmm)
        # Value (R$/ton)
        types = pd.read_csv(
            f'data/{data_folder}/{period}/Types.csv',
            usecols=['Code', 'Width', 'Value'],
            dtype={'Code': 'str', 'Width': 'float', 'Value': 'float'}
        )
        
        # Width (mm -> m)
        types['Width'] = types['Width'] / 1000
        # Value (R$/ton -> R$/kg)
        types['Value'] = types['Value'] / 1000

        # Weight (kg)
        coils = pd.read_csv(
            f'data/{data_folder}/{period}/Coils.csv',
            usecols=['Id', 'Code', 'Weight', 'Processed'],
            dtype={'Id': 'str', 'Code': 'str', 'Weight': 'float', 'Processed': 'int'}
        )

        coils = pd.merge(coils, types, left_on='Code', right_on='Code', how='inner')
        # Length (m)
        coils['Length'] = ((coils['Weight'] / parameters['Density']) / (parameters['Thickness'] * coils['Width']))
        # PesoM2 (kg/m2)
        coils['WeightPerM2'] = (parameters['Density'] * parameters['Thickness'])
        # Maximo de tiras
        coils['MaxNbStrips'] = np.minimum(np.ceil((coils['Width']) / min_strip_width), parameters['NumKnives'] - 1).astype(int)
        # Value (R$/kg -> R$)
        # coils['Value'] = coils['Value'] * coils['Weight']

        # Width (mm)
        # Value (R$/ton)
        # Weight (kg)    
        cols = ['Id', 'Width', 'Value', 'Weight', 'Processed']
        dtypes = {'Id': 'str', 'Width': 'float', 'Value': 'float', 'Weight': 'float', 'Processed': 'int'}
        # Period 1 may contain initial reusable leftovers supplied with the
        # instance. In later periods, only leftovers generated by this same
        # objective/weight configuration are read, preventing contamination
        # across computational scenarios.
        if period == 'period_1':
            retails_input_path = Path('data', data_folder, period, 'Retails.csv')
        else:
            retails_input_path = period_output_dir / 'Retails.csv'

        try:
            retails = pd.read_csv(retails_input_path, usecols=cols, dtype=dtypes)
        except FileNotFoundError:
            retails = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in dtypes.items()})
        
        # Width (mm -> m)
        retails['Width'] = retails['Width'] / 1000
        # Value (R$/ton -> R$/kg)
        retails['Value'] = retails['Value'] / 1000
        # Codigo indefinido
        retails['Code'] = '0000000000'
        # Length (m)
        retails['Length'] = ((retails['Weight'] / parameters['Density']) / (parameters['Thickness'] * retails['Width']))
        # PesoM2 (kg/m2) 
        retails['WeightPerM2'] = (parameters['Density'] * parameters['Thickness'])
        # Maximo de tiras
        retails['MaxNbStrips'] = np.minimum(np.ceil((retails['Width']) / min_strip_width), parameters['NumKnives'] - 1).astype(int)
        # Value (R$/kg -> R$)
        # retails['Value'] = retails['Value'] * retails['Weight']
        
        # Ajusta colunas de retails para coincidir com coils
        retails = retails.reindex(columns=coils.columns)
        # Concatena
        coils = pd.concat([coils, retails], ignore_index=True)
        # Recria Id sequencial
        coils['Id'] = np.arange(1, len(coils) + 1).astype(str)

        coils_ids = coils['Id'].unique()

        pairs = gp.tuplelist(
            (row['Id'], slit)
            for _, row in coils.iterrows()
            for slit in range(1, int(str(row['MaxNbStrips'])) + 1)
        )

        logging.info(f'{data_folder}-{period}-leitura de dados finalizada.')
        
        logging.info(f'{data_folder}-{period}-geracao do modelo iniciada')
        
        gurobi_log_path = period_output_dir / 'gurobi.log'
        gurobi_log_path.parent.mkdir(parents=True, exist_ok=True)
        if gurobi_log_path.exists():
            gurobi_log_path.unlink()

        env = gp.Env(empty=True)
        env.setParam('LogFile', str(gurobi_log_path))
        env.setParam('LogToConsole', 0)
        env.setParam('TimeLimit', parameters['TimeLimit'].seconds)
        # env.setParam('TimeLimit', 120)
        env.start()

        model = gp.Model(name='slitting',env=env)
 
        # alpha[c, s]: se pelo menos s tiras são geradas da bobina c
        alpha = model.addVars(pairs, vtype=GRB.BINARY, name='alpha')

        # gammaT[c]: se a bobina c é usada por completo
        gammaT = model.addVars(coils_ids, vtype=GRB.BINARY, name='gammaT')

        # gammaP[c]: se a bobina c é usada parcialmente
        gammaP = model.addVars(coils_ids, vtype=GRB.BINARY, name='gammaP')

        # lambda[c]: se a bobina c passa por processo de corte
        lanbda = model.addVars(coils_ids, vtype=GRB.BINARY, name='lambda')

        # mu[p, c, s]: se s-ésima tira da bobina c está relacionada à peça "p"
        mu = model.addVars(parts_codes, pairs, vtype=GRB.BINARY, name='mu')

        # tau[c]: se a bobina c possui sobra na largura
        tau = model.addVars(coils_ids, vtype=GRB.BINARY, name='tau')

        # theta[c]: se a tira de sobra da bobina c é reutilizável
        theta = model.addVars(coils_ids, vtype=GRB.BINARY, name='theta')

        # beta[p, c, s]: se a sobra da s-ésima tira da bobina c empregada na produção da peça "p" é reutilizável
        beta = model.addVars(parts_codes, pairs, vtype=GRB.BINARY, name='beta')

        # x[c]: comprimento utilizado da bobina c
        x = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='x')

        # v[p, c, s]: comprimento da s-ésima tira da bobina c relacionada à peça "p"
        v = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='v')

        # v1[p, c, s]: comprimento da s-ésima tira da bobina c empregada na produção da peça "p"
        v1 = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='v1')

        # v2[p, c, s]: comprimento da sobra da s-ésima tira da bobina c empregada na produção da peça "p"
        v2 = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='v2')

        # vr[p, c, s]: comprimento da sobra da s-ésima tira da bobina c empregada na produção da peça "p" que é reutilizável
        vr = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='vr')

        # vs[p, c, s]: comprimento da sobra da s-ésima tira da bobina c empregada na produção da peça "p" que é sucata
        vs = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='vs')

        # u[p, c, s]: peso da s-ésima tira da bobina c relacionada à peça "p"
        u = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='u')

        # u1[p, c, s]: peso da s-ésima tira da bobina c empregada na produção da peça "p"
        u1 = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='u1')

        # u2[p, c, s]: peso da sobra da s-ésima tira da bobina c empregada na produção da peça "p"
        u2 = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='u2')

        # ur[p, c, s]: peso da sobra da s-ésima tira da bobina c empregada na produção da peça "p" que é reutilizável
        ur = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='ur')

        # us[p, c, s]: peso da sobra da s-ésima tira da bobina c empregada na produção da peça "p" que é sucata
        us = model.addVars(parts_codes, pairs, vtype=GRB.CONTINUOUS, lb=0, name='us')

        # y[c]: largura da tira de sobra da bobina c
        y = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='y')

        # yr[c]: largura da tira de sobra da bobina c que é reutilizável
        yr = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='yr')

        # ys[c]: largura da tira de sobra da bobina c que é sucata
        ys = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='ys')

        # z[c]: peso da tira de sobra da bobina c
        z = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='z')

        # zr[c]: peso da tira de sobra da bobina c que é reutilizável
        zr = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='zr')

        # zs[c]: peso da tira de sobra da bobina c que é sucata
        zs = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='zs')

        # e[c]: peso do refilo
        e = model.addVars(coils_ids, vtype=GRB.CONTINUOUS, lb=0, name='e')

        # (5)
        model.addConstrs(
            (gammaT[c] + gammaP[c] == alpha[c, 1] for c in coils_ids), name='utilization'
        )

        # (6)
        for coil in coils.itertuples():
            c = coil.Id
            if coil.Processed:
                model.addConstr(
                    gammaP[c] == 0, name=f'processed[{c}]'
                )

        # (7)
        model.addConstrs(
            (alpha[c, s] <= alpha[c, s - 1] for (c, s) in pairs if s != 1), name='sequence'
        )

        # (9)
        model.addConstrs(
            (alpha[c, s] <= lanbda[c] for (c, s) in pairs.select('*', 2)), name='slitted'
        )

        # (10)
        model.addConstrs(
            (gammaP[c] <= lanbda[c] for c in coils_ids), name='crosscut'
        )

        # (12)
        model.addConstrs(
            (lanbda[c] <= alpha.get((c, 2), 0) + gammaP[c] for c in coils_ids), name='nocut'
        )

        # (13)
        model.addConstrs(
            (lanbda[c] <= alpha[c, 1] for c in coils_ids), name='unused'
        )

        # (14)
        model.addConstrs(
            (mu.sum('*', c, 2) + tau[c] == alpha.get((c, 2), 0) for c in coils_ids), name='leftover'
        )

        # (15)
        for coil in coils.itertuples():
            c = coil.Id
            if coil.MaxNbStrips == 1:
                model.addConstr(
                    tau[c] == 0, name=f'noleftover[{c}]'
                )

        # (16)
        model.addConstrs(
            (mu.sum('*', c, s) == alpha[c, s] for (c, s) in pairs if s != 2), name='assignment'
        )

        # (19)
        for coil in coils.itertuples():
            c = coil.Id
            pattern = gp.LinExpr(0.0)
            for (_, s) in pairs.select(c, '*'):
                for part in parts.itertuples():
                    p = part.Code
                    pattern.addTerms(part.Width, mu[p, c, s])
                if s == 2:
                    pattern.addTerms(2 * parameters['MinEdgeTrim'], alpha[c, 2])
            pattern.addTerms(1, y[c])
            model.addConstr(
                pattern == coil.Width * alpha[c, 1], name=f'pattern[{c}]'
            )

        # (20)
        for coil in coils.itertuples():
            c = coil.Id
            # noinspection SpellCheckingInspection
            model.addConstr(
                y[c] <= (coil.Width - 2 * parameters['MinEdgeTrim'] - min_strip_width) * tau[c],
                name=f'zeroleftover[{c}]'
            )

        # (21)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                x[c] >= coil.Length * gammaT[c] + parameters['MinStripLength'] * gammaP[c],
                name=f'minUsedLength[{c}]'
            )
            model.addConstr(
                x[c] <= coil.Length * gammaT[c] + (coil.Length - parameters['MinCoilLength']) * gammaP[
                    c],
                name=f'maxUsedLength[{c}]'
            )

        # todo (new) VERIFICAR LAMBDA
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                coil.Length >= alpha.get((c, 2), 0) * parameters['MinCoilLength'],
                name=f'minCoilLengthToCut[{c}]'
            )

        # TODO (22)CHECAR QUANDO GERO UMA TIRA E NÃO UTILIZO NADA!!! NÃO TEM PERDA DE INICIO/FIM
        #  ACREDITO QUE PELA PENALIZAÇÃO NA F.O. NÃO HA PROBLEMA, POIS DEIXARIA COMO TIRA 2 (SOBRA)
        for coil in coils.itertuples():
            c = coil.Id
            for (_, s) in pairs.select(c, '*'):
                for part in parts.itertuples():
                    p = part.Code
                    model.addConstr(
                        v[p, c, s] == v1[p, c, s] + v2[p, c, s] + (part.BeginLoss + part.EndLoss) *
                        mu[p, c, s],
                        name=f'stripLength1[{p},{c},{s}]'
                    )
                    model.addConstr(
                        x[c] - v[p, c, s] >= 0, name=f'stripLength2[{p},{c},{s}]'
                    )
                    model.addConstr(
                        x[c] - v[p, c, s] <= coil.Length * (1 - mu[p, c, s]),
                        name=f'stripLength3[{p},{c},{s}]'
                    )

        # (23)
        for coil in coils.itertuples():
            c = coil.Id
            for (_, s) in pairs.select(c, '*'):
                for part in parts.itertuples():
                    p = part.Code
                    model.addConstr(
                        v[p, c, s] <= coil.Length * mu[p, c, s], name=f'stripLength4[{p},{c},{s}]'
                    )

        # (new)
        model.addConstrs(
            (v2[p, c, s] == vr[p, c, s] + vs[p, c, s] for p in parts_codes for (c, s) in
             pairs),
            name='retail-scrap-x'
        )

        # (new)
        model.addConstrs(
            (vr[p, c, s] >= parameters['MinRetailLength'] * beta[p, c, s] for p in parts_codes for (c, s)
             in
             pairs), name='retail-x1'
        )

        # (new)
        for coil in coils.itertuples():
            c = coil.Id
            for (_, s) in pairs.select(c, '*'):
                for p in parts_codes:
                    model.addConstr(
                        vr[p, c, s] <= coil.Length * beta[p, c, s], name=f"'retail-x2'[{p},{c},{s}]"
                    )

        # (new)
        model.addConstrs(
            (vs[p, c, s] <= parameters['MinRetailLength'] * (1 - beta[p, c, s]) for p in parts_codes for
             (c, s)
             in pairs),
            name='scrap-x'
        )

        # (26)
        for coil in coils.itertuples():
            c = coil.Id
            for (_, s) in pairs.select(c, '*'):
                for part in parts.itertuples():
                    p = part.Code
                    model.addConstr(
                        u[p, c, s] == coil.WeightPerM2 * part.Width * v[p, c, s],
                        name=f'stripWeight1[{p},{c},{s}]'
                    )
                    model.addConstr(
                        u1[p, c, s] == coil.WeightPerM2 * part.Width * v1[p, c, s],
                        name=f'stripWeight2[{p},{c},{s}]'
                    )
                    model.addConstr(
                        u2[p, c, s] == coil.WeightPerM2 * part.Width * v2[p, c, s],
                        name=f'stripWeight3[{p},{c},{s}]'
                    )
                    model.addConstr(
                        ur[p, c, s] == coil.WeightPerM2 * part.Width * vr[p, c, s],
                        name=f'stripWeight4[{p},{c},{s}]'
                    )
                    model.addConstr(
                        us[p, c, s] == coil.WeightPerM2 * part.Width * vs[p, c, s],
                        name=f'stripWeight5[{p},{c},{s}]'
                    )

        # (28)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                u.sum('*', c, '*') + z[c] + e[c] == coil.WeightPerM2 * coil.Width * x[c],
                name=f'leftoverWeight[{c}]'
            )

        # (30)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                e[c] <= 2 * parameters['MinEdgeTrim'] * coil.WeightPerM2 * x[c], name=f'edgeTrim1[{c}]'
            )

        # (31)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                e[c] <= 2 * parameters['MinEdgeTrim'] * coil.WeightPerM2 * coil.Length * alpha.get((c, 2), 0),
                name=f'edgeTrim2[{c}]'
            )

        # (32)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                e[c] >= 2 * parameters['MinEdgeTrim'] * coil.WeightPerM2 * (
                        x[c] - coil.Length * (1 - alpha.get((c, 2), 0))),
                name=f'edgeTrim3[{c}]'
            )

        # (44)
        for part in parts.itertuples():
            p = part.Code
            production = gp.LinExpr(0.0)
            for coil in coils.itertuples():
                c = coil.Id
                for (_, s) in pairs.select(c, '*'):
                    production.addTerms(1, u1[p, c, s])
            model.addConstr(
                production == part.Demand, name=f'demand[{p}]'
            )

        # (45)
        model.addConstrs(
            (y[c] == yr[c] + ys[c] for c in coils_ids), name='retail-scrap-y'
        )

        # (46)
        model.addConstrs(
            (z[c] == zr[c] + zs[c] for c in coils_ids), name='retail-scrap-y-weight'
        )

        # (47)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                yr[c] >= min_strip_width * theta[c], name=f'retail-y-1[{c}]'
            )
            model.addConstr(
                yr[c] <= (coil.Width - 2 * parameters['MinEdgeTrim'] - min_strip_width) * theta[c],
                name=f'retail-y-2[{c}]'
            )

        # (49)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                zr[c] <= coil.Weight * theta[c], name=f'retail-y-weight[{c}]'
            )

        # (50)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                ys[c] <= min_strip_width * (1 - theta[c]), name=f'scrap-y[{c}]'
            )

        # (51)
        for coil in coils.itertuples():
            c = coil.Id
            model.addConstr(
                zs[c] <= coil.Weight * (1 - theta[c]), name=f'scrap-y-weight[{c}]'
            )

        # (68)
        for coil in coils.itertuples():
            c = coil.Id
            slits = [s for (_, s) in pairs.select(c, '*')]
            for i_s1, s1 in enumerate(slits):
                for s2 in slits[:i_s1 + 1]:
                    for i_p1, p1 in enumerate(parts_codes):
                        p2_list = parts_codes[i_p1 + 1:]
                        if len(p2_list) == 0:
                            continue
                        model.addConstr(
                            mu[p1, c, s1] + mu.sum(p2_list, c, s2) <= 1, name=f"valid[{p1},{c},{s1},{s2}]"
                        )

        objective_type = args.objective

        cost = gp.LinExpr(0.0)

        if objective_type == "weighted_loss":

            edge_trim = gp.LinExpr(0.0)
            retail_y = gp.LinExpr(0.0)
            scrap_y = gp.LinExpr(0.0)
            retail_v = gp.LinExpr(0.0)
            scrap_v = gp.LinExpr(0.0)
            end_loss = gp.LinExpr(0.0)
            rolled = gp.LinExpr(0.0)
            scrap_p = gp.LinExpr(0.0)
            use_v = gp.LinExpr(0.0)

            for coil in coils.itertuples():
                c = coil.Id

                if coil.Processed:
                    scrap_p += coil.Weight * coil.Value
                else:
                    edge_trim += coil.Value * e[c]
                    retail_y += coil.Value * zr[c]
                    scrap_y += coil.Value * zs[c]
                    rolled += (
                        coil.Weight * coil.Value * alpha[c, 1]
                        - coil.WeightPerM2 * coil.Width * coil.Value * x[c]
                    )

                for (_, s) in pairs.select(c, '*'):
                    for part in parts.itertuples():
                        p = part.Code

                        if coil.Processed:
                            scrap_p -= coil.Value * u1[p, c, s]
                            use_v += coil.Value * u1[p, c, s]
                        else:
                            retail_v += coil.Value * ur[p, c, s]
                            scrap_v += coil.Value * us[p, c, s]
                            end_loss += (
                                coil.Value * u[p, c, s]
                                - coil.Value * u1[p, c, s]
                                - coil.Value * u2[p, c, s]
                            )
                            use_v += coil.Value * u1[p, c, s]

            # Aqui assumimos coeficiente unitario para o emprego de materia-prima
            # Sucata tem coeficiente 8
            # As sobras possuem  coeficiente intermediário (2 ou 4). 
            # Precisamos definir que sobras possuem coeficiente 2 e que sobras possuem coeficiente 4
            objective_coefficients = {
                'use_v': 1,
                'edge_trim': 8,
                'retail_y': leftover_weights['retail_y'],
                'scrap_y': 8,
                'retail_v': leftover_weights['retail_v'],
                'scrap_v': 8,
                'endloss': 8,
                'rolled_leftover': leftover_weights['rolled_leftover'],
                'scrap_processed': 8
            }

            cost.add(
                objective_coefficients['use_v'] * use_v +
                objective_coefficients['edge_trim'] * edge_trim +
                objective_coefficients['retail_y'] * retail_y +
                objective_coefficients['scrap_y'] * scrap_y +
                objective_coefficients['retail_v'] * retail_v +
                objective_coefficients['scrap_v'] * scrap_v +
                objective_coefficients['endloss'] * end_loss +
                objective_coefficients['rolled_leftover'] * rolled +
                objective_coefficients['scrap_processed'] * scrap_p
            )

        elif objective_type == "new_coils_value":

            for coil in coils.itertuples():
                c = coil.Id

                if coil.Processed == 0:
                    cost += coil.Weight * coil.Value * alpha[c, 1]

        else:
            raise ValueError(f"Unknown objective_type: {objective_type}")

        model.setObjective(cost, GRB.MINIMIZE)

        # model.write(f'output/{data_folder}/{period}/model.lp')

        logging.info(f'{data_folder}-{period}-geracao do modelo finalizada')
        
        logging.info(f'{data_folder}-{period}-modelo de otimizacao iniciado')
        model.optimize()
        logging.info(f'{data_folder}-{period}-modelo de otimizacao finalizado')
        
        logging.info(f'{data_folder}-{period}-leitura da solucao iniciada')

        EPS = 1e-6
        
        def r_weight(x):
            return round(float(x), 2)

        def r_width(x):
            return round(float(x), 1)

        def r_length(x):
            return round(float(x), 2)        

        def r_value(x):
            return round(float(x), 2)

        def val(var):
            return var.X if hasattr(var, "X") else float(var)

        def positive(x):
            return abs(x) > EPS

        def build_cutting_plan_and_retails(
            coils, parts, pairs,
            alpha, x,
            mu, u, u1, u2, ur, us,
            y, z, zr, zs, e,
            output_retails_path
        ):
            cutting_plan = {}
            retails_rows = []
            next_retail_id = 1

            for coil in coils.itertuples():
                c = coil.Id

                is_used = val(alpha[c, 1]) > 0.5
                is_processed = coil.Processed == 1
                can_generate_retail = coil.Processed == 0

                if not is_processed and not is_used:
                    continue

                produced_weight = 0.0
                strip_leftover_weight = 0.0
                strip_retail_weight = 0.0
                strip_scrap_weight = 0.0
                begin_end_loss_weight = 0.0

                strips = []

                for (_, s) in pairs.select(c, '*'):
                    for part in parts.itertuples():
                        p = part.Code

                        if val(mu[p, c, s]) <= 0.5:
                            continue

                        total_strip_weight = val(u[p, c, s])
                        production_weight = val(u1[p, c, s])
                        leftover_weight = val(u2[p, c, s])
                        retail_weight = val(ur[p, c, s])
                        scrap_weight = val(us[p, c, s])

                        loss_weight = total_strip_weight - production_weight - leftover_weight

                        produced_weight += production_weight
                        strip_leftover_weight += leftover_weight
                        strip_retail_weight += retail_weight
                        strip_scrap_weight += scrap_weight
                        begin_end_loss_weight += loss_weight

                        strips.append({
                            "strip_index": s,
                            "part_code": p,
                            "part_width": r_width(part.Width * 1000.0),  # volta para mm,
                            "total_strip_weight": r_weight(total_strip_weight),
                            "---production_weight": r_weight(production_weight),
                            "---leftover_weight": r_weight(leftover_weight),
                            "------retail_leftover_weight": r_weight(retail_weight),
                            "------scrap_leftover_weight": r_weight(scrap_weight),
                            "---begin_end_loss_weight": r_weight(loss_weight),
                        })

                        # Sobra reutilizável longitudinal da tira
                        if can_generate_retail and retail_weight > EPS:
                            retails_rows.append({
                                "Id": str(next_retail_id),
                                "Width": r_width(part.Width * 1000.0),  # volta para mm
                                "Value": r_value(coil.Value * 1000.0),  # volta para R$/ton
                                "Weight": r_weight(retail_weight),
                                "Processed": 1
                            })
                            next_retail_id += 1

                if is_processed:
                    rolled_leftover_weight = 0.0
                    rolled_leftover_length = 0.0
                    processed_scrap_weight = coil.Weight - produced_weight
                else:
                    rolled_leftover_length = coil.Length * val(alpha[c, 1]) - val(x[c])

                    rolled_leftover_weight = (
                        coil.Weight * val(alpha[c, 1]) - coil.WeightPerM2 * coil.Width * val(x[c])
                    )

                    processed_scrap_weight = 0.0

                    if rolled_leftover_weight > EPS:
                        retails_rows.append({
                            "Id": str(next_retail_id),
                            "Width": r_width(coil.Width * 1000.0),
                            "Value": r_value(coil.Value * 1000.0),
                            "Weight": r_weight(rolled_leftover_weight),
                            "Processed": 1
                        })
                        next_retail_id += 1

                rolled_leftover = {
                    "width": r_width(coil.Width * 1000.0),
                    "weight": abs(r_weight(rolled_leftover_weight)),
                    "length": abs(r_length(rolled_leftover_length)),
                }

                lateral_leftover = {
                    "width": r_width(val(y[c]) * 1000.0),
                    "weight": r_weight(val(z[c])),
                    "---retail_weight": r_weight(val(zr[c])),
                    "---scrap_weight": r_weight(val(zs[c])),
                }

                # Sobra reutilizável lateral
                if can_generate_retail and val(zr[c]) > EPS:
                    retails_rows.append({
                        "Id": str(next_retail_id),
                        "Width": r_width(val(y[c]) * 1000.0),  # volta para mm
                        "Value": r_value(coil.Value * 1000.0),  # volta para R$/ton
                        "Weight": r_weight(val(zr[c])),
                        "Processed": 1
                    })
                    next_retail_id += 1
                
                cutting_plan[c] = {
                    "coil_width": r_width(coil.Width * 1000.0),
                    "coil_ton_value": r_value(coil.Value * 1000.0),
                    "processed": int(coil.Processed),
                    "used": int(is_used),
                    "used_length": r_length(val(x[c])),
                    "coil_weight": r_weight(coil.Weight),
                    "---strip_produced_weight": r_weight(produced_weight),
                    "---strip_leftover_weight": r_weight(strip_leftover_weight),
                    "------strip_retail_weight": r_weight(strip_retail_weight),
                    "------strip_scrap_weight": r_weight(strip_scrap_weight),
                    "---strip_loss_weight": r_weight(begin_end_loss_weight),
                    "---lateral_leftover_weight": lateral_leftover["weight"],
                    "---edge_trim_weight": r_weight(val(e[c])),
                    "---rolled_leftover_weight": rolled_leftover["weight"],
                    "---processed_scrap_weight": r_weight(processed_scrap_weight),
                    "strips": strips,
                    "rolled_leftover": rolled_leftover,
                    "lateral_leftover": lateral_leftover,
                }

            retails_df = pd.DataFrame(
                retails_rows,
                columns=["Id", "Width", "Value", "Weight", "Processed"]
            )
            
            retails_path = Path(output_retails_path)
            retails_path.parent.mkdir(parents=True, exist_ok=True)
            retails_df.to_csv(output_retails_path, index=False)

            return cutting_plan, retails_df

        if model.SolCount > 0:
            
            current_period = period
            period_number = int(current_period.split("_")[1])
            next_period = f"period_{period_number + 1}"

            output_retails_path = output_root / next_period / 'Retails.csv'
            
            cutting_plan, retails_df = build_cutting_plan_and_retails(
                coils=coils,
                parts=parts,
                pairs=pairs,
                alpha=alpha,
                x=x,
                mu=mu,
                u=u,
                u1=u1,
                u2=u2,
                ur=ur,
                us=us,
                y=y,
                z=z,
                zr=zr,
                zs=zs,
                e=e,
                output_retails_path=output_retails_path
            )

        json_output_path = period_output_dir / 'cutting_plan.json'

        os.makedirs(json_output_path.parent, exist_ok=True)

        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(
                cutting_plan,
                f,
                indent=4,
                ensure_ascii=False
            )

        logging.info(f'{data_folder}-{period}-leitura da solucao finalizada')

        model.dispose()
        gp.disposeDefaultEnv()
