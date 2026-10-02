"""Public API and JSON request dispatch for the browser and Python clients."""
import json
import os
import sys
import time

# Compatibility with scripts that put engine/ itself on sys.path.
if not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = 'engine'

import sympy as S
from .syntax import InputError, SYMBOLS, OPAQUE, FUNCS, ARITY, t, w, s, z, n, fn, name, isfn, txt, tree, parse, lineparse, positive, nonzero
from .formatting import FORMAT_VERSION, SignalLatexPrinter, signal_latex, roc_latex, format_steps, presentation_latex
from .rules import RULEDATA, RULES, RULEMAP, rewrite, reduce_expression, candidates
from .diagnostics import canonical, equal, roc_parse, roc_compare, proofdiff, sample_counterexample, formal_counterexample, explain_error
from .verification import LABELS, check_step, verify

EXAMPLES=[
{'id':'ft-shift','title':'时移的一个负号','category':'傅里叶','description':'第2行误写相位；第3行代入本身正确，却继承了前错。',
 'steps':['FT(x(t-2),t,w)','exp(2*I*w)*X(w)','exp(2*I*w)/(1+I*w)'],
 'context':{'definitions':{'X(w)':'1/(1+I*w)'},'causal':True,'initial':{}}},
{'id':'ft-scale','title':'负尺度，正幅度','category':'傅里叶','description':'时间反转与压缩不能把幅度系数变成负数。','steps':['FT(x(-2*t),t,w)','-X(-w/2)/2'],'context':{}},
{'id':'lt-initial','title':'不能漏掉的初值','category':'拉普拉斯','description':'已知 x(0-)=2；单边拉普拉斯必须保留初值项。','steps':['LT(D(x(t),t),t,s)','s*X(s)'],'context':{'initial':{'x0':2},'causal':False}},
{'id':'z-roc','title':'答案还差一个收敛域','category':'Z变换','description':'相同有理式可能对应不同序列，ROC 是答案的一部分。','steps':['ZT((1/2)^n*u(n),n,z)','z/(z-1/2)'],'context':{}},
{'id':'conv','title':'卷积不是普通相乘','category':'卷积','description':'用冲激性质验证时移，同时检查后续代数。','steps':['Conv(x(t),delta(t-2),t)','x(t+2)'],'context':{}},
{'id':'multi','title':'一步使用多条规则','category':'傅里叶','description':'线性与时移组合，系统展开可追溯的规则路径。','steps':['FT(2*x(t-3),t,w)','2*exp(-3*I*w)*X(w)'],'context':{}},
{'id':'unknown','title':'有边界的判断','category':'傅里叶','description':'对不支持的时变调制保留未知，不会强行给出正确结论。','steps':['FT(exp(I*t^2)*x(t),t,w)','X(w)'],'context':{}},
{'id':'lt-correct','title':'完整的拉普拉斯变换','category':'拉普拉斯','description':'代数式、收敛域和规则证据同时验证。','steps':['LT(exp(-2*t)*u(t),t,s)','1/(s+2); ROC: re(s)>-2'],'context':{}}]

def runtests(filename='tests.json'):
    start=time.perf_counter();path=os.path.join(os.path.dirname(__file__),'..','data',filename)
    with open(path,encoding='utf-8-sig') as f: fixtures=json.load(f)
    if isinstance(fixtures,dict): fixtures=fixtures.get('tests',fixtures.get('cases',[]))
    results=[]
    for case in fixtures:
        try:
            r=verify(case['steps'],case.get('context',{}));actual=r['status'];first=r['firstError'];err=''
        except InputError as ex: actual='unknown';first=None;err='输入被安全拒绝（不是数学未知）：'+str(ex)
        except Exception as ex: actual='error';first=None;err=str(ex)
        expected=case.get('expected',case.get('expectedVerdict'))
        expfirst=case.get('expectedFirstError')
        passed=actual==expected and first==expfirst
        results.append(dict(case,actual=actual,actualFirstError=first,passed=passed,error=err,inputRejected=err.startswith('输入被安全拒绝')))
    return {'total':len(results),'passed':sum(x['passed'] for x in results),'failed':sum(not x['passed'] for x in results),
        'correctCount':sum(x.get('expected')=='correct' for x in results),'wrongCount':sum(x.get('expected')=='wrong' for x in results),
        'elapsedMs':round((time.perf_counter()-start)*1000,2),'results':results}

def dispatch(data):
    if not isinstance(data,dict): raise InputError('请求必须是 JSON 对象。')
    action=data.get('action','verify')
    if action=='catalog':
        rules=[]
        for rule in RULES:
            formatted=format_steps([rule['exampleBefore'],rule['exampleAfter']])['lines']
            rules.append(dict(rule,beforeLatex=formatted[0]['latex'],afterLatex=formatted[1]['latex'],
                              beforeRocLatex=formatted[0]['rocLatex'],afterRocLatex=formatted[1]['rocLatex']))
        return {'rules':rules,'examples':EXAMPLES,'ruleCount':len(RULES),'engine':'SymPy '+S.__version__,
                'version':'1.0.0','formatVersion':FORMAT_VERSION}
    if action=='format': return format_steps(data.get('steps',[]))
    if action=='verify': return verify(data.get('steps',[]),data.get('context',{}))
    if action=='tests': return runtests()
    if action=='robustness': return runtests('robustness.json')
    raise InputError('未知操作。')
