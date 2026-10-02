"""Symbolic equality, region checks and admissible counterexample evidence."""
import math
import re
import sympy as S
from .syntax import SYMBOLS, OPAQUE, w, s, z, n, name, isfn, txt, parse, nonzero, InputError

def canonical(e,c):
    e=S.sympify(e)
    definition_domains={}
    for key in c.get('definitions',{}):
        declared,_=parse(key)
        definition_domains.setdefault(declared.func,set()).add(declared.args[0])
    for _ in range(2):
        if c.get('causal'):
            e=e.replace(lambda q:name(q) in ('x','h','g','y') and q.args[0].is_negative is True,
                        lambda q:S.Integer(0))
        for key,value in c.get('definitions',{}).items():
            a,_=parse(key); b,_=parse(value)
            if not a.is_Function or len(a.args)!=1 or not isinstance(a.args[0],S.Symbol): raise InputError('变换对键应为 X(w)、X(s) 等单参数函数。')
            e=e.replace(lambda q: q.is_Function and q.func==a.func and len(q.args)==1 and
                        (q.args[0].free_symbols.intersection({w,s,z})=={a.args[0]} or
                         (not q.args[0].free_symbols.intersection({w,s,z}) and len(definition_domains[a.func])==1)),
                        lambda q:b.subs(a.args[0],q.args[0]))
        # Substitute a known spectrum before differentiation. Differentiating an
        # undefined function first can leave unevaluated Derivative/Subs nodes.
        e=e.replace(lambda q:isfn(q,'D'),lambda q:S.diff(q.args[0],q.args[1],int(q.args[2]) if len(q.args)==3 else 1))
        e=e.replace(lambda q:isinstance(q,S.Derivative),lambda q:q.doit())
    assumptions=[S.Q.positive(SYMBOLS[k]) for k in c.get('positive',[]) if k in SYMBOLS]
    if assumptions:
        # Explicit positive symbols also carry realness through Abs/conjugate algebra.
        replacements={SYMBOLS[k]:S.Dummy(k,positive=True,**({'integer':True} if SYMBOLS[k].is_integer is True else {})) for k in c.get('positive',[])}
        e=S.simplify(e.xreplace(replacements)).xreplace({v:k for k,v in replacements.items()})
        e=S.refine(e,S.And(*assumptions))
    return S.simplify(e)

def equal(a,b,c):
    if a==b: return True
    try: return canonical(a-b,c)==0
    except (ValueError,NotImplementedError,TypeError): return False


def denominator_factors(value):
    value=S.factor(value)
    if value.is_Mul: return [factor for child in value.args for factor in denominator_factors(child)]
    if value.is_Pow and value.exp.is_integer and value.exp!=0: return denominator_factors(value.base)
    return [value] if value.free_symbols else []


def domain_changes(before, after, original_denominators, new_denominators, context):
    """Track canceled and introduced restrictions even when algebra simplifies away a/a."""
    old=[f for d in original_denominators for f in denominator_factors(d)]
    new=[f for d in new_denominators for f in denominator_factors(d)]
    for expression,factors in ((before,old),(after,new)):
        for node in S.preorder_traversal(canonical(expression,context)):
            if node.is_Pow and node.exp.is_negative: factors.extend(denominator_factors(node.base))
    conditions=[]
    for source,target,label in ((old,new,''),(new,old,'（新引入的分母）')):
        for factor in source:
            if not nonzero(factor,context) and not any(equal(factor,other,context) for other in target):
                conditions.append(txt(factor)+'≠0'+label)
    return list(dict.fromkeys(conditions))

def roc_parse(text):
    compact=text.replace(' ','').replace('|z|','abs(z)').replace('Re(s)','re(s)').replace('Abs(z)','abs(z)')
    m=re.fullmatch(r'(abs\(z\)|re\(s\))([<>]=?)(.+)',compact)
    if not m: raise InputError('Demo 收敛域支持 abs(z)>a、abs(z)<a 或 re(s)>a。')
    value,_=parse(m.group(3));value=S.simplify(value)
    if value.is_real is not True or value.has(s,z): raise InputError('ROC 边界必须是与 s、z 无关的实数表达式。')
    if m.group(1)=='abs(z)' and m.group(2) in ('<','<=') and value.is_nonpositive:
        raise InputError('该半径上界不能定义非空的开放收敛域。')
    return m.group(1),m.group(2),value

def roc_compare(expected,actual):
    if not expected: return 'unknown' if actual else 'correct'
    if not actual: return 'incomplete'
    e=roc_parse(expected[-1]);a=roc_parse(actual)
    return 'correct' if e[:2]==a[:2] and S.simplify(e[2]-a[2])==0 else 'wrong'

def proofdiff(a,b,path='root'):
    if a==b: return {'path':path,'before':txt(b),'after':txt(a)}
    if a.func==b.func and len(a.args)==len(b.args):
        diffs=[(i,x,y) for i,(x,y) in enumerate(zip(a.args,b.args)) if x!=y]
        if len(diffs)==1:
            i,x,y=diffs[0]; return proofdiff(x,y,path+'.'+name(a)+'['+str(i)+']')
    return {'path':path,'before':txt(b),'after':txt(a)}

def sample_counterexample(a,b,c):
    """Only fully concrete ordinary expressions: never sample distributions/unknown functions."""
    d=canonical(a-b,c)
    if any(q.is_Function and (name(q) in OPAQUE) for q in S.preorder_traversal(d)) or d.has(S.Derivative): return []
    for val in [S.Rational(1,3),S.Rational(-2,3),S.Rational(7,5),S.Rational(-11,4)]:
        restrictions=c.get('_denominators',[])
        variables=a.free_symbols | b.free_symbols | d.free_symbols
        variables.update(*(q.free_symbols for q in restrictions))
        sub={q:val for q in variables}
        for q in variables:
            if q.is_integer: sub[q]=S.Integer(round(float(val)*3))
            if str(q) in c.get('positive',[]): sub[q]=abs(sub[q]) or S.Integer(1)
            if q in (s,z): sub[q]=5+val+S.I/3
            if str(q) in c.get('positive',[]): sub[q]=abs(val) if q.is_integer is not True else S.Integer(max(1,abs(round(float(val)*3))))
        for region in c.get('_activeRocs',[]):
            try:
                variable,operator,bound=roc_parse(region)
                threshold=S.simplify(bound.subs(sub))
                if not threshold.is_number or threshold.is_real is not True: continue
                if variable=='abs(z)' and threshold.is_positive and operator in ('<','<='):
                    sub[z]=threshold*(S.Rational(1,2)+S.I/4)
                elif variable=='abs(z)' and operator in ('>','>='):
                    sub[z]=S.Abs(threshold)+2+S.I/3
                elif variable=='re(s)': sub[s]=threshold+(1 if operator in ('>','>=') else -1)+S.I/3
            except (InputError,TypeError,ValueError): pass
        # A point outside a declared region cannot refute an identity on that region.
        admissible=True
        for region in c.get('_activeRocs',[]):
            try:
                variable,operator,bound=roc_parse(region)
                coordinate=S.Abs(sub.get(z,z)) if variable=='abs(z)' else S.re(sub.get(s,s))
                threshold=bound.subs(sub)
                relation={'<':S.Lt,'>':S.Gt,'<=':S.Le,'>=':S.Ge}[operator](coordinate,threshold)
                if relation is not S.true: admissible=False;break
            except (InputError,TypeError,ValueError): admissible=False;break
        if not admissible: continue
        if any(sub.get(SYMBOLS[key],SYMBOLS[key]).is_positive is not True for key in c.get('positive',[]) if SYMBOLS[key] in variables): continue
        # Evaluate original denominator restrictions before any cancellation.
        if any(S.simplify(q.subs(sub)).is_zero is not False for q in restrictions): continue
        try:
            difference=complex(d.subs(sub).evalf(40))
            if not all(math.isfinite(v) for v in (difference.real,difference.imag)): continue
            try:
                aa=complex(canonical(a,c).subs(sub).evalf(40));bb=complex(canonical(b,c).subs(sub).evalf(40))
                if not all(math.isfinite(v) for v in (aa.real,aa.imag,bb.real,bb.imag)): continue
                scale=1+abs(aa)+abs(bb);expected=str(aa);actual=str(bb)
            except (TypeError,ValueError):
                scale=1;expected=txt(a);actual=txt(b)
            if abs(difference)>1e-8*scale:
                return [{'at':', '.join(txt(q)+'='+txt(v) for q,v in sub.items()) or '常数项','expected':expected,'actual':actual,'error':abs(difference),'difference':str(difference)}]
        except (TypeError,ValueError,OverflowError): pass
    return []

def formal_counterexample(a,b,c):
    """Refute universal signal identities with actual functions, never independent AST atoms.

    Gaussian signals/spectra and stable rational transforms respect conjugation,
    differentiation, convolution and exponential identities. A failed construction
    yields no verdict. Mixed time/frequency expressions are outside this witness model.
    """
    # A witness must respect supplied transform pairs, rather than replacing a
    # declared spectrum with a convenient but inconsistent rational function.
    a=canonical(a,c);b=canonical(b,c)
    functions={name(q) for e in (a,b) for q in S.preorder_traversal(e) if q.is_Function}
    defined_spectra={name(parse(key)[0]).lower() for key in c.get('definitions',{})}
    if {f.lower() for f in functions}.intersection(defined_spectra): return []
    if functions.intersection(('FT','LT','ZT','Int0','delta','u')): return []
    if functions.intersection(('x','h','g','y')) and functions.intersection(('X','H','G','Y')): return []
    if not functions.intersection(('x','h','g','y','X','H','G','Y')): return []
    if c.get('causal') or c.get('initial'):
        # A Gaussian time signal (or its Fourier spectrum) does not in general
        # satisfy caller-supplied causality/initial values. Do not invent evidence.
        if functions.intersection(('x','h','g','y')): return []
        if any(name(q) in ('X','H','G','Y') and not q.args[0].has(s,z)
               for e in (a,b) for q in S.preorder_traversal(e)): return []
    spectrum_domains={v for e in (a,b) for q in S.preorder_traversal(e)
                      if name(q) in ('X','H','G','Y') for v in (w,s,z) if q.args[0].has(v)}
    if len(spectrum_domains)>1: return []
    cache={}
    def gaussian_integral(expr,var):
        total=0
        for term in S.Add.make_args(S.expand(expr)):
            exponent=0;coefficient=S.Integer(1)
            for factor in S.Mul.make_args(term):
                if factor.func==S.exp: exponent+=factor.args[0]
                else: coefficient*=factor
            polynomial=S.Poly(S.expand(exponent),var)
            if polynomial.degree()!=2: raise ValueError('只构造高斯卷积反例')
            aa=polynomial.nth(2);bb=polynomial.nth(1);cc=polynomial.nth(0)
            if aa.is_negative is not True: raise ValueError('反例卷积不收敛')
            weight=S.Poly(S.expand(coefficient),var)
            if weight.degree()>8: raise ValueError('反例次数超限')
            mean=-bb/(2*aa);variance=-1/(2*aa);moment=0
            for (degree,),value in weight.terms():
                moment+=value*sum(S.binomial(degree,2*j)*S.factorial2(2*j-1)*variance**j*mean**(degree-2*j) for j in range(degree//2+1))
            total+=S.sqrt(S.pi/(-aa))*S.exp(cc-bb**2/(4*aa))*moment
        return S.simplify(total)
    def model(e):
        if e in cache: return cache[e]
        if not e.args: return e
        nm=name(e)
        if nm in ('x','h','g','y','X','H','G','Y'):
            index=('x','h','g','y').index(nm.lower())+1
            arg=model(e.args[0])
            if nm.isupper() and arg.has(s):
                ini=c.get('initial',{});v0=S.sympify(ini.get(nm.lower()+'0',1));v1=S.sympify(ini.get(nm.lower()+'1',-index*v0))
                result=v0/(arg+index)+(v1+index*v0)/(arg+index)**2+1/(arg+index)**3
            elif nm.isupper() and arg.has(z): result=arg/(arg-S.Rational(1,index+2))
            else: result=S.exp(-index*(arg-S.Rational(index,3))**2)
        elif nm=='Conv':
            left,right,var=e.args
            if var==n: raise ValueError('离散卷积反例尚未实现')
            tau=S.Dummy('tau',real=True)
            integrand=S.expand(model(left).subs(var,tau)*model(right).subs(var,var-tau))
            result=gaussian_integral(integrand,tau)
        elif nm=='D': result=S.diff(model(e.args[0]),e.args[1],int(e.args[2]) if len(e.args)==3 else 1)
        elif isinstance(e,S.Derivative): result=S.diff(model(e.expr),*e.variable_count)
        else: result=e.func(*[model(q) for q in e.args])
        cache[e]=result
        return result
    try:
        aa=model(a);bb=model(b)
        samples=sample_counterexample(aa,bb,c)
        for item in samples:
            item['model']='可构造反例：第 k 个时域信号/频谱取 exp(-k*(v-k/3)^2)；s 域取符合已给初值的稳定有理函数，z 域取 z/(z-1/(k+2))。'
            item['witnessExpected']=txt(aa);item['witnessActual']=txt(bb)
        return samples
    except (ValueError,TypeError,NotImplementedError,RecursionError): return []

def explain_error(rids,diff,expected,after):
    checks=[('F02','时移相位因子的方向不一致。延迟 a 对应负指数 exp(-I*w*a)。'),
            ('F04','尺度变换需同时替换频率并乘 1/abs(a)，负尺度也不能使用负幅度。'),
            ('F03','调制对应频谱平移，请核对频移方向。'),
            ('F09','时域相乘对应频域卷积，角频率约定下必须带 1/(2*pi)。'),
            ('L02','单边拉普拉斯导数公式包含 x(0-) 初值项。'),
            ('L03','二阶导数必须同时包含 s*x(0-) 与 x\u2032(0-) 两项。'),
            ('Z02','序列延迟对应 z 的负次幂，请核对移位方向。'),
            ('Z04','指数序列相乘应把 z 替换为 z/a。'),
            ('C08','卷积求导只需对一侧求导；不能套用普通乘积求导后相加。')]
    for rid,msg in checks:
        if rid in rids: return msg
    return '该步与已验证的规则候选不一致。下方显示局部结构差异与建议结果。'
