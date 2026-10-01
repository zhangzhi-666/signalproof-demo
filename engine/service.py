"""SignalProof: bounded symbolic rules with auditable proof paths. No eval/parse_expr."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vendor'))
import ast, json, re, time, math
from collections import deque
import sympy as S

SYMBOLS = {k: S.Symbol(k, real=True) for k in ['t','w','a','b','c','q','v','tau','T','w0','x0','x1','h0','h1']}
SYMBOLS.update({k:S.Symbol(k, integer=True) for k in ['n','k','m']})
SYMBOLS.update({k:S.Symbol(k) for k in ['s','z']})
t,w,s,z,n = [SYMBOLS[k] for k in ['t','w','s','z','n']]
OPAQUE = ['FT','LT','ZT','Conv','D','Int0','delta','u','x','h','g','y','X','H','G','Y']
FUNCS = {k:S.Function(k) for k in OPAQUE}
FUNCS.update({'exp':S.exp,'sin':S.sin,'cos':S.cos,'sqrt':S.sqrt,'abs':S.Abs,'Abs':S.Abs,'conjugate':S.conjugate,'re':S.re,'log':S.log})
ARITY = {'FT':(3,), 'LT':(3,), 'ZT':(3,), 'Conv':(3,), 'D':(2,3), 'Int0':(2,)}
for _f in FUNCS:
    ARITY.setdefault(_f,(1,))

def fn(name,*args): return FUNCS[name](*args)
def name(e): return e.func.__name__
def isfn(e,f): return name(e)==f
def txt(e): return str(e).replace('**','^')
def tree(e,level=0):
    if level>12: return '  '*level+'…'
    return '  '*level+(name(e) if e.args else str(e))+''.join('\n'+tree(a,level+1) for a in e.args)

class InputError(Exception): pass

def parse(text):
    if not isinstance(text,str) or not text.strip(): raise InputError('表达式不能为空。')
    if len(text)>1200: raise InputError('单行最多 1200 个字符。')
    text=text.replace('ω','w').replace('τ','tau').replace('π','pi').replace('−','-').replace('×','*').replace('^','**')
    try: root=ast.parse(text.strip(), mode='eval')
    except (SyntaxError,RecursionError) as ex: raise InputError('公式语法不正确，请使用显式乘号 * 和成对括号。') from ex
    if len(list(ast.walk(root)))>250: raise InputError('表达式过于复杂，请拆成多步。')
    denoms=[]
    def read(a,depth=0):
        if depth>22: raise InputError('嵌套层数超过 22。')
        r=lambda v:read(v,depth+1)
        if isinstance(a,ast.Constant) and type(a.value) in (int,float):
            if not math.isfinite(float(a.value)) or abs(a.value)>1e8: raise InputError('数值超出 Demo 范围。')
            return S.Rational(str(a.value))
        if isinstance(a,ast.Name):
            if a.id in ('I','j'): return S.I
            if a.id=='pi': return S.pi
            if a.id not in SYMBOLS: raise InputError('不支持的变量：'+a.id+'。请查看语法说明。')
            return SYMBOLS[a.id]
        if isinstance(a,ast.UnaryOp) and isinstance(a.op,(ast.UAdd,ast.USub)):
            return r(a.operand) if isinstance(a.op,ast.UAdd) else -r(a.operand)
        if isinstance(a,ast.BinOp):
            l,b=r(a.left),r(a.right)
            if isinstance(a.op,ast.Add): return S.Add(l,b,evaluate=False)
            if isinstance(a.op,ast.Sub): return S.Add(l,-b,evaluate=False)
            if isinstance(a.op,ast.Mult): return S.Mul(l,b,evaluate=False)
            if isinstance(a.op,ast.Div):
                if b==0: raise InputError('分母不能为零。')
                denoms.append(b)
                return S.Mul(l,S.Pow(b,-1,evaluate=False),evaluate=False)
            if isinstance(a.op,ast.Pow):
                if b.is_number and abs(b)>16: raise InputError('数值指数绝对值上限为 16。')
                if b.is_negative: denoms.append(l)
                return S.Pow(l,b,evaluate=False)
        if isinstance(a,ast.Call) and isinstance(a.func,ast.Name) and a.func.id in FUNCS and not a.keywords:
            f=a.func.id
            if len(a.args) not in ARITY[f]: raise InputError(f+' 的参数数量不正确。')
            args=[r(v) for v in a.args]
            if f in ('FT','LT','ZT'):
                expected={'FT':(t,w),'LT':(t,s),'ZT':(n,z)}[f]
                if tuple(args[1:])!=expected: raise InputError(f+' 变量约定不匹配；应使用 '+str(expected))
            if f in ('Conv','D','Int0') and not isinstance(args[-1] if f!='D' or len(args)==2 else args[1],S.Symbol):
                raise InputError(f+' 的变量参数必须是变量名。')
            if f=='D' and len(args)==3 and args[2] not in (1,2): raise InputError('导数阶数支持 1 或 2。')
            return FUNCS[f](*args)
        raise InputError('只允许白名单数学语法；不支持属性访问、代码、下标或任意函数。')
    value=read(root.body)
    if value.has(S.zoo,S.oo,-S.oo,S.nan): raise InputError('表达式包含除零或非有限数值。')
    return value,denoms

def lineparse(line):
    parts=line.split(';')
    e,d=parse(parts[0])
    roc=''
    if len(parts)>2: raise InputError('每行只允许一个 ROC 条件。')
    if len(parts)==2:
        if not parts[1].strip().upper().startswith('ROC:'): raise InputError('收敛域格式为 ; ROC: abs(z)>1/2')
        roc=parts[1].strip()[4:].strip()
    return e,d,roc

def canonical(e,c):
    e=S.sympify(e)
    for _ in range(2):
        e=e.replace(lambda q:isfn(q,'D'),lambda q:S.diff(q.args[0],q.args[1],int(q.args[2]) if len(q.args)==3 else 1))
        for key,value in c.get('definitions',{}).items():
            a,_=parse(key); b,_=parse(value)
            if not a.is_Function or len(a.args)!=1 or not isinstance(a.args[0],S.Symbol): raise InputError('变换对键应为 X(w)、X(s) 等单参数函数。')
            e=e.replace(lambda q: q.is_Function and q.func==a.func and len(q.args)==1 and
                        q.args[0].free_symbols.intersection({w,s,z})=={a.args[0]},
                        lambda q:b.subs(a.args[0],q.args[0]))
    assumptions=[S.Q.positive(SYMBOLS[k]) for k in c.get('positive',[]) if k in SYMBOLS]
    if assumptions: e=S.refine(e,S.And(*assumptions))
    return S.simplify(e)

def equal(a,b,c):
    if a==b: return True
    try: return canonical(a-b,c)==0
    except (ValueError,NotImplementedError,TypeError): return False

def positive(a,c): return a.is_positive is True or str(a) in c.get('positive',[])
def nonzero(a,c): return a.is_zero is False or positive(a,c) or str(a) in c.get('nonzero',[])
def base(e,var): return e.is_Function and name(e) in ('x','h','g','y') and e.args==(var,)
def spectrum(e,var): return fn(name(e).upper(),var)
def affine(e,var):
    try:
        aa=S.diff(e,var); bb=S.simplify(e-aa*var)
        if not aa.has(var) and not bb.has(var): return aa,bb
    except Exception: pass
    return None
def split_const(e,var):
    if not e.is_Mul: return None
    a,b=e.as_independent(var,as_Add=False)
    return (a,b) if a!=1 else None

RULEDATA = [
('C01','卷积','卷积交换律','Conv(x,h)=Conv(h,x)','卷积存在','Conv(x(t),h(t),t)','Conv(h(t),x(t),t)'),
('C02','卷积','卷积结合律','(x*h)*g=x*(h*g)','相关卷积存在','Conv(Conv(x(t),h(t),t),g(t),t)','Conv(x(t),Conv(h(t),g(t),t),t)'),
('C03','卷积','卷积分配律','(x+h)*g=x*g+h*g','卷积存在','Conv(x(t)+h(t),g(t),t)','Conv(x(t),g(t),t)+Conv(h(t),g(t),t)'),
('C04','卷积','常数提取','(a x)*h=a(x*h)','a 与积分变量无关','Conv(2*x(t),h(t),t)','2*Conv(x(t),h(t),t)'),
('C05','卷积','单位冲激卷积','x*δ=x','分布意义','Conv(x(t),delta(t),t)','x(t)'),
('C06','卷积','移位冲激卷积','x*δ(t-a)=x(t-a)','实数时移；离散时为整数','Conv(x(t),delta(t-2),t)','x(t-2)'),
('C07','卷积','零信号卷积','x*0=0','卷积定义成立','Conv(x(t),0,t)','0'),
('C08','卷积','卷积求导','D(x*h)=(Dx)*h','可交换求导与卷积','D(Conv(x(t),h(t),t),t)','Conv(D(x(t),t),h(t),t)'),
('F01','傅里叶','傅里叶线性','F{a x+b h}=aX+bH','相关傅里叶变换存在','FT(2*x(t)+h(t),t,w)','2*X(w)+H(w)'),
('F02','傅里叶','时移性质','F{x(t-a)}=exp(-I*w*a) X(w)','a 为实数','FT(x(t-2),t,w)','exp(-2*I*w)*X(w)'),
('F03','傅里叶','频移性质','F{exp(I*b*t)x(t)}=X(w-b)','b 为实数','FT(exp(3*I*t)*x(t),t,w)','X(w-3)'),
('F04','傅里叶','尺度变换','F{x(a*t)}=X(w/a)/abs(a)','a 为非零实数','FT(x(-2*t),t,w)','X(-w/2)/2'),
('F05','傅里叶','共轭性质','F{conjugate(x(t))}=conjugate(X(-w))','相关变换存在','FT(conjugate(x(t)),t,w)','conjugate(X(-w))'),
('F06','傅里叶','时域求导','F{x^(k)}=(I*w)^k X(w)','分布意义或边界项消失','FT(D(x(t),t),t,w)','I*w*X(w)'),
('F07','傅里叶','乘以时间','F{t*x}=I*D(X,w)','频谱可微','FT(t*x(t),t,w)','I*D(X(w),w)'),
('F08','傅里叶','卷积定理','F{x*h}=X*H','卷积与变换存在','FT(Conv(x(t),h(t),t),t,w)','X(w)*H(w)'),
('F09','傅里叶','时域乘积','F{x*h普通乘法}=Conv(X,H,w)/(2*pi)','频域卷积存在','FT(x(t)*h(t),t,w)','Conv(X(w),H(w),w)/(2*pi)'),
('F10','傅里叶','冲激变换对','F{delta(t)}=1','分布意义','FT(delta(t),t,w)','1'),
('F11','傅里叶','因果指数变换对','F{exp(-a*t)u(t)}=1/(a+I*w)','a>0','FT(exp(-2*t)*u(t),t,w)','1/(2+I*w)'),
('F12','傅里叶','高斯变换对','F{exp(-a*t^2)}=sqrt(pi/a)*exp(-w^2/(4*a))','a>0','FT(exp(-2*t^2),t,w)','sqrt(pi/2)*exp(-w^2/8)'),
('L01','拉普拉斯','拉普拉斯线性','L{a x+b h}=aX+bH','相关收敛半平面公共部分','LT(2*x(t)+h(t),t,s)','2*X(s)+H(s)'),
('L02','拉普拉斯','一阶导数与初值','L{x\u2032}=sX-x(0-)','初值 x0；未给初值时保留未知判断','LT(D(x(t),t),t,s)','s*X(s)-x0'),
('L03','拉普拉斯','二阶导数与初值','L{x\u2033}=s^2 X-s*x0-x1','初值 x0 与 x1','LT(D(x(t),t,2),t,s)','s^2*X(s)-s*x0-x1'),
('L04','拉普拉斯','乘以时间','L{t*x}=-D(X,s)','可交换微分与积分','LT(t*x(t),t,s)','-D(X(s),s)'),
('L05','拉普拉斯','指数频移','L{exp(a*t)x}=X(s-a)','ROC 同步平移','LT(exp(-2*t)*x(t),t,s)','X(s+2)'),
('L06','拉普拉斯','因果时移','L{x(t-a)u(t-a)}=exp(-a*s)X(s)','a>0；因果信号','LT(x(t-2)*u(t-2),t,s)','exp(-2*s)*X(s)'),
('L07','拉普拉斯','因果卷积定理','L{x*h}=X(s)H(s)','x,h 为因果信号','LT(Conv(x(t),h(t),t),t,s)','X(s)*H(s)'),
('L08','拉普拉斯','零起点积分','L{Int0(x,t)}=X(s)/s','从0开始积分','LT(Int0(x(t),t),t,s)','X(s)/s'),
('L09','拉普拉斯','单位阶跃变换对','L{u(t)}=1/s','Re(s)>0','LT(u(t),t,s)','1/s; ROC: re(s)>0'),
('L10','拉普拉斯','因果指数变换对','L{exp(-a*t)u(t)}=1/(s+a)','Re(s)>-a','LT(exp(-2*t)*u(t),t,s)','1/(s+2); ROC: re(s)>-2'),
('Z01','Z变换','Z变换线性','Z{a x+b h}=aX+bH','ROC 至少包含公共收敛区','ZT(2*x(n)+h(n),n,z)','2*X(z)+H(z)'),
('Z02','Z变换','序列移位','Z{x(n-k)}=z^(-k)X(z)','k为整数；0与无穷端点需另检','ZT(x(n-2),n,z)','z^(-2)*X(z)'),
('Z03','Z变换','序列反转','Z{x(-n)}=X(1/z)','ROC 半径取倒数','ZT(x(-n),n,z)','X(1/z)'),
('Z04','Z变换','指数序列乘积','Z{a^n*x(n)}=X(z/a)','a≠0；ROC 半径乘abs(a)','ZT(2^n*x(n),n,z)','X(z/2)'),
('Z05','Z变换','乘以序号','Z{n*x(n)}=-z*D(X,z)','原ROC内成立','ZT(n*x(n),n,z)','-z*D(X(z),z)'),
('Z06','Z变换','离散卷积定理','Z{x*h}=X(z)H(z)','ROC 至少包含公共收敛区','ZT(Conv(x(n),h(n),n),n,z)','X(z)*H(z)'),
('Z07','Z变换','序列共轭','Z{conjugate(x(n))}=conjugate(X(conjugate(z)))','ROC 半径不变','ZT(conjugate(x(n)),n,z)','conjugate(X(conjugate(z)))'),
('Z08','Z变换','单位冲激变换对','Z{delta(n)}=1','全z平面含0、无穷','ZT(delta(n),n,z)','1'),
('Z09','Z变换','右边指数序列','Z{a^n*u(n)}=z/(z-a)','abs(z)>abs(a)','ZT((1/2)^n*u(n),n,z)','z/(z-1/2); ROC: abs(z)>1/2'),
('Z10','Z变换','左边指数序列','Z{-a^n*u(-n-1)}=z/(z-a)','abs(z)<abs(a)；a≠0','ZT(-(1/2)^n*u(-n-1),n,z)','z/(z-1/2); ROC: abs(z)<1/2'),
('F00','傅里叶','已知傅里叶变换对','FT(x(t),t,w)=X(w)','X 为 x 的已声明变换','FT(x(t),t,w)','X(w)'),
('L00','拉普拉斯','已知拉普拉斯变换对','LT(x(t),t,s)=X(s)','X 为 x 的已声明变换','LT(x(t),t,s)','X(s)'),
('Z00','Z变换','已知Z变换对','ZT(x(n),n,z)=X(z)','X 为 x 的已声明变换','ZT(x(n),n,z)','X(z)')]
RULES=[dict(zip(['id','category','name','formula','conditions','exampleBefore','exampleAfter'],q)) for q in RULEDATA]
RULEMAP={r['id']:r for r in RULES}

def rewrite(rid,e,c):
    """Returns (replacement, unresolved conditions, ROC). None means no match."""
    out=lambda v,needs=None,roc='':(v,needs or [],roc)
    if rid.startswith('C'):
        if rid=='C08' and isfn(e,'D') and isfn(e.args[0],'Conv'):
            a,b,v=e.args[0].args
            if e.args[1]==v and len(e.args)==2: return out(fn('Conv',fn('D',a,v),b,v))
        if not isfn(e,'Conv'): return None
        a,b,v=e.args
        if rid=='C01': return out(fn('Conv',b,a,v))
        if rid=='C02' and isfn(a,'Conv') and a.args[2]==v: return out(fn('Conv',a.args[0],fn('Conv',a.args[1],b,v),v))
        if rid=='C03':
            if a.is_Add: return out(S.Add(*[fn('Conv',q,b,v) for q in a.args]))
            if b.is_Add: return out(S.Add(*[fn('Conv',a,q,v) for q in b.args]))
        if rid=='C04':
            k=split_const(a,v)
            if k: return out(k[0]*fn('Conv',k[1],b,v))
            k=split_const(b,v)
            if k: return out(k[0]*fn('Conv',a,k[1],v))
        if rid in ('C05','C06'):
            if isfn(a,'delta'): a,b=b,a
            if isfn(b,'delta'):
                q=affine(b.args[0],v)
                if q and q[0]==1:
                    shift=-q[1]
                    if (rid=='C05' and shift==0) or (rid=='C06' and shift!=0):
                        needs=[] if v!=n or shift.is_integer else ['离散时移必须是整数']
                        if isfn(a,'Conv') and a.args[2]==v:
                            return out(fn('Conv',a.args[0].subs(v,v-shift),a.args[1],v),needs)
                        if any(name(q) in ('Conv','Int0','D') for q in S.preorder_traversal(a)): return None
                        return out(a.subs(v,v-shift),needs)
        if rid=='C07' and (a==0 or b==0): return out(S.Integer(0))
        return None
    typ={'F':'FT','L':'LT','Z':'ZT'}[rid[0]]
    if not isfn(e,typ): return None
    a,v,f=e.args; trans=lambda q:fn(typ,q,v,f)
    if rid.endswith('00') and base(a,v): return out(spectrum(a,f))
    if rid in ('F01','L01','Z01'):
        if a.is_Add: return out(S.Add(*[trans(q) for q in a.args]))
        k=split_const(a,v)
        if k: return out(k[0]*trans(k[1]))
    if rid in ('F02','F04','Z02','Z03') and a.is_Function and name(a) in ('x','h','g','y'):
        q=affine(a.args[0],v)
        if q:
            aa,bb=q; X=lambda arg:fn(name(a).upper(),arg)
            if rid=='F02' and aa==1 and bb!=0: return out(S.exp(S.I*f*bb)*X(f),[] if bb.is_real is True else ['时移参数必须为实数'])
            if rid=='F04' and aa not in (0,1):
                needs=[] if nonzero(aa,c) else [str(aa)+'≠0']
                if aa.is_real is not True or bb.is_real is not True: needs.append('尺度与时移参数必须为实数')
                return out(S.exp(S.I*f*bb/aa)*X(f/aa)/S.Abs(aa),needs)
            if rid=='Z02' and aa==1 and bb!=0: return out(f**bb*X(f),[] if bb.is_integer else ['移位为整数'])
            if rid=='Z03' and aa==-1 and bb==0: return out(X(1/f))
    if rid in ('F03','L05') and a.is_Mul:
        for ex in a.args:
            if ex.func==S.exp:
                b=S.simplify(ex.args[0]/v); rest=S.simplify(a/ex)
                if b.has(v) or not base(rest,v): continue
                if rid=='F03':
                    shift=S.simplify(b/S.I)
                    if shift.is_real is not True: continue
                    return out(spectrum(rest,f-shift))
                return out(spectrum(rest,f-b))
    if rid in ('F05','Z07') and a.func==S.conjugate and base(a.args[0],v):
        return out(S.conjugate(spectrum(a.args[0],-f if rid=='F05' else S.conjugate(f))))
    if rid in ('F06','L02','L03') and isfn(a,'D') and a.args[1]==v and base(a.args[0],v):
        order=int(a.args[2]) if len(a.args)==3 else 1
        X=spectrum(a.args[0],f); sg=name(a.args[0])
        ini=c.get('initial',{})
        x0=S.sympify(str(ini.get(sg+'0',sg+'0')),locals=SYMBOLS)
        x1=S.sympify(str(ini.get(sg+'1',sg+'1')),locals=SYMBOLS)
        if rid=='F06': return out((S.I*f)**order*X)
        if rid=='L02' and order==1: return out(f*X-x0,[] if sg+'0' in ini else ['需要提供 '+sg+'(0-) 初值'])
        if rid=='L03' and order==2: return out(f*f*X-f*x0-x1,[] if all(sg+str(k) in ini for k in (0,1)) else ['需要提供函数与一阶导数在 0- 的初值'])
    if rid in ('F07','L04','Z05') and a.is_Mul:
        rest=S.simplify(a/v)
        if base(rest,v):
            return out({'F07':S.I,'L04':-1,'Z05':-f}[rid]*fn('D',spectrum(rest,f),f))
    if rid in ('F08','L07','Z06') and isfn(a,'Conv') and a.args[2]==v:
        return out(trans(a.args[0])*trans(a.args[1]),['需要声明因果信号'] if rid=='L07' and not c.get('causal') else [])
    if rid=='F09' and a.is_Mul and len(a.args)==2 and all(base(q,v) for q in a.args):
        return out(fn('Conv',spectrum(a.args[0],f),spectrum(a.args[1],f),f)/(2*S.pi))
    if rid in ('F10','Z08') and isfn(a,'delta'):
        q=affine(a.args[0],v)
        if q and q[0]==1:
            if rid=='F10': return out(S.exp(S.I*f*q[1]))
            return out(f**q[1],[] if q[1].is_integer else ['离散冲激移位必须为整数'])
    if rid in ('F11','L10'):
        ex=S.simplify(a/fn('u',v)) if a.has(fn('u',v)) else (a if rid=='L10' else None)
        if ex is not None and ex.func==S.exp:
            rate=S.simplify(-ex.args[0]/v)
            if not rate.has(v):
                if rid=='F11': return out(1/(rate+S.I*f),[] if positive(rate,c) else [str(rate)+'>0'])
                return out(1/(f+rate),roc='re(s)>'+txt(-rate))
    if rid=='F12' and a.func==S.exp:
        rate=S.simplify(-a.args[0]/v**2)
        if not rate.has(v): return out(S.sqrt(S.pi/rate)*S.exp(-f*f/(4*rate)),[] if positive(rate,c) else [str(rate)+'>0'])
    if rid=='L06' and a.is_Mul:
        for sig in a.args:
            if sig.is_Function and name(sig) in ('x','h','g','y'):
                q=affine(sig.args[0],v)
                gate=S.simplify(a/sig)
                if q and q[0]==1 and isfn(gate,'u') and S.simplify(gate.args[0]-sig.args[0])==0:
                    delay=-q[1]; needs=[]
                    if not positive(delay,c): needs.append('延迟参数>0')
                    if not c.get('causal'): needs.append('需要声明因果信号')
                    return out(S.exp(-delay*f)*spectrum(sig,f),needs)
    if rid=='L08' and isfn(a,'Int0') and a.args[1]==v: return out(trans(a.args[0])/f)
    if rid=='L09' and a in (fn('u',v),S.Integer(1)): return out(1/f,roc='re(s)>0')
    if rid=='Z04' and a.is_Mul:
        for q in a.args:
            if q.is_Pow and q.exp==v and not q.base.has(v):
                rest=S.simplify(a/q)
                if base(rest,v): return out(spectrum(rest,f/q.base),[] if nonzero(q.base,c) else ['指数底数≠0'])
    if rid in ('Z09','Z10'):
        argument=v if rid=='Z09' else -v-1
        step=next((q for q in S.preorder_traversal(a) if isfn(q,'u') and S.simplify(q.args[0]-argument)==0),None)
        rest=S.simplify(a/step) if step is not None else None
        if rest is not None:
            if rid=='Z10': rest=-rest
            if rest==1: rate=S.Integer(1)
            elif rest.is_Pow and not rest.base.has(v):
                power=S.simplify(rest.exp/v)
                if power.has(v): return None
                rate=S.simplify(rest.base**power)
            else: return None
            needs=[] if rid=='Z09' or nonzero(rate,c) else ['指数底数≠0']
            return out(f/(f-rate),needs,'abs(z)'+('>' if rid=='Z09' else '<')+txt(S.Abs(rate)))
    return None

def reduce_expression(e,c):
    """Apply only terminating, size-directed rules; leave exchanges to bounded search."""
    current=e;path=[];conditions=[];rocs=[]
    for _ in range(32):
        changed=False
        for node in S.postorder_traversal(current):
            for rule in RULES:
                if rule['id'] in ('C01','C02'): continue
                r=rewrite(rule['id'],node,c)
                if r is None: continue
                val,needs,roc=r
                new=current.xreplace({node:val})
                if new==current: continue
                path.append({'ruleId':rule['id'],'before':txt(current),'after':txt(new)})
                current=new;conditions.extend(needs)
                if roc: rocs.append(roc)
                changed=True
                break
            if changed: break
        if not changed or conditions: break
    return current,path,conditions,rocs

def candidates(e,c,maxdepth=8):
    seen={S.srepr(e)}; queue=deque([(e,[],[],[])])
    found=[]
    while queue and len(found)<90:
        current,path,conditions,rocs=queue.popleft()
        if len(path)>=maxdepth: continue
        # Specific, informative rewrites precede harmless commutativity.
        nodes=list(S.preorder_traversal(current))
        for node in nodes:
            for rule in RULES:
                if rule['id']=='C01' and len(path)>1: continue
                r=rewrite(rule['id'],node,c)
                if r is None: continue
                val,needs,roc=r
                new=current.xreplace({node:val})
                key=S.srepr(new)
                if key in seen: continue
                seen.add(key)
                step={'ruleId':rule['id'],'before':txt(current),'after':txt(new)}
                item=(new,path+[step],conditions+needs,rocs+([roc] if roc else []))
                found.append(item)
                if not needs: queue.append(item)
                if len(found)>=90: break
            if len(found)>=90: break
    return found

def roc_parse(text):
    compact=text.replace(' ','').replace('|z|','abs(z)').replace('Re(s)','re(s)').replace('Abs(z)','abs(z)')
    m=re.fullmatch(r'(abs\(z\)|re\(s\))([<>]=?)(.+)',compact)
    if not m: raise InputError('Demo 收敛域支持 abs(z)>a、abs(z)<a 或 re(s)>a。')
    value,_=parse(m.group(3));return m.group(1),m.group(2),S.simplify(value)

def roc_compare(expected,actual):
    if not expected: return 'correct'
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
        variables=a.free_symbols | b.free_symbols | d.free_symbols
        sub={q:val for q in variables}
        for q in variables:
            if q.is_integer: sub[q]=S.Integer(round(float(val)*3))
            if str(q) in c.get('positive',[]): sub[q]=abs(val)
            if q in (s,z): sub[q]=5+val+S.I/3
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
        try:
            difference=complex(d.subs(sub).evalf(40))
            if not all(math.isfinite(v) for v in (difference.real,difference.imag)): continue
            try:
                aa=complex(canonical(a,c).subs(sub).evalf(40));bb=complex(canonical(b,c).subs(sub).evalf(40))
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
    functions={name(q) for e in (a,b) for q in S.preorder_traversal(e) if q.is_Function}
    if functions.intersection(('FT','LT','ZT','Int0','delta','u')): return []
    if functions.intersection(('x','h','g','y')) and functions.intersection(('X','H','G','Y')): return []
    if not functions.intersection(('x','h','g','y','X','H','G','Y')): return []
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

def check_step(before,after,c):
    lhs,den1,roc1=lineparse(before); rhs,den2,roc2=lineparse(after)
    c=dict(c);c['_activeRocs']=[q for q in (roc1,roc2) if q]
    if roc1: roc_parse(roc1)
    if roc2: roc_parse(roc2)
    base_result={'before':before,'after':after,'expected':'','ruleIds':[],'ruleNames':[],'conditions':[],
                 'evidence':[],'diff':{},'trace':[],'samples':[],'inherited':False}
    if equal(lhs,rhs,c):
        lost=[]
        def denominator_factors(q):
            q=S.factor(q)
            if q.is_Mul: return [v for child in q.args for v in denominator_factors(child)]
            if q.is_Pow and q.exp.is_integer and q.exp!=0: return denominator_factors(q.base)
            return [q] if q.free_symbols else []
        remaining=[factor for q in den2 for factor in denominator_factors(q)]
        for d in den1:
            if not d.free_symbols: continue
            if all(nonzero(factor,c) or any(equal(factor,q,c) for q in remaining) for factor in denominator_factors(d)): continue
            # A canceled domain restriction needs an explicit assumption.
            if not S.denom(S.together(rhs)).has(d): lost.append(txt(d)+'≠0')
        original=[factor for q in den1 for factor in denominator_factors(q)]
        original.extend(denominator_factors(S.denom(canonical(lhs,c))))
        for d in den2:
            if not d.free_symbols: continue
            for factor in denominator_factors(d):
                if not nonzero(factor,c) and not any(equal(factor,q,c) for q in original):
                    lost.append(txt(factor)+'≠0（新引入的分母）')
        status='unknown' if lost else 'correct'
        if roc1:
            roc_status=roc_compare([roc1],roc2)
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
        rocs=rocs or ([roc1] if roc1 else [])
        if len(set(rocs))>1: needs=needs+['组合变换的精确收敛域需要另行确认']
        status='unknown' if needs else roc_compare(rocs,roc2)
        exp=txt(ex)+('; ROC: '+rocs[-1] if rocs else '')
        ids=list(dict.fromkeys(q['ruleId'] for q in path))
        why='规则重写链与目标表达式符号一致。'
        if needs: why='表达式符合规则形式，但前提尚未满足：'+'；'.join(needs)
        elif status=='incomplete': why='代数表达式正确，但缺少收敛域。变换结果必须包含 ROC。'
        elif status=='wrong': why='代数表达式正确，但收敛域方向或边界不正确。'
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
    start=time.perf_counter();c=dict(c or {})
    if not isinstance(steps,list) or not 2<=len(steps)<=16: raise InputError('请输入 2–16 行推导。')
    if not isinstance(c.get('initial',{}),dict): raise InputError('initial 必须是对象。')
    for key,val in c.get('initial',{}).items():
        if key not in ('x0','x1','h0','h1','g0','g1','y0','y1') or type(val) not in (int,float): raise InputError('初值须为 x0/x1/h0/h1 等数值。')
    if not isinstance(c.get('definitions',{}),dict) or len(c.get('definitions',{}))>8: raise InputError('definitions 最多包含8个变换对。')
    # Substitute declared initial values into both submitted and generated expressions.
    effective=[]
    for line in steps:
        for key,val in c.get('initial',{}).items(): line=re.sub(r'\b'+key+r'\b','('+str(val)+')',line)
        effective.append(line)
    parsed=[lineparse(line)[0] for line in effective]
    results=[];first=None; uncertain=False; firstcertain=True
    for i in range(1,len(steps)):
        row=check_step(effective[i-1],effective[i],c)
        row['beforeLatex']=S.latex(parsed[i-1]);row['afterLatex']=S.latex(parsed[i])
        row['expectedLatex']=S.latex(lineparse(row['expected'])[0]) if row.get('expected') else ''
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
            'ast':[tree(q) for q in parsed],'latex':[S.latex(q) for q in parsed],'correction':correction}

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
    action=data.get('action','verify')
    if action=='catalog': return {'rules':RULES,'examples':EXAMPLES,'ruleCount':len(RULES),'engine':'SymPy '+S.__version__,'version':'1.0.0'}
    if action=='verify': return verify(data.get('steps',[]),data.get('context',{}))
    if action=='tests': return runtests()
    if action=='robustness': return runtests('robustness.json')
    raise InputError('未知操作。')

if __name__=='__main__':
    if hasattr(sys.stdin,'reconfigure'): sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    for raw in sys.stdin:
        try:
            if len(raw)>100000: raise InputError('请求过大。')
            result=dispatch(json.loads(raw))
        except Exception as ex: result={'error':str(ex),'status':'error','summary':str(ex)}
        print(json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)
        if '--once' in sys.argv: break
