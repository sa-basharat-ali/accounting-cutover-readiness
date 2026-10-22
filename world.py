"""Synthetic multifamily operator moving property accounting to a new platform.

60 properties, one cutover date. For each property: units, resident ledgers (charges and receipts
for the cutover month), security and pet deposits held, the legacy charge-code table, a legacy GL
trial balance, and bank balances. Failures are injected with ground truth so every check can be
scored. Fixed seed, no real operator, resident or bank.
"""
import random

SEED = 7
N_PROPS = 60

# legacy charge codes -> GL account (the operator's standard table)
CHARGE_CODES = {
    'RENT':   ('4100', 'Rent'),
    'CONC':   ('4110', 'Concessions'),          # contra-revenue, negative amounts
    'PETRNT': ('4410', 'Pet rent'),
    'PARK':   ('4420', 'Parking'),
    'RUBSW':  ('4510', 'Utility reimbursement - water/sewer'),
    'RUBST':  ('4520', 'Utility reimbursement - trash'),
    'LATE':   ('4610', 'Late fees'),
    'SECDEP': ('2200', 'Security deposits held'),
    'PETDEP': ('2210', 'Pet deposits held'),
    'STOR':   ('4430', 'Storage'),
}
# codes some sites created locally that never made it into the standard table
LOCAL_CODES = ['STOR2', 'AMENX', 'UTILADJ']
NEW_MAPPING = {c: v[0] for c, v in CHARGE_CODES.items()}   # what the migration team was handed

GL = {
    '1010': 'Cash - operating',
    '1020': 'Cash - security deposit trust',
    '1310': 'Resident accounts receivable',
    '2200': 'Security deposits held',
    '2210': 'Pet deposits held',
    '2300': 'Prepaid rent',
    '3000': 'Owner equity',
}


def build():
    rnd = random.Random(SEED)
    props = []
    for p in range(N_PROPS):
        pid = f'P{p+1:03d}'
        units = rnd.randint(120, 400)
        props.append({'pid': pid, 'units': units, 'state': rnd.choice(['NY', 'NJ', 'TX', 'FL', 'GA', 'NC', 'AZ', 'CO'])})

    pids = [p['pid'] for p in props]
    truth = {
        'petdep_to_income': set(rnd.sample(pids, 9)),      # local override: PETDEP posts to 4410 (income)
        'manual_ar_je': {},                                  # pid -> amount posted straight to 1310
        'local_codes': {},                                   # pid -> code used but unmapped
        'commingled': set(rnd.sample(pids, 4)),              # deposits sit in operating cash
        'net_prepaids': True,                                # legacy AR control is net of resident credits
        'dup_transfers': [],                                 # (pid, old_rid, new_rid)
    }
    for pid in rnd.sample(pids, 7):
        # write-offs and reversals keyed to the control account, never to a resident
        truth['manual_ar_je'][pid] = round(rnd.choice([-1, -1, 1]) * rnd.uniform(4_000, 38_000), 2)
    for pid in rnd.sample(pids, 11):
        truth['local_codes'][pid] = rnd.choice(LOCAL_CODES)

    residents, txns = [], []
    rid_n = 0
    for pr in props:
        pid = pr['pid']
        occupied = int(pr['units'] * rnd.uniform(0.91, 0.97))
        for u in range(occupied):
            rid_n += 1
            rid = f'R{rid_n:06d}'
            rent = round(rnd.uniform(1_350, 3_400), 0)
            pet = rnd.random() < 0.27
            r = {'rid': rid, 'pid': pid, 'unit': f'{pid}-{u+1:03d}', 'rent': rent, 'pet': pet,
                 'name': f'resident {rid_n}', 'status': 'current'}
            residents.append(r)
            # deposits held from move-in (posted long ago; carried as opening liability)
            sec = round(rnd.choice([500, 750, rent / 2, rent]), 2)
            txns.append((pid, rid, 'SECDEP', sec, 'deposit'))
            if pet:
                txns.append((pid, rid, 'PETDEP', float(rnd.choice([300, 400, 500])), 'deposit'))
            # cutover-month charges
            charges = [('RENT', rent), ('RUBSW', round(rnd.uniform(38, 85), 2)), ('RUBST', round(rnd.uniform(12, 30), 2))]
            if pet:
                charges.append(('PETRNT', float(rnd.choice([35, 45, 60]))))
            if rnd.random() < 0.30:
                charges.append(('PARK', float(rnd.choice([75, 100, 150]))))
            if rnd.random() < 0.08:
                charges.append(('CONC', -round(rnd.uniform(100, 350), 0)))
            if rnd.random() < 0.05:
                charges.append(('STOR', 65.0))
            if pid in truth['local_codes'] and rnd.random() < 0.22:
                charges.append((truth['local_codes'][pid], round(rnd.uniform(25, 140), 2)))
            billed = sum(a for _, a in charges)
            roll = rnd.random()
            if roll < 0.08:                      # delinquent: carries a prior balance, partial pay, late fee
                prior = round(rent * rnd.choice([0.5, 1, 1, 2, 3]), 2)
                charges.append(('RENT', prior))   # prior-month rent still open at cutover
                charges.append(('LATE', 75.0))
                paid = round(billed * rnd.uniform(0.0, 0.6), 2)
            elif roll < 0.12:                    # paid ahead: part or all of next month
                paid = round(billed + rent * rnd.choice([0.25, 0.5, 1.0]), 2)
            else:
                paid = round(billed, 2)
            for code, amt in charges:
                txns.append((pid, rid, code, amt, 'charge'))
            txns.append((pid, rid, 'PMT', -paid, 'receipt'))

        # transfers: resident moved to another unit; a second record was created and the deposit
        # was re-entered on it instead of moved, so the deposit sits on both records
        for _ in range(rnd.randint(0, 2)):
            old = rnd.choice([r for r in residents if r['pid'] == pid and r['status'] == 'current'])
            rid_n += 1
            new = dict(old, rid=f'R{rid_n:06d}', unit=f"{pid}-T{rid_n % 1000:03d}")
            if rnd.random() < 0.35:              # re-keyed by hand: case or spacing differs
                new['name'] = rnd.choice([old['name'].title(), old['name'] + ' ', old['name'].upper()])
            residents.append(new)
            dep = next(t[3] for t in txns if t[1] == old['rid'] and t[2] == 'SECDEP')
            txns.append((pid, new['rid'], 'SECDEP', dep, 'deposit'))
            truth['dup_transfers'].append((pid, old['rid'], new['rid'], dep))
    return props, residents, txns, truth


def legacy_gl(props, txns, truth):
    """Legacy trial balance per property, as the old system reports it."""
    tb = {}
    by_pid = {}
    for t in txns:
        by_pid.setdefault(t[0], []).append(t)
    for pr in props:
        pid = pr['pid']
        g = {k: 0.0 for k in GL}
        rev = 0.0
        resident_bal = {}
        for _, rid, code, amt, kind in by_pid.get(pid, []):
            if kind == 'deposit':
                acct = CHARGE_CODES[code][0]
                if code == 'PETDEP' and pid in truth['petdep_to_income']:
                    rev += amt                                   # booked as income, not liability
                    dep_cash = '1010'
                else:
                    g[acct] -= amt                               # liability (credit)
                    dep_cash = '1010' if pid in truth['commingled'] else '1020'
                g[dep_cash] += amt
            elif kind == 'charge':
                resident_bal[rid] = resident_bal.get(rid, 0.0) + amt
                rev += amt
            else:  # receipt
                resident_bal[rid] = resident_bal.get(rid, 0.0) + amt
                g['1010'] += -amt
        # duplicate transfer deposits were re-entered in the subledger only; the GL liability was posted once
        for d in truth['dup_transfers']:
            if d[0] == pid:
                g['2200'] += d[3]
                g['1020' if pid not in truth['commingled'] else '1010'] -= d[3]
        net_ar = sum(resident_bal.values())
        g['1310'] = net_ar + truth['manual_ar_je'].get(pid, 0.0)  # legacy control is net of credits
        g['2300'] = 0.0
        g['3000'] = -(sum(v for k, v in g.items() if k != '3000') ) + 0.0
        # equity plugs revenue and history so the TB balances, as a real legacy TB does
        tb[pid] = {k: round(v, 2) for k, v in g.items()}
    return tb
