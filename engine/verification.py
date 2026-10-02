"""Verify adjacent steps, then locate the earliest confirmed error in a chain."""
import re
import time
import sympy as S
from .syntax import InputError, s, z, name, txt, tree, parse, lineparse, nonzero, validate_context
from .formatting import FORMAT_VERSION, presentation_latex
from .rules import RULEMAP, reduce_expression, candidates
from .diagnostics import canonical, equal, domain_changes, roc_parse, roc_compare, proofdiff, sample_counterexample, formal_counterexample, explain_error

def check_step(before,after,c):
    lhs,den1,roc1=lineparse(before); rhs,den2,roc2=lineparse(after)
    c=dict(c);c['_activeRocs']=[q for q in (roc1,roc2) if q];c['_denominators']=den1+den2
    if roc1: roc_parse(roc1)
    if roc2: roc_parse(roc2)
    for region in (roc1,roc2):
        if not region: continue
        axis=roc_parse(region)[0]
        domains={name(node) for expr in (lhs,rhs) for node in S.preorder_traversal(expr)}
        variables=lhs.free_symbols|rhs.free_symbols
        if ('LT' in domains or s in variables) and not ('ZT' in domains or z in variables) and axis!='re(s)':
            raise InputError('拉普拉斯表达式应使用 re(s) 的收敛域。')
        if ('ZT' in domains or z in variables) and not ('LT' in domains or s in variables) and axis!='abs(z)':
            raise InputError('Z 变换表达式应使用 abs(z) 的收敛域。')
    base_result={'before':before,'after':after,'expected':'','ruleIds':[],'ruleNames':[],'conditions':[],
                 'evidence':[],'diff':{},'trace':[],'samples':[],'inherited':False}
    if equal(lhs,rhs,c):
        lost=domain_changes(lhs,rhs,den1,den2,c)
        status='unknown' if lost else 'correct'
        if roc1 or roc2:
            roc_status=roc_compare([roc1] if roc1 else [],roc2)
            if roc_status!='correct': status=roc_status
        return dict(base_result,status=status,expected=before if status!='correct' else after,
                    conditions=lost,explanation=('代数式相等，但需保留定义域限制：'+', '.join(lost)) if lost else
                    ('代数式等价，但收敛域缺失或改变。' if status!='correct' else '相邻两式在给定条件下符号等价。'),
                    evidence=['符号差值化简为 0'],ruleIds=['ALG'],ruleNames=['代数化简 / 已知变换对代入'])
    reduced=reduce_expression(lhs,c)
    right_reduced=reduce_expression(rhs,c)
    rhs_check=right_reduced[0] if not right_reduced[2] else rhs
    cand=[reduced] if reduced[1] else []
    if not reduced[1]: cand.extend(candidates(lhs,c))
    # Prefer shortest matching proof, and a fully resolved proof over a blocked one.
    matches=[q for q in cand if equal(q[0],rhs_check,c)]
    if matches:
        matches.sort(key=lambda q:(bool(q[2]),len(q[1])))
        ex,path,needs,rocs=matches[0]
        needs=needs+domain_changes(ex,rhs,den1,den2,c)
        rocs=rocs or ([roc1] if roc1 else [])
        if len(set(rocs))>1: needs=needs+['组合变换的精确收敛域需要另行确认']
        status='unknown' if needs else roc_compare(rocs,roc2)
        exp=txt(ex)+('; ROC: '+rocs[-1] if rocs else '')
        ids=list(dict.fromkeys(q['ruleId'] for q in path))
        why='规则重写链与目标表达式符号一致。'
        if needs: why='表达式符合规则形式，但前提尚未满足：'+'；'.join(needs)
        elif status=='incomplete': why='代数表达式正确，但缺少收敛域。变换结果必须包含 ROC。'
        elif status=='wrong': why='代数表达式正确，但收敛域方向或边界不正确。'
        elif status=='unknown': why='代数表达式符合规则，但无法从已知条件证明所填收敛域。'
        return dict(base_result,status=status,expected=exp,ruleIds=ids,ruleNames=[RULEMAP[i]['name'] for i in ids],
                    conditions=needs+rocs,evidence=['已执行 '+str(len(path))+' 次规则重写','候选与目标的符号差值为 0'],
                    trace=path,explanation=why,diff={'path':'ROC','before':roc2 or '未填写','after':rocs[-1]} if rocs and status!='correct' else {})
    # Choose the closest completed candidate. Structure similarity guides explanation, not correctness.
    valid=[q for q in cand if not q[2] and not any(name(v) in ('FT','LT','ZT') for v in S.preorder_traversal(q[0]))]
    if not valid: valid=[q for q in cand if not q[2]]
    if valid:
        from difflib import SequenceMatcher
        valid.sort(key=lambda q:(-SequenceMatcher(None,txt(canonical(q[0],c)),txt(canonical(rhs_check,c))).ratio(),len(q[1])))
        for ex,path,needs,rocs in valid[:8]:
            witness_context=dict(c,_activeRocs=c.get('_activeRocs',[])+rocs)
            samples=sample_counterexample(ex,rhs_check,witness_context) or formal_counterexample(ex,rhs_check,witness_context)
            if samples:
                ids=list(dict.fromkeys(q['ruleId'] for q in path));d=proofdiff(canonical(ex,{}),canonical(rhs,{}))
                return dict(base_result,status='wrong',expected=txt(ex)+('; ROC: '+rocs[-1] if rocs else ''),
                    ruleIds=ids,ruleNames=[RULEMAP[i]['name'] for i in ids],conditions=rocs,trace=path,diff=d,samples=samples,
                    evidence=['规则产生正确候选','发现可复核的函数/数值反例'],
                    explanation=explain_error(ids,d,ex,rhs))
    samples=sample_counterexample(lhs,rhs_check,c) or formal_counterexample(lhs,rhs_check,c)
    if samples:
        return dict(base_result,status='wrong',explanation='高精度代入发现反例，两式不能作为恒等式互换。',samples=samples,evidence=['40位精度求值发现不一致'])
    return dict(base_result,status='unknown',conditions=reduced[2],explanation='当前规则库与有界搜索尚不能证明或否定此步，请补充条件或拆成更小步骤。',
                evidence=['未把“化简未成功”当成错误','数值一致不作为数学证明'])

LABELS={'correct':'已验证正确','wrong':'已确认错误','unknown':'暂无法判断','incomplete':'缺少收敛域'}

def verify(steps,c=None):
    start=time.perf_counter();c=validate_context(c)
    if not isinstance(steps,list) or not 2<=len(steps)<=16: raise InputError('请输入 2–16 行推导。')
    # Substitute declared initial values into both submitted and generated expressions.
    effective=[]
    for line in steps:
        if not isinstance(line,str): raise InputError('每行公式必须是文本。')
        for key,val in c.get('initial',{}).items(): line=re.sub(r'\b'+key+r'\b','('+str(val)+')',line)
        effective.append(line)
    parsed_lines=[lineparse(line) for line in effective]
    parsed=[line[0] for line in parsed_lines]
    presentations=[presentation_latex(line[0],line[2]) for line in parsed_lines]
    rendered=[line[0] for line in presentations]
    rendered_rocs=[line[1] for line in presentations]
    results=[];first=None; uncertain=False; firstcertain=True; known_roc=parsed_lines[0][2]
    for i in range(1,len(steps)):
        before=effective[i-1]
        if known_roc and not parsed_lines[i-1][2]: before+='; ROC: '+known_roc
        row=check_step(before,effective[i],c)
        if row['status'] in ('correct','incomplete') and row.get('expected'):
            known_roc=lineparse(row['expected'])[2] or known_roc
        row['beforeLatex']=rendered[i-1];row['afterLatex']=rendered[i]
        row['beforeRocLatex']=rendered_rocs[i-1];row['afterRocLatex']=rendered_rocs[i]
        if row.get('expected'):
            expected_expr,_,expected_roc=lineparse(row['expected'])
            row['expectedLatex'],row['expectedRocLatex']=presentation_latex(expected_expr,expected_roc)
        else: row['expectedLatex']='';row['expectedRocLatex']=''
        for transition in row['trace']:
            for side in ('before','after'):
                try: transition[side+'Latex']=presentation_latex(lineparse(transition[side])[0])[0]
                except (InputError,ValueError,TypeError,RecursionError): transition[side+'Latex']=''
        for side in ('before','after'):
            if row.get('diff',{}).get(side):
                try: row['diff'][side+'Latex']=presentation_latex(parse(row['diff'][side])[0])[0]
                except (InputError,ValueError,TypeError,RecursionError): pass
        row['before']=steps[i-1];row['after']=steps[i];row['line']=i+1
        row['localStatus']=row['status'];row['statusLabel']=LABELS[row['status']]
        row['inherited']=first is not None
        if row['status']=='wrong' and first is None: first=i+1;firstcertain=not uncertain
        if row['status'] in ('unknown','incomplete'): uncertain=True
        if row['inherited'] and row['status']=='correct': row['statusLabel']='局部正确 · 继承前错'
        results.append(row)
    statuses=[q['status'] for q in results]
    status='wrong' if first else ('unknown' if 'unknown' in statuses else ('incomplete' if 'incomplete' in statuses else 'correct'))
    summary=('第 '+str(first-1)+' → '+str(first)+' 行出现'+('首个错误' if firstcertain else '最早已确认错误；此前存在未证实步骤')) if first else {
        'correct':'全部相邻步骤已通过验证。','unknown':'存在尚未证实的步骤，不能判定整条推导正确。','incomplete':'代数推导成立，但收敛域信息不完整。'}[status]
    correction=list(steps)
    if first and results[first-2]['expected']:
        correction[first-1]=results[first-2]['expected']
        # Only repair first confirmed mistake; later lines must be reviewed again.
    return {'status':status,'summary':summary,'firstError':first,'firstErrorCertain':firstcertain,
            'elapsedMs':round((time.perf_counter()-start)*1000,2),'steps':results,'normalized':[txt(canonical(q,c)) for q in parsed],
            'ast':[tree(q) for q in parsed],'latex':rendered,'rocLatex':rendered_rocs,
            'formatVersion':FORMAT_VERSION,'correction':correction}
