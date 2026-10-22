"""Cutover readiness checks for a property-accounting migration. stdlib only.

python3 run.py
"""
from collections import defaultdict
from world import build, legacy_gl, NEW_MAPPING

props, residents, txns, truth = build()
tb = legacy_gl(props, txns, truth)
pids = [p['pid'] for p in props]
units = sum(p['units'] for p in props)

bal = defaultdict(float)            # resident balance from the subledger (charges + receipts)
dep = defaultdict(float)            # (pid, code) -> deposits held per subledger
codes_used = defaultdict(lambda: [0, 0.0, set()])
for pid, rid, code, amt, kind in txns:
    if kind == 'deposit':
        dep[(pid, code)] += amt
    else:
        bal[(pid, rid)] += amt
    if code != 'PMT':
        c = codes_used[code]
        c[0] += 1; c[1] += amt; c[2].add(pid)

sub_ar = defaultdict(float); gross_ar = defaultdict(float); prepaid = defaultdict(float)
for (pid, rid), b in bal.items():
    sub_ar[pid] += b
    if b > 0: gross_ar[pid] += b
    else: prepaid[pid] += -b


def money(x):
    return f'${x:,.0f}'


flags = defaultdict(set)
print(f'{len(props)} properties, {units:,} units, {len(residents):,} resident records, {len(txns):,} ledger lines\n')

# 1. trial balance
tb_ok = sum(1 for p in pids if abs(sum(tb[p].values())) < 0.01)
print(f'1. Trial balance debits = credits: {tb_ok}/{len(pids)} properties')

# 2. portfolio-level AR and deposit totals (what a summary sign-off looks at)
gl_ar = sum(tb[p]['1310'] for p in pids); s_ar = sum(sub_ar.values())
gl_dep = -sum(tb[p]['2200'] + tb[p]['2210'] for p in pids); s_dep = sum(dep.values())
print(f'2. Portfolio AR: GL {money(gl_ar)} vs resident ledgers {money(s_ar)} ({(gl_ar - s_ar) / s_ar:+.2%})')
print(f'   Portfolio deposits: GL {money(gl_dep)} vs resident ledgers {money(s_dep)} ({(gl_dep - s_dep) / s_dep:+.2%})')

# 3. AR tie-out per property
ar_breaks = {p: tb[p]['1310'] - sub_ar[p] for p in pids if abs(tb[p]['1310'] - sub_ar[p]) > 1}
for p in ar_breaks: flags[p].add('ar')
caught = set(ar_breaks) & set(truth['manual_ar_je'])
print(f'3. AR control vs resident ledgers by property: {len(ar_breaks)} break '
      f'(gross {money(sum(abs(v) for v in ar_breaks.values()))}, net {money(sum(ar_breaks.values()))}); '
      f'{len(caught)}/{len(truth["manual_ar_je"])} manual control-account entries found')

# 4. deposits by type
pet_breaks = {p: dep[(p, 'PETDEP')] + tb[p]['2210'] for p in pids if abs(dep[(p, 'PETDEP')] + tb[p]['2210']) > 1}
sec_breaks = {p: dep[(p, 'SECDEP')] + tb[p]['2200'] for p in pids if abs(dep[(p, 'SECDEP')] + tb[p]['2200']) > 1}
for p in pet_breaks: flags[p].add('petdep')
for p in sec_breaks: flags[p].add('secdep')
print(f'4. Pet deposits held vs GL 2210: {len(pet_breaks)} properties, {money(sum(pet_breaks.values()))} '
      f'held for residents but booked as income ({len(set(pet_breaks) & truth["petdep_to_income"])}/{len(truth["petdep_to_income"])} found)')
dups = truth['dup_transfers']
print(f'   Security deposits vs GL 2200: {len(sec_breaks)} properties, {money(sum(sec_breaks.values()))} '
      f'more on resident ledgers than in the GL')

# 5. duplicate resident records (transfers)
def dup_groups(key):
    seen = defaultdict(list)
    for r in residents:
        seen[(r['pid'], key(r['name']))].append(r['rid'])
    return {k: v for k, v in seen.items() if len(v) > 1}
exact = dup_groups(lambda n: n)
norm = dup_groups(lambda n: ' '.join(n.lower().split()))
print(f'5. Same resident on two records at one property (transfers re-keyed, deposit re-entered): '
      f'exact name match {len(exact)}, normalized name {len(norm)}, true {len(dups)}; '
      f'deposit double-counted {money(sum(d[3] for d in dups))}')

# 6. deposit cash: is the liability backed by the trust account?
comm = {p: -(tb[p]['2200'] + tb[p]['2210']) - tb[p]['1020'] for p in pids
        if -(tb[p]['2200'] + tb[p]['2210']) - tb[p]['1020'] > 1}
for p in comm: flags[p].add('cash')
print(f'6. Deposit liability vs trust-account cash: {len(comm)} properties short {money(sum(comm.values()))} '
      f'({len(set(comm) & truth["commingled"])}/{len(truth["commingled"])} commingled found)')

# 7. charge-code mapping coverage
unmapped = {c: v for c, v in codes_used.items() if c not in NEW_MAPPING}
for c, v in unmapped.items():
    for p in v[2]: flags[p].add('code')
print(f'7. Charge codes missing from the mapping file: {len(unmapped)} codes, '
      f'{sum(v[0] for v in unmapped.values())} lines, {money(sum(v[1] for v in unmapped.values()))}, '
      f'{len(set().union(*[v[2] for v in unmapped.values()]))} properties: ' +
      ', '.join(f'{c} ({v[0]} lines)' for c, v in sorted(unmapped.items())))

# 8. net vs gross AR
print(f'8. Legacy AR is net of resident credits: gross AR {money(sum(gross_ar.values()))}, '
      f'prepaid {money(sum(prepaid.values()))}, net {money(s_ar)}. Migrating the net balance as AR '
      f'drops {money(sum(prepaid.values()))} of prepaid-rent liability.')

ready = [p for p in pids if not flags[p]]
print(f'\nReady to cut over with no exceptions: {len(ready)}/{len(pids)} properties')
mix = defaultdict(int)
for p in pids:
    mix[len(flags[p])] += 1
print('Exceptions per property: ' + ', '.join(f'{k}: {mix[k]}' for k in sorted(mix)))
